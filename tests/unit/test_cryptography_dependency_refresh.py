from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

from srl.contracts import object_id

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "uv.lock"
PYPROJECT = ROOT / "pyproject.toml"
RECEIPT = ROOT / "docs" / "verification" / "cryptography-50-reuse-decision-receipt-v1.json"


def _load_toml(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _load_receipt() -> dict[str, object]:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_declared_and_locked_versions_exclude_affected_range() -> None:
    project = _load_toml(PYPROJECT)
    dependencies = project["project"]["dependencies"]  # type: ignore[index]
    assert dependencies.count("cryptography>=50.0.0") == 1  # type: ignore[union-attr]

    lock = _load_toml(LOCK)
    packages = [
        package
        for package in lock["package"]  # type: ignore[index]
        if package["name"] == "cryptography"
    ]
    assert [package["version"] for package in packages] == ["50.0.0"]


def test_reuse_receipt_is_canonical_content_addressed_and_authority_negative() -> None:
    raw = RECEIPT.read_bytes()
    receipt = _load_receipt()
    assert raw == (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()

    unsigned = {key: value for key, value in receipt.items() if key != "receipt_id"}
    assert receipt["receipt_id"] == object_id(unsigned)
    assert receipt["schema_version"] == "ReuseDecisionReceipt/v1"
    assert receipt["decision"] == "REUSE_WITH_SECURITY_UPGRADE"
    assert receipt["canonical_writes"] == 0
    assert receipt["live_actions"] == 0
    assert receipt["grants_authority"] is False
    assert receipt["activates_runtime"] is False
    assert receipt["vulnerable_api_used"] is False


def test_reuse_receipt_binds_lock_and_generated_sbom(tmp_path: Path) -> None:
    receipt = _load_receipt()
    lock_sha256 = "sha256:" + hashlib.sha256(LOCK.read_bytes()).hexdigest()
    assert receipt["candidate_lock_sha256"] == lock_sha256

    output = tmp_path / "sbom.json"
    subprocess.run(  # noqa: S603 - fixed repository script and interpreter
        [sys.executable, "scripts/release/sbom.py", str(LOCK), str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    raw = output.read_bytes()
    sbom = json.loads(raw)
    expected = receipt["candidate_sbom"]
    assert expected == {
        "package_count": 130,
        "schema_version": "SrlSbom/v1",
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }
    assert sbom["package_count"] == 130
    versions = {package["name"]: package["version"] for package in sbom["packages"]}
    assert versions["cryptography"] == "50.0.0"
    assert versions["cffi"] == "2.1.0"
    assert versions["pycparser"] == "3.0"
