#!/usr/bin/env python3
"""Generate a minimal deterministic SBOM (JSON) from uv.lock.

Stdlib-only. Reads the TOML lock via tomllib and emits a canonical JSON
document listing every locked package with name, version, and source kind.
This is not a full CycloneDX document; it is a deterministic inventory whose
sha256 travels with ReleaseEvidence/v1.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tomllib
from pathlib import Path

_ARG_LOCK = 1
_ARG_OUT = 2


def main() -> int:
    lock_path = Path(sys.argv[_ARG_LOCK] if len(sys.argv) > _ARG_LOCK else "uv.lock")
    out_path = Path(sys.argv[_ARG_OUT] if len(sys.argv) > _ARG_OUT else "sbom.json")
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = sorted(
        (
            {
                "name": pkg["name"],
                "version": pkg["version"],
                "source": (
                    "registry"
                    if "registry" in pkg.get("source", {})
                    else next(iter(pkg.get("source", {"unknown": None})))
                ),
            }
            for pkg in data.get("package", [])
        ),
        key=lambda p: (p["name"], p["version"]),
    )
    doc = {
        "schema_version": "SrlSbom/v1",
        "generator": "scripts/release/sbom.py",
        "package_count": len(packages),
        "packages": packages,
    }
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    out_path.write_text(raw, encoding="utf-8")
    print(json.dumps({"sbom": str(out_path), "packages": len(packages), "sha256": digest}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
