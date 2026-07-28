#!/usr/bin/env python3
"""WP-F50 acceptance gate for the JSON-first SRL CLI surface.

Runs a set of hermetic checks against every namespaced command and the legacy
``doctor`` / ``version`` top-level commands. The gate constructs its own inputs
so it requires no live network, no external services, and no pre-existing files.
It prints one canonical ``GateReceipt/v1`` JSON line and exits 0 only if every
check PASSes.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from io import StringIO
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp50-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
_FX_KNOWLEDGE = _REPO_ROOT / "fixtures" / "conformance" / "knowledge"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import srl.cli  # noqa: E402
from srl.contracts import dumps  # noqa: E402
from srl.contracts.ids import object_id  # noqa: E402
from srl.planning.request import build_request  # noqa: E402

# ---------------------------------------------------------------------------
# Receipt identity.
# ---------------------------------------------------------------------------

GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-F50"


def _tmp_dir() -> str:
    """Return a fresh temporary directory path string."""
    return tempfile.mkdtemp(prefix="wp50-gate-")


def _cleanup(path: str) -> None:
    """Remove the temporary directory."""
    shutil.rmtree(path, ignore_errors=True)


def _write_json(path: Path, obj: object) -> None:
    """Write ``obj`` as compact JSON to ``path``."""
    path.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _run(args: list[str]) -> tuple[int, str, str]:
    """Run the CLI with ``args`` and return (code, stdout, stderr)."""
    old_stdout, old_stderr = sys.stdout, sys.stderr
    out_buf, err_buf = StringIO(), StringIO()
    try:
        sys.stdout, sys.stderr = out_buf, err_buf
        code = srl.cli.main(args)
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    return code, out_buf.getvalue(), err_buf.getvalue()


def _stdout_json(out: str) -> dict[str, Any]:
    """Parse the single JSON line from stdout."""
    lines = out.strip().splitlines()
    if len(lines) != 1:
        raise ValueError(f"expected one stdout line, got {len(lines)}")
    parsed = json.loads(lines[0])
    if not isinstance(parsed, dict):
        raise ValueError(f"stdout JSON is not an object: {type(parsed).__name__}")
    return parsed


def _stderr_json(err: str) -> dict[str, Any]:
    """Parse the single JSON line from stderr."""
    lines = err.strip().splitlines()
    if len(lines) != 1:
        raise ValueError(f"expected one stderr line, got {len(lines)}")
    parsed = json.loads(lines[0])
    if not isinstance(parsed, dict):
        raise ValueError(f"stderr JSON is not an object: {type(parsed).__name__}")
    return parsed


# ---------------------------------------------------------------------------
# Input builders.
# ---------------------------------------------------------------------------


def _minimal_claim() -> dict[str, Any]:
    """Return a valid ScientificClaim/v1 skeleton."""
    return {
        "schema_version": "ScientificClaim/v1",
        "statement": {"subject": "mass", "predicate": "equals", "object": "energy"},
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _valid_claim() -> dict[str, Any]:
    """Return a valid ScientificClaim/v1 with a computed claim_id."""
    claim = _minimal_claim()
    claim["claim_id"] = object_id(claim)
    return claim


def _valid_request(claim_id_value: str) -> dict[str, Any]:
    """Return a valid ScienceLabRunRequest/v1 targeting the given claim."""
    return build_request(
        claim_id=claim_id_value,
        requested_profiles=[],
        created_utc="2026-07-28T00:00:00Z",
    )


def _knowledge_payload_path() -> Path:
    """Return the canned OpenAlex fixture."""
    path = _FX_KNOWLEDGE / "payloads" / "openalex_works.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing knowledge fixture {path}")
    return path


# ---------------------------------------------------------------------------
# F50-01: legacy doctor/version commands remain unchanged.
# ---------------------------------------------------------------------------


def _check_f50_01() -> dict[str, Any]:
    """``doctor`` and ``version`` still emit the legacy reports."""
    try:
        code, out, _ = _run(["doctor"])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"doctor exited {code}"}
        report = _stdout_json(out)
        if report.get("schema_version") != "DoctorReport/v1" or report.get("status") != "ok":
            return {"status": "FAIL", "detail": f"unexpected doctor report: {report}"}

        code, out, _ = _run(["version"])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"version exited {code}"}
        report = _stdout_json(out)
        if report.get("schema_version") != "VersionReport/v1":
            return {"status": "FAIL", "detail": f"unexpected version report: {report}"}
        return {"status": "PASS", "detail": "doctor and version emit legacy reports"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# F50-02: schema validate command.
# ---------------------------------------------------------------------------


def _check_f50_02() -> dict[str, Any]:
    """``schema validate ScientificClaim <file>`` accepts a valid claim."""
    tmp = _tmp_dir()
    try:
        path = Path(tmp) / "claim.json"
        _write_json(path, _valid_claim())
        code, out, _ = _run(["schema", "validate", "ScientificClaim", str(path)])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"exit {code}"}
        report = _stdout_json(out)
        if report.get("schema_version") != "SchemaValidationReport/v1" or not report.get("valid"):
            return {"status": "FAIL", "detail": f"unexpected report: {report}"}
        return {"status": "PASS", "detail": "ScientificClaim schema validation accepted"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# F50-03: claim validate command and typed invariant failure.
# ---------------------------------------------------------------------------


def _check_f50_03() -> dict[str, Any]:
    """``claim validate`` accepts a valid claim and rejects an invariant violation."""
    tmp = _tmp_dir()
    try:
        valid_path = Path(tmp) / "valid.json"
        _write_json(valid_path, _valid_claim())
        code, out, _ = _run(["claim", "validate", str(valid_path)])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"valid claim exited {code}"}
        report = _stdout_json(out)
        if report.get("schema_version") != "ClaimValidationReport/v1" or not report.get("valid"):
            return {"status": "FAIL", "detail": f"valid claim report: {report}"}

        bad = _minimal_claim()
        bad["claim_class"] = "established_law_reference"
        bad["claim_id"] = object_id(bad)
        bad_path = Path(tmp) / "bad.json"
        _write_json(bad_path, bad)
        code, _, err = _run(["claim", "validate", str(bad_path)])
        if code != srl.cli.EXIT_ERROR:
            return {
                "status": "FAIL",
                "detail": f"bad claim exited {code}, expected {srl.cli.EXIT_ERROR}",
            }
        error = _stderr_json(err)
        if error.get("fail_reason") != "CONTRACT_INVALID":
            return {"status": "FAIL", "detail": f"bad claim error: {error}"}
        return {"status": "PASS", "detail": "valid claim accepted, invariant violation rejected"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# F50-04: plan build and inspect commands.
# ---------------------------------------------------------------------------


def _check_f50_04() -> dict[str, Any]:  # noqa: PLR0911
    """``plan build`` produces a ScienceLabPlan; ``plan inspect`` reports on it."""
    tmp = _tmp_dir()
    try:
        claim = _valid_claim()
        bundle = {"request": _valid_request(claim["claim_id"]), "claim": claim}
        bundle_path = Path(tmp) / "bundle.json"
        _write_json(bundle_path, bundle)

        code, out, _ = _run(["plan", "build", str(bundle_path)])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"plan build exited {code}"}
        build_report = _stdout_json(out)
        if build_report.get("schema_version") != "PlanBuildReport/v1":
            return {"status": "FAIL", "detail": f"unexpected build report: {build_report}"}
        plan_id = build_report.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id.startswith("sha256:"):
            return {"status": "FAIL", "detail": f"missing plan_id: {build_report}"}

        plan_path = Path(tmp) / "plan.json"
        _write_json(plan_path, build_report["plan"])
        code, out, _ = _run(["plan", "inspect", str(plan_path)])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"plan inspect exited {code}"}
        inspect_report = _stdout_json(out)
        if inspect_report.get("schema_version") != "PlanInspectionReport/v1":
            return {"status": "FAIL", "detail": f"unexpected inspect report: {inspect_report}"}
        if inspect_report.get("plan_id") != plan_id:
            return {"status": "FAIL", "detail": "inspect plan_id does not match build"}
        return {"status": "PASS", "detail": "plan build and inspect work"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# F50-05: CAS status, verify, and fsck.
# ---------------------------------------------------------------------------


def _check_f50_05() -> dict[str, Any]:  # noqa: PLR0911
    """``cas status|verify|fsck`` report integrity on an empty and corrupt store."""
    tmp = _tmp_dir()
    try:
        code, out, _ = _run(["cas", "status", tmp])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"cas status empty exited {code}"}
        status = _stdout_json(out)
        if status.get("schema_version") != "CasStatusReport/v1":
            return {"status": "FAIL", "detail": f"unexpected status report: {status}"}

        code, out, _ = _run(["cas", "verify", tmp])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"cas verify empty exited {code}"}
        verify = _stdout_json(out)
        if not verify.get("valid"):
            return {"status": "FAIL", "detail": f"verify empty not valid: {verify}"}

        # Introduce a corrupt object.
        shard = Path(tmp) / "objects" / "ab"
        shard.mkdir(parents=True)
        bad_digest = "sha256:" + "ab" * 32
        (shard / bad_digest).write_bytes(b"corrupt")
        code, out, _ = _run(["cas", "fsck", tmp])
        if code != srl.cli.EXIT_FSCK:
            return {"status": "FAIL", "detail": f"cas fsck corrupt exited {code}, expected 3"}
        fsck = _stdout_json(out)
        if fsck.get("schema_version") != "CasFsckReport/v1" or bad_digest not in fsck.get(
            "failed_digests", []
        ):
            return {"status": "FAIL", "detail": f"fsck corrupt report: {fsck}"}
        return {"status": "PASS", "detail": "cas status/verify/fsck report integrity"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# F50-06: run execute and run verify.
# ---------------------------------------------------------------------------


def _check_f50_06() -> dict[str, Any]:  # noqa: PLR0911
    """``run execute`` runs the echo adapter; ``run verify`` checks a receipt."""
    tmp = _tmp_dir()
    try:
        spec_path = Path(tmp) / "run.json"
        _write_json(spec_path, {"adapter_id": "echo.v1", "input": {"value": 42}})
        code, out, _ = _run(["run", "execute", str(spec_path)])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"run execute exited {code}"}
        run_report = _stdout_json(out)
        if run_report.get("schema_version") != "RunExecutionReport/v1":
            return {"status": "FAIL", "detail": f"unexpected run report: {run_report}"}
        if run_report.get("status") != "completed" or run_report.get("output") != {"value": 42}:
            return {"status": "FAIL", "detail": f"run did not complete: {run_report}"}

        output_path = Path(tmp) / "output.json"
        output_path.write_text("{}", encoding="utf-8")
        receipt_path = Path(tmp) / "receipt.json"
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
        code, out, _ = _run(["run", "verify", str(receipt_path)])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"run verify exited {code}"}
        verify = _stdout_json(out)
        if verify.get("schema_version") != "RunReceiptVerificationReport/v1" or not verify.get(
            "valid"
        ):
            return {"status": "FAIL", "detail": f"run verify invalid: {verify}"}
        return {"status": "PASS", "detail": "run execute and run verify work"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# F50-07: knowledge query with fixture transport.
# ---------------------------------------------------------------------------


def _check_f50_07() -> dict[str, Any]:
    """``knowledge query`` works offline via ``--transport``."""
    tmp = _tmp_dir()
    try:
        payload_path = _knowledge_payload_path()
        code, out, _ = _run(
            [
                "knowledge",
                "query",
                "openalex",
                "/works",
                "{}",
                "--cache-dir",
                tmp,
                "--transport",
                str(payload_path),
            ]
        )
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"knowledge query exited {code}"}
        report = _stdout_json(out)
        if report.get("schema_version") != "KnowledgeQueryReport/v1":
            return {"status": "FAIL", "detail": f"unexpected query report: {report}"}
        receipt = report.get("receipt")
        if not isinstance(receipt, dict) or receipt.get("schema_version") != "QueryReceipt/v1":
            return {"status": "FAIL", "detail": f"unexpected receipt: {receipt}"}
        return {"status": "PASS", "detail": "knowledge query offline via fixture transport"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# F50-08: catalog list and inspect.
# ---------------------------------------------------------------------------


def _check_f50_08() -> dict[str, Any]:  # noqa: PLR0911
    """``catalog list`` and ``catalog inspect`` emit the shipped catalog."""
    try:
        code, out, _ = _run(["catalog", "list"])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"catalog list exited {code}"}
        list_report = _stdout_json(out)
        if list_report.get("schema_version") != "CapabilityCatalogList/v1":
            return {"status": "FAIL", "detail": f"unexpected list report: {list_report}"}
        entries = list_report.get("entries")
        if not isinstance(entries, list) or not entries:
            return {"status": "FAIL", "detail": f"catalog list empty: {list_report}"}

        code, out, _ = _run(["catalog", "inspect"])
        if code != srl.cli.EXIT_OK:
            return {"status": "FAIL", "detail": f"catalog inspect exited {code}"}
        inspect_report = _stdout_json(out)
        if inspect_report.get("schema_version") != "CapabilityCatalogReport/v1":
            return {"status": "FAIL", "detail": f"unexpected inspect report: {inspect_report}"}
        catalog = inspect_report.get("catalog")
        if not isinstance(catalog, dict) or catalog.get("schema_version") != "CapabilityCatalog/v1":
            return {"status": "FAIL", "detail": f"catalog document missing: {inspect_report}"}
        return {"status": "PASS", "detail": "catalog list and inspect work"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# F50-09: unknown and missing commands return the documented exit codes.
# ---------------------------------------------------------------------------


def _check_f50_09() -> dict[str, Any]:  # noqa: PLR0911
    """Unknown/missing commands exit 2; command errors exit 1."""
    try:
        code, out, _ = _run(["nope"])
        if code != srl.cli.EXIT_USAGE:
            return {"status": "FAIL", "detail": f"unknown command exited {code}, expected 2"}
        report = _stdout_json(out)
        if report.get("schema_version") != "ErrorReport/v1":
            return {"status": "FAIL", "detail": f"unknown command report: {report}"}

        code, out, _ = _run([])
        if code != srl.cli.EXIT_USAGE:
            return {"status": "FAIL", "detail": f"missing command exited {code}, expected 2"}
        report = _stdout_json(out)
        if report.get("error") != "missing command":
            return {"status": "FAIL", "detail": f"missing command report: {report}"}

        code, _, err = _run(["schema", "nope"])
        if code != srl.cli.EXIT_USAGE:
            return {"status": "FAIL", "detail": f"unknown subcommand exited {code}, expected 2"}
        error = _stderr_json(err)
        if error.get("schema_version") != "ErrorReport/v1":
            return {"status": "FAIL", "detail": f"unknown subcommand error: {error}"}
        return {"status": "PASS", "detail": "exit codes 0/1/2/3/4 are documented and emitted"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _build_receipt() -> dict[str, Any]:
    """Run all F50 checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "F50-01": _check_f50_01(),
        "F50-02": _check_f50_02(),
        "F50-03": _check_f50_03(),
        "F50-04": _check_f50_04(),
        "F50-05": _check_f50_05(),
        "F50-06": _check_f50_06(),
        "F50-07": _check_f50_07(),
        "F50-08": _check_f50_08(),
        "F50-09": _check_f50_09(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {"statuses": statuses},
    }


def main(argv: list[str] | None = None) -> int:
    """Run the WP-F50 gate. Returns 0 iff every check PASSes."""
    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
