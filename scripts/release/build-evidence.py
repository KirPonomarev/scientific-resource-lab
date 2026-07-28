#!/usr/bin/env python3
"""Build release artifacts and emit ReleaseEvidence/v1.

Steps: clean dist/ -> uv build (sdist + wheel) -> sha256 checksums ->
SBOM -> NOTICE/LICENSE bundle -> ReleaseEvidence/v1 JSON (canonical).
Stdlib + uv only. Publication is performed separately by the trusted
owner-authenticated agent; this script never uploads anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    root = Path.cwd()
    dist = root / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir()
    env = {**os.environ, "SOURCE_DATE_EPOCH": "1704067200"}
    uv = shutil.which("uv") or "uv"
    subprocess.run([uv, "build"], check=True, env=env)  # noqa: S603 - fixed argv
    artifacts = sorted(p for p in dist.iterdir() if p.is_file() and p.suffix in {".whl", ".gz"})
    checksums = {p.name: sha256_file(p) for p in artifacts}
    (dist / "SHA256SUMS.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in checksums.items()),
        encoding="utf-8",
    )
    sbom = json.loads(
        subprocess.run(
            [sys.executable, "scripts/release/sbom.py", "uv.lock", "dist/sbom.json"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    with tempfile.TemporaryDirectory() as tmp:
        bundle = Path(tmp) / "license-bundle.tar.gz"
        with tarfile.open(bundle, "w:gz") as tar:
            for name in ("LICENSE", "NOTICE"):
                tar.add(root / name, arcname=name)
        bundle_bytes = bundle.read_bytes()
    (dist / "license-bundle.tar.gz").write_bytes(bundle_bytes)
    git = shutil.which("git") or "git"
    head = subprocess.run(  # noqa: S603 - fixed argv
        [git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    tag = subprocess.run(  # noqa: S603 - fixed argv
        [git, "describe", "--tags", "--exact-match"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    evidence = {
        "schema_version": "ReleaseEvidence/v1",
        "head_sha": head,
        "tag": tag or None,
        "artifacts": checksums,
        "sbom_sha256": sbom["sha256"],
        "sbom_packages": sbom["packages"],
        "license_bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "source_date_epoch": 1704067200,
        "publication": "trusted-local-agent-after-verification",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    raw = json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n"
    (dist / "release-evidence.json").write_text(raw, encoding="utf-8")
    print(raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
