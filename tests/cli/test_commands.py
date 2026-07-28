"""Hermetic tests for the WP-F50 JSON-first CLI surface.

These tests exercise every namespaced command and several typed error paths by
calling :func:`srl.cli.main` directly with temporary files. No test makes a live
network call; the ``knowledge query`` path uses the ``--transport`` fixture file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.cli import EXIT_ERROR, EXIT_FSCK, EXIT_OK, EXIT_POLICY, EXIT_USAGE, main
from srl.contracts.ids import object_id
from srl.execution.runner import RunOutcome, RunStatus, RunUsage
from srl.planning.request import build_request
from srl.semantic.claims import claim_id


def _write_json(path: Path, obj: object) -> None:
    """Write ``obj`` as compact JSON to ``path``."""
    path.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _parse_stdout(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """Parse the single JSON line written to stdout."""
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) == 1, f"expected one JSON line on stdout, got {lines!r}"
    report = json.loads(lines[0])
    assert isinstance(report, dict)
    return report


def _parse_stderr(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """Parse the single JSON line written to stderr."""
    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    assert len(lines) == 1, f"expected one JSON line on stderr, got {lines!r}"
    report = json.loads(lines[0])
    assert isinstance(report, dict)
    return report


def _minimal_claim() -> dict[str, Any]:
    """Return a valid ScientificClaim/v1 without a claim_id (added by caller)."""
    return {
        "schema_version": "ScientificClaim/v1",
        "statement": {"subject": "foo", "predicate": "is", "object": "bar"},
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _valid_claim(tmp_path: Path) -> Path:
    """Write a valid claim file and return its path."""
    claim = _minimal_claim()
    claim["claim_id"] = claim_id(claim)
    path = tmp_path / "claim.json"
    _write_json(path, claim)
    return path


def _valid_request(claim: dict[str, Any]) -> dict[str, Any]:
    """Build a valid ScienceLabRunRequest/v1 targeting ``claim``."""
    return build_request(
        claim_id=claim["claim_id"],
        requested_profiles=[],
        created_utc="2026-07-28T00:00:00Z",
    )


def _valid_plan_bundle(tmp_path: Path) -> Path:
    """Write a plan-build bundle file and return its path."""
    claim = _minimal_claim()
    claim["claim_id"] = claim_id(claim)
    request = _valid_request(claim)
    path = tmp_path / "bundle.json"
    _write_json(path, {"request": request, "claim": claim})
    return path


def _knowledge_payload_path() -> Path:
    """Return the canned OpenAlex fixture used by the hermetic knowledge tests."""
    here = Path(__file__).resolve().parents[2]
    path = here / "fixtures" / "conformance" / "knowledge" / "payloads" / "openalex_works.json"
    assert path.is_file(), f"missing knowledge fixture {path}"
    return path


# ---------------------------------------------------------------------------
# Schema validation.
# ---------------------------------------------------------------------------


def test_schema_validate_valid_claim(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``schema validate ScientificClaim <file>`` emits a valid report."""
    path = _valid_claim(tmp_path)
    code = main(["schema", "validate", "ScientificClaim", str(path)])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "SchemaValidationReport/v1"
    assert report["schema_name"] == "ScientificClaim"
    assert report["file"] == str(path)
    assert report["valid"] is True


def test_schema_validate_unknown_schema(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """An unknown schema name emits a typed error on stderr."""
    path = _valid_claim(tmp_path)
    code = main(["schema", "validate", "NoSuchSchema", str(path)])
    assert code == EXIT_ERROR
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "CONTRACT_INVALID"
    assert "NoSuchSchema" in report["error"]


def test_schema_validate_malformed_json(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """A non-JSON file emits a typed error on stderr."""
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    code = main(["schema", "validate", "ScientificClaim", str(path)])
    assert code == EXIT_ERROR
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert "not valid JSON" in report["error"]


# ---------------------------------------------------------------------------
# Claim validation.
# ---------------------------------------------------------------------------


def test_claim_validate_valid(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``claim validate <file>`` accepts a valid claim."""
    path = _valid_claim(tmp_path)
    code = main(["claim", "validate", str(path)])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "ClaimValidationReport/v1"
    assert report["valid"] is True
    assert report["claim_class"] == "candidate_hypothesis"


def test_claim_validate_invariant_violation(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """An established-law claim without literature support is rejected."""
    claim = _minimal_claim()
    claim["claim_class"] = "established_law_reference"
    claim["claim_id"] = object_id(claim)
    path = tmp_path / "bad-claim.json"
    _write_json(path, claim)
    code = main(["claim", "validate", str(path)])
    assert code == EXIT_ERROR
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "CONTRACT_INVALID"
    assert "literature" in report["error"]


def test_claim_validate_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    """A missing claim file emits a typed error."""
    code = main(["claim", "validate", "/no/such/file.json"])
    assert code == EXIT_ERROR
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "CONTRACT_INVALID"


# ---------------------------------------------------------------------------
# Plan build / inspect.
# ---------------------------------------------------------------------------


def test_plan_build(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``plan build <bundle>`` produces a deterministic plan report."""
    bundle = _valid_plan_bundle(tmp_path)
    code = main(["plan", "build", str(bundle)])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "PlanBuildReport/v1"
    assert report["file"] == str(bundle)
    assert report["plan_id"].startswith("sha256:")
    assert report["plan_digest"].startswith("sha256:")
    assert isinstance(report["steps"], int) and report["steps"] > 0
    assert report["plan"]["schema_version"] == "ScienceLabPlan/v1"


def test_plan_build_missing_request(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """A bundle without a request object is rejected."""
    path = tmp_path / "bundle.json"
    _write_json(path, {"claim": _minimal_claim()})
    code = main(["plan", "build", str(path)])
    assert code == EXIT_ERROR
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "CONTRACT_INVALID"
    assert "request" in report["error"].lower()


def test_plan_inspect(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``plan inspect <file>`` reports step counts for a valid plan."""
    bundle = _valid_plan_bundle(tmp_path)
    main(["plan", "build", str(bundle)])
    built = json.loads(capsys.readouterr().out.splitlines()[0])
    plan_path = tmp_path / "plan.json"
    _write_json(plan_path, built["plan"])

    code = main(["plan", "inspect", str(plan_path)])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "PlanInspectionReport/v1"
    assert report["plan_id"] == built["plan_id"]
    assert report["step_count"] == built["steps"]


def test_plan_inspect_bad_plan(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """An invalid plan emits a typed error on stderr."""
    path = tmp_path / "bad-plan.json"
    _write_json(path, {"schema_version": "ScienceLabPlan/v1"})
    code = main(["plan", "inspect", str(path)])
    assert code == EXIT_ERROR
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "CONTRACT_INVALID"


# ---------------------------------------------------------------------------
# CAS.
# ---------------------------------------------------------------------------


def test_cas_status_empty_store(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``cas status <root>`` reports an empty store."""
    code = main(["cas", "status", str(tmp_path)])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "CasStatusReport/v1"
    assert report["objects_checked"] == 0
    assert report["failed_count"] == 0


def test_cas_verify_empty_store(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``cas verify`` on an empty store is valid."""
    code = main(["cas", "verify", str(tmp_path)])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "CasVerifyReport/v1"
    assert report["valid"] is True


def test_cas_fsck_corruption(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``cas fsck`` exits 3 when an object's bytes do not match its digest."""
    objects_dir = tmp_path / "objects" / "ab"
    objects_dir.mkdir(parents=True)
    bad_digest = "sha256:" + "ab" * 32
    (objects_dir / bad_digest).write_bytes(b"wrong bytes")

    code = main(["cas", "fsck", str(tmp_path)])
    assert code == EXIT_FSCK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "CasFsckReport/v1"
    assert report["objects_checked"] == 1
    assert report["objects_passed"] == 0
    assert bad_digest in report["failed_digests"]


# ---------------------------------------------------------------------------
# Run execution / verification.
# ---------------------------------------------------------------------------


def test_run_execute_echo(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``run execute`` runs the echo adapter and emits a completion report."""
    spec_path = tmp_path / "run.json"
    _write_json(spec_path, {"adapter_id": "echo.v1", "input": {"value": 42}})
    code = main(["run", "execute", str(spec_path)])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "RunExecutionReport/v1"
    assert report["adapter_id"] == "echo.v1"
    assert report["status"] == "completed"
    assert report["receipt_written"] is True
    assert report["output"] == {"value": 42}
    assert set(report["usage"]) >= {"wall_seconds", "rss_bytes", "output_bytes"}


def test_run_execute_unknown_adapter(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """An unknown adapter is a contract failure, not a policy violation."""
    spec_path = tmp_path / "run.json"
    _write_json(spec_path, {"adapter_id": "unknown.adapter", "input": {}})
    code = main(["run", "execute", str(spec_path)])
    assert code == EXIT_ERROR
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "CONTRACT_INVALID"
    assert "unknown adapter" in report["error"].lower()


def test_run_execute_policy_violation(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner policy-violation outcome exits 4 with the orphan fail reason."""
    spec_path = tmp_path / "run.json"
    _write_json(spec_path, {"adapter_id": "echo.v1", "input": {"value": 1}})

    def _fake_run_adapter(**_kwargs: object) -> RunOutcome:
        return RunOutcome(
            adapter_id="echo.v1",
            status=RunStatus.POLICY_VIOLATION,
            output=None,
            usage=RunUsage(wall_seconds=0.0, rss_bytes=0, output_bytes=0),
            receipt_written=False,
            fail_reason="ORPHAN_SURVIVOR",
            detail="orphan survived",
        )

    monkeypatch.setattr("srl.cli.run_adapter", _fake_run_adapter)
    code = main(["run", "execute", str(spec_path)])
    assert code == EXIT_POLICY
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "ORPHAN_PROCESS_DETECTED"
    assert report["error"] == "orphan survived"

    """``run verify`` succeeds when the receipt's output file exists."""
    output_path = tmp_path / "output.json"
    output_path.write_text("{}", encoding="utf-8")
    receipt_path = tmp_path / "receipt.json"
    _write_json(
        receipt_path,
        {
            "schema_version": "RunReceipt/v1",
            "adapter_id": "echo.v1",
            "status": "completed",
            "usage": {"wall_seconds": 0.1, "rss_bytes": 0, "output_bytes": 2},
            "output_path": str(output_path),
        },
    )
    code = main(["run", "verify", str(receipt_path)])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "RunReceiptVerificationReport/v1"
    assert report["output_exists"] is True
    assert report["valid"] is True


def test_run_verify_missing_output(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``run verify`` reports invalid when the output file is absent."""
    receipt_path = tmp_path / "receipt.json"
    _write_json(
        receipt_path,
        {
            "schema_version": "RunReceipt/v1",
            "adapter_id": "echo.v1",
            "status": "completed",
            "usage": {"wall_seconds": 0.1, "rss_bytes": 0, "output_bytes": 2},
            "output_path": "/no/such/output.json",
        },
    )
    code = main(["run", "verify", str(receipt_path)])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["valid"] is False


# ---------------------------------------------------------------------------
# Knowledge query.
# ---------------------------------------------------------------------------


def test_knowledge_query_fixture_transport(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``knowledge query`` with ``--transport`` succeeds without network."""
    payload_path = _knowledge_payload_path()
    cache_dir = tmp_path / "cache"
    code = main(
        [
            "knowledge",
            "query",
            "openalex",
            "/works",
            "{}",
            "--cache-dir",
            str(cache_dir),
            "--transport",
            str(payload_path),
        ]
    )
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "KnowledgeQueryReport/v1"
    assert report["endpoint_id"] == "openalex"
    assert report["status"] == "COMPLETED"
    assert report["receipt"]["schema_version"] == "QueryReceipt/v1"
    assert report["receipt"]["endpoint_id"] == "openalex"


def test_knowledge_query_missing_cache_dir(capsys: pytest.CaptureFixture[str]) -> None:
    """``knowledge query`` without ``--cache-dir`` emits a typed error."""
    code = main(["knowledge", "query", "openalex", "/works"])
    assert code == EXIT_ERROR
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "CONTRACT_INVALID"
    assert "cache-dir" in report["error"].lower()


def test_knowledge_query_offline_wait_environment(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A non-network transport failure surfaces as ``WAIT_ENVIRONMENT``."""
    payload_path = _knowledge_payload_path()
    # ``cache_dir`` is a file, so the retriever cannot create the cache
    # directory and the fetch raises a generic OSError. The CLI maps any
    # untyped transport exception to a ``WAIT_ENVIRONMENT`` receipt.
    cache_file = tmp_path / "cache-as-file"
    cache_file.write_text("not a directory", encoding="utf-8")
    code = main(
        [
            "knowledge",
            "query",
            "openalex",
            "/works",
            "{}",
            "--cache-dir",
            str(cache_file),
            "--transport",
            str(payload_path),
        ]
    )
    assert code == EXIT_ERROR
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "WAIT_ENVIRONMENT"
    assert report["status"] == "WAIT_ENVIRONMENT"


# ---------------------------------------------------------------------------
# Catalog.
# ---------------------------------------------------------------------------


def test_catalog_list(capsys: pytest.CaptureFixture[str]) -> None:
    """``catalog list`` emits the shipped capability catalog entries."""
    code = main(["catalog", "list"])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "CapabilityCatalogList/v1"
    assert report["catalog_digest"].startswith("sha256:")
    entries = report["entries"]
    assert isinstance(entries, list) and entries
    for entry in entries:
        assert set(entry) >= {"profile", "capability_id", "availability"}


def test_catalog_inspect(capsys: pytest.CaptureFixture[str]) -> None:
    """``catalog inspect`` emits the full catalog document."""
    code = main(["catalog", "inspect"])
    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "CapabilityCatalogReport/v1"
    assert report["catalog"]["schema_version"] == "CapabilityCatalog/v1"
    assert isinstance(report["catalog"]["capabilities"], list)


# ---------------------------------------------------------------------------
# Unknown / missing commands.
# ---------------------------------------------------------------------------


def test_unknown_top_level_command(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown top-level command exits 2 and writes JSON to stdout."""
    code = main(["nope"])
    assert code == EXIT_USAGE
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["error"] == "unknown command"


def test_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown subcommand exits 2 and writes JSON to stderr."""
    code = main(["schema", "nope"])
    assert code == EXIT_USAGE
    report = _parse_stderr(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert "unknown schema subcommand" in report["error"].lower()


def test_missing_command(capsys: pytest.CaptureFixture[str]) -> None:
    """No command at all exits 2 and writes JSON to stdout."""
    code = main([])
    assert code == EXIT_USAGE
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["error"] == "missing command"
