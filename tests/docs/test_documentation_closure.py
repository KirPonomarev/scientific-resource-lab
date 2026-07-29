from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUIRED_DOCS = (
    "START-HERE.md",
    "SYSTEM-ATLAS.md",
    "SOLO-AGENT-RUNBOOK.md",
    "CELL-MATRIX.md",
    "CAPABILITY-CATALOG.md",
    "CONTRACT-MATRIX.md",
    "AUTHORITY-MATRIX.md",
    "DATA-CLASSIFICATION.md",
    "FAILURE-ROUTING.md",
    "T7-OPERATIONS.md",
    "COMPUTE-NODE.md",
    "MARKET-INTEGRATION.md",
    "SECURITY-INTEGRATION.md",
    "TRADING-EXECUTION-BOUNDARY.md",
    "PACK-AUTHORING.md",
    "PACK-REVOCATION.md",
    "RECOVERY-RUNBOOK.md",
    "RELEASE-RUNBOOK.md",
)
RECEIPT_PATH = Path("docs/verification/documentation-closure-receipt.json")
SYSTEM_RECEIPT_PATH = Path("docs/verification/system-acceptance-receipt.json")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _receipt() -> dict[str, Any]:
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def _system_receipt() -> dict[str, Any]:
    return json.loads(SYSTEM_RECEIPT_PATH.read_text(encoding="utf-8"))


def _normalize_digest(value: str) -> str:
    return value.removeprefix("sha256:").replace("-", "")


def _sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _receipt_id(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_id"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, 64, 8))


def test_generated_documentation_is_current() -> None:
    solo = _run("scripts/docs/generate_solo_agent_docs.py", "--check")
    system = _run("scripts/docs/generate_system_docs.py", "--check")

    assert solo.returncode == 0, solo.stdout
    assert system.returncode == 0, system.stdout


def test_required_document_set_exists() -> None:
    for doc in REQUIRED_DOCS:
        path = Path(doc)
        assert path.is_file(), doc
        text = path.read_text(encoding="utf-8")
        assert text.startswith(f"# {Path(doc).stem}")
        assert text.endswith("\n")


def test_documentation_closure_receipt_is_authority_negative() -> None:
    receipt = _receipt()

    assert receipt["schema_version"] == "DocumentationClosureReceipt/v1"
    assert receipt["stage_id"] == "S26"
    assert receipt["result"] == "PASS"
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False
    assert receipt["live_actions"] == 0
    assert set(receipt["protected_actions"]["wait_states"]) >= {
        "WAIT_T7_BINDING",
        "WAIT_COMPUTE_NODE",
    }
    assert _normalize_digest(receipt["source_system_acceptance_receipt"]) == (
        _normalize_digest(_system_receipt()["receipt_id"])
    )


def test_documentation_closure_receipt_hashes_required_docs() -> None:
    receipt = _receipt()
    doc_hashes = receipt["required_doc_sha256"]

    assert set(doc_hashes) == set(REQUIRED_DOCS)
    for doc, expected in doc_hashes.items():
        actual = _sha256(doc)
        assert actual == _normalize_digest(expected), doc


def test_documentation_closure_receipt_hashes_generated_sources() -> None:
    receipt = _receipt()
    source_hashes = receipt["generated_source_sha256"]

    for path, expected in source_hashes.items():
        actual = _sha256(path)
        assert actual == _normalize_digest(expected), path


def test_documentation_closure_receipt_id_is_content_addressed() -> None:
    receipt = _receipt()

    assert receipt["receipt_id"] == _receipt_id(receipt)


def test_documentation_checks_all_passed() -> None:
    receipt = _receipt()
    checks = {item["check_id"]: item for item in receipt["checks"]}

    for check_id in (
        "solo_docs_check",
        "system_docs_check",
        "markdown_structure",
        "link_check",
        "public_boundary",
        "secret_scan",
    ):
        assert checks[check_id]["status"] == "PASS"
        assert checks[check_id]["exit_code"] == 0
