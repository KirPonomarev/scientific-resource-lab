from __future__ import annotations

import hashlib
import json
import os
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
RECEIPT_PATH = Path("docs/verification/documentation-closure-receipt-v2.json")
HISTORICAL_RECEIPT_PATH = Path("docs/verification/documentation-closure-receipt.json")
SYSTEM_RECEIPT_PATH = Path("docs/verification/system-acceptance-receipt.json")
INDEPENDENT_REVIEW_RECEIPT_PATH = Path(
    "docs/verification/federation-doctrine-independent-review-v1.json"
)
EXPECTED_CANDIDATE_BASE_HEAD = "7adf5cd2c2d4af888c27126e01094981f821c98a"


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_object_without_duplicate_keys,
    )
    assert isinstance(value, dict)
    return value


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _receipt() -> dict[str, Any]:
    return _load_json(RECEIPT_PATH)


def _system_receipt() -> dict[str, Any]:
    return _load_json(SYSTEM_RECEIPT_PATH)


def _normalize_digest(value: str) -> str:
    return value.removeprefix("sha256:").replace("-", "")


def _sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _receipt_id(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_id"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, 64, 8))


def _candidate_diff_sha256() -> str:
    environment = {
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
    top_level = subprocess.run(
        ["/usr/bin/git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert top_level.returncode == 0
    assert Path(top_level.stdout.strip()).resolve() == Path.cwd().resolve()
    ancestor = subprocess.run(  # noqa: S603
        [
            "/usr/bin/git",
            "merge-base",
            "--is-ancestor",
            EXPECTED_CANDIDATE_BASE_HEAD,
            "HEAD",
        ],
        capture_output=True,
        check=False,
        env=environment,
    )
    assert ancestor.returncode == 0
    exclusions = (
        f":(top,exclude,literal){RECEIPT_PATH}",
        f":(top,exclude,literal){INDEPENDENT_REVIEW_RECEIPT_PATH}",
    )
    process = subprocess.run(  # noqa: S603
        [
            "/usr/bin/git",
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-renames",
            "--no-textconv",
            EXPECTED_CANDIDATE_BASE_HEAD,
            "--",
            ".",
            *exclusions,
        ],
        capture_output=True,
        check=False,
        env=environment,
    )
    assert process.returncode == 0
    assert process.stdout
    return hashlib.sha256(process.stdout).hexdigest()


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

    historical = _load_json(HISTORICAL_RECEIPT_PATH)
    assert receipt["schema_version"] == "DocumentationClosureReceipt/v2"
    assert receipt["work_package"] == "GOV-FED-01"
    assert receipt["supersedes_receipt_id"] == historical["receipt_id"]
    assert receipt["historical_receipt_unchanged"] is True
    assert receipt["runtime_truth"] is False
    assert receipt["activates_federation"] is False
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


def test_documentation_closure_receipt_binds_exact_base_to_index_candidate() -> None:
    receipt = _receipt()
    candidate = _candidate_diff_sha256()

    assert receipt["source_head"] == EXPECTED_CANDIDATE_BASE_HEAD
    assert receipt["source_head_role"] == "base_head_for_frozen_staged_candidate"
    assert _normalize_digest(receipt["staged_candidate_diff_sha256"]) == candidate
    assert candidate != hashlib.sha256(b"").hexdigest()


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
