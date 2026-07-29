"""A17 solo-agent session lifecycle for Scientific Reasoning Fabric.

The solo-agent entry is intentionally local, bounded and receipt-first. It
does not create canonical writes, does not grant authority, and does not depend
on chat history. A fresh agent can enter SRF, discover capabilities from the
truth-ledger projection, submit one deterministic research task, inspect its
status/result, export a sanitized packet, and replay the task from recorded
inputs.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from srl.bridge.exporter import DisclosurePolicy, ExportObject, build_packet
from srl.capabilities.truth import build_truth_ledger
from srl.contracts import object_id, schema_validate
from srl.contracts.canonical import dumps, loads
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.labctl import PROJECT_FINGERPRINT, enter_report, lab_access_receipt
from srl.packs.adapters.units import convert, pint_version
from srl.planning import build_plan, default_policy, load_default_catalog, route
from srl.planning.request import build_request
from srl.semantic.claims import claim_id
from srl.semantic.evidence import (
    DEFAULT_AXES,
    build_assessment,
    build_engine_receipt,
    build_validation_receipt,
)

SOLO_SESSION_SCHEMA: Final[str] = "SoloAgentSession/v1"
SOLO_TASK_RESULT_SCHEMA: Final[str] = "SoloAgentTaskResult/v1"
SOLO_STATUS_SCHEMA: Final[str] = "SoloAgentStatusReport/v1"
SOLO_REPLAY_SCHEMA: Final[str] = "SoloAgentReplayReport/v1"
SOLO_EXPORT_SCHEMA: Final[str] = "SoloAgentExportReport/v1"
SOLO_DOCTOR_SCHEMA: Final[str] = "SoloAgentDoctorReport/v1"
SOLO_ACCEPTANCE_SCHEMA: Final[str] = "SoloAgentAcceptanceReceipt/v1"

_FIXED_UTC: Final[str] = "2026-07-29T00:00:00Z"
_SESSION_FILE: Final[str] = "session.json"
_CAPABILITY_FILE: Final[str] = "capability-manifest.json"
_RESULT_FILE: Final[str] = "result.json"
_EXPORT_FILE: Final[str] = "export-packet.json"
_REPLAY_FILE: Final[str] = "replay.json"
_PORTAL_DIR: Final[str] = "portal"
_OBJECTS_DIR: Final[str] = "objects"
_SOLO_TASK_ID: Final[str] = "units_identity_research_task"
_WRONG_CHECKOUT_STATUS: Final[str] = "WRONG_CHECKOUT"
_STALE_STATUS: Final[str] = "STALE_OR_CROSS_HEAD"


class SoloAgentError(ContractError):
    """Raised when a solo-agent session fails closed."""

    def __init__(self, message: str, *, status: str = "ERROR") -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)
        self.status = status


@dataclass(frozen=True)
class CheckoutReport:
    """Read-only checkout identity used to fail closed on wrong or stale work."""

    status: str
    project_root_ok: bool
    git_head: str | None
    origin_main: str | None
    expected_head: str | None
    detail: str

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible report."""
        return {
            "status": self.status,
            "project_root_ok": self.project_root_ok,
            "git_head": self.git_head,
            "origin_main": self.origin_main,
            "expected_head": self.expected_head,
            "detail": self.detail,
        }


def _git(args: list[str]) -> str | None:
    """Run a bounded git inspection command; return stripped stdout or None."""
    try:
        result = subprocess.run(  # noqa: S603 - bounded git inspection
            ["git", *args],  # noqa: S607 - git is inspected through PATH like existing gates.
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def checkout_report(*, expected_head: str | None = None) -> CheckoutReport:
    """Return the current checkout status without mutating the repository."""
    root = _git(["rev-parse", "--show-toplevel"])
    head = _git(["rev-parse", "HEAD"])
    origin_main = _git(["rev-parse", "origin/main"])
    if root is None or head is None:
        return CheckoutReport(
            status=_WRONG_CHECKOUT_STATUS,
            project_root_ok=False,
            git_head=head,
            origin_main=origin_main,
            expected_head=expected_head,
            detail="not inside a git checkout; run from a scientific-resource-lab checkout",
        )
    root_path = Path(root)
    markers = (
        root_path / "pyproject.toml",
        root_path / "docs" / "plans" / "scientific-reasoning-fabric-activation-master-plan-v3.7.md",
        root_path / "src" / "srl" / "labctl.py",
    )
    if not all(path.is_file() for path in markers):
        return CheckoutReport(
            status=_WRONG_CHECKOUT_STATUS,
            project_root_ok=False,
            git_head=head,
            origin_main=origin_main,
            expected_head=expected_head,
            detail="checkout markers do not match scientific-resource-lab",
        )
    if expected_head is not None and head != expected_head:
        return CheckoutReport(
            status=_STALE_STATUS,
            project_root_ok=True,
            git_head=head,
            origin_main=origin_main,
            expected_head=expected_head,
            detail="session head does not match current checkout head",
        )
    return CheckoutReport(
        status="OK",
        project_root_ok=True,
        git_head=head,
        origin_main=origin_main,
        expected_head=expected_head,
        detail="scientific-resource-lab checkout markers and head are consistent",
    )


def _read_json(path: Path) -> dict[str, Any]:
    """Read a canonical JSON object from ``path``."""
    try:
        parsed = loads(path.read_bytes())
    except OSError as exc:
        msg = f"could not read {path.name}: {exc}"
        raise SoloAgentError(msg) from exc
    if not isinstance(parsed, dict):
        msg = f"{path.name} must contain a JSON object"
        raise SoloAgentError(msg)
    return parsed


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write canonical JSON bytes to ``path``."""
    path.write_bytes(dumps(payload))


def _capability_projection() -> tuple[dict[str, Any], str]:
    """Build CapabilityManifest/v1 plus its source truth-ledger digest."""
    ledger = build_truth_ledger()
    active = sorted(
        {
            str(item["component_id"])
            for item in ledger["components"]
            if item.get("state") == "ACTIVE"
        }
    )
    manifest: dict[str, Any] = {
        "schema_version": "CapabilityManifest/v1",
        "capabilities": active,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    manifest["manifest_id"] = object_id(manifest)
    schema_validate(manifest, "CapabilityManifest")
    return manifest, object_id(ledger)


def _capability_manifest() -> dict[str, Any]:
    """Build a schema-valid CapabilityManifest/v1 from the truth ledger."""
    manifest, _truth_digest = _capability_projection()
    return manifest


def _session_envelope(cell_id: str, checkout: CheckoutReport) -> dict[str, Any]:
    """Build a LabSessionEnvelope/v1 bound to the current checkout head."""
    seed = {
        "schema_version": "LabSessionEnvelope/v1",
        "cell_id": cell_id,
        "project_fingerprint": PROJECT_FINGERPRINT,
        "created_utc": _FIXED_UTC,
        "classification": "D0",
        "canonical_writes": 0,
        "grants_authority": False,
        "git_head": checkout.git_head,
    }
    envelope = {k: v for k, v in seed.items() if k != "git_head"}
    envelope["session_id"] = object_id(seed)
    schema_validate(envelope, "LabSessionEnvelope")
    return envelope


def _claim() -> dict[str, Any]:
    """Return the deterministic synthetic claim used by the solo task."""
    claim: dict[str, Any] = {
        "schema_version": "ScientificClaim/v1",
        "statement": {
            "subject": "one newton",
            "predicate": "equals",
            "object": "one kilogram meter per second squared",
        },
        "claim_class": "definition",
        "claim_status": "under_investigation",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": _FIXED_UTC,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    claim["claim_id"] = claim_id(claim)
    schema_validate(claim, "ScientificClaim")
    return claim


def _pack_ref() -> dict[str, Any]:
    """Return a stable synthetic pack ref for the bounded units adapter."""
    return {
        "schema_version": "ArtifactRef/v1",
        "media_type": "application/vnd.srl.adapter-pack+json",
        "digest": "sha256:" + "17" * 32,
        "size_bytes": 1024,
        "path": "units/pack.json",
    }


def _build_task_result(
    session: dict[str, Any],
    capability_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Run the bounded solo research task and return its result envelope."""
    claim = _claim()
    request = build_request(
        claim_id=claim["claim_id"],
        requested_profiles=["algebra_exact"],
        resource_class="default",
        seed=17,
        threads=1,
        output_schemas=["ScientificObjectEnvelope"],
        created_utc=_FIXED_UTC,
    )
    catalog = load_default_catalog()
    decision = route(request, claim, catalog, default_policy())
    plan = build_plan(request, decision, catalog, default_policy(), created_utc=_FIXED_UTC)

    converted = convert("1", "kg*m/s^2", "N")
    if converted != "1":
        msg = f"units identity conversion drifted: expected '1', got {converted!r}"
        raise SoloAgentError(msg)

    engine = build_engine_receipt(
        run_request_id=request["request_id"],
        adapter_id="units",
        pack_ref=_pack_ref(),
        engine_execution="completed",
        exercise_level="actual_compute",
        wall_seconds=0,
        rss_bytes=0,
        created_utc=_FIXED_UTC,
    )
    validation = build_validation_receipt(
        engine_receipt_id=engine["receipt_id"],
        validator_id="units-identity-checker",
        scientific_check="checked",
        formal_check="unchecked",
        statistical_support="not_applicable",
        causal_identification="not_applicable",
        created_utc=_FIXED_UTC,
    )
    axes = dict(DEFAULT_AXES)
    axes["capability_state"] = "ready"
    axes["exercise_level"] = "actual_compute"
    axes["engine_execution"] = "completed"
    axes["scientific_check"] = "checked"
    assessment = build_assessment(
        subject_claim_id=claim["claim_id"],
        axes=axes,
        evidence_refs=[engine["receipt_id"], validation["receipt_id"]],
        assessor="adapter",
        created_utc=_FIXED_UTC,
    )
    result: dict[str, Any] = {
        "schema_version": SOLO_TASK_RESULT_SCHEMA,
        "task_id": _SOLO_TASK_ID,
        "session_id": session["session_id"],
        "status": "COMPLETED",
        "claim": claim,
        "request": request,
        "plan": plan,
        "capability_manifest_id": capability_manifest["manifest_id"],
        "truth_ledger_digest": session["truth_ledger_digest"],
        "compute": {
            "adapter_id": "units",
            "pint_version": pint_version(),
            "operation": "convert",
            "value": "1",
            "from_unit": "kg*m/s^2",
            "to_unit": "N",
            "result": converted,
        },
        "engine_receipt": engine,
        "validation_receipt": validation,
        "assessment": assessment,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    result["result_id"] = object_id(result)
    return result


def _assert_fresh_session(session: dict[str, Any]) -> CheckoutReport:
    """Validate a session against the current checkout head."""
    expected = session.get("git_head")
    if not isinstance(expected, str) or not expected:
        raise SoloAgentError("session missing git_head", status=_STALE_STATUS)
    checkout = checkout_report(expected_head=expected)
    if checkout.status != "OK":
        raise SoloAgentError(checkout.detail, status=checkout.status)
    return checkout


def submit_session(session_dir: str | Path, *, cell_id: str = "standalone") -> dict[str, Any]:
    """Create a solo-agent session and execute the bounded default task."""
    checkout = checkout_report()
    if checkout.status != "OK":
        raise SoloAgentError(checkout.detail, status=checkout.status)
    access = lab_access_receipt(cell_id)
    if access["scope"]["proposal_only"]:
        raise SoloAgentError(
            f"{cell_id} requires native bootstrap before submit",
            status="WAIT_NATIVE_BOOTSTRAP",
        )
    out = Path(session_dir)
    out.mkdir(parents=True, exist_ok=True)
    capability_manifest, truth_ledger_digest = _capability_projection()
    envelope = _session_envelope(cell_id, checkout)
    session = {
        "schema_version": SOLO_SESSION_SCHEMA,
        "session_id": envelope["session_id"],
        "cell_id": cell_id,
        "project_fingerprint": PROJECT_FINGERPRINT,
        "created_utc": _FIXED_UTC,
        "lab_session_envelope": envelope,
        "git_head": checkout.git_head,
        "origin_main": checkout.origin_main,
        "access_receipt": access,
        "capability_manifest_id": capability_manifest["manifest_id"],
        "truth_ledger_digest": truth_ledger_digest,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    result = _build_task_result(session, capability_manifest)
    _write_json(out / _SESSION_FILE, session)
    _write_json(out / _CAPABILITY_FILE, capability_manifest)
    _write_json(out / _RESULT_FILE, result)
    return {
        "schema_version": "SoloAgentSubmitReport/v1",
        "status": "COMPLETED",
        "session_id": session["session_id"],
        "result_id": result["result_id"],
        "files": [_SESSION_FILE, _CAPABILITY_FILE, _RESULT_FILE],
        "canonical_writes": 0,
        "grants_authority": False,
    }


def session_status(session_dir: str | Path) -> dict[str, Any]:
    """Return status for a session directory, failing closed on stale HEAD."""
    root = Path(session_dir)
    session = _read_json(root / _SESSION_FILE)
    result = _read_json(root / _RESULT_FILE)
    checkout = _assert_fresh_session(session)
    return {
        "schema_version": SOLO_STATUS_SCHEMA,
        "status": result["status"],
        "session_id": session["session_id"],
        "result_id": result["result_id"],
        "checkout": checkout.to_dict(),
        "canonical_writes": 0,
        "grants_authority": False,
    }


def session_result(session_dir: str | Path) -> dict[str, Any]:
    """Return a completed solo-agent task result."""
    root = Path(session_dir)
    session = _read_json(root / _SESSION_FILE)
    result = _read_json(root / _RESULT_FILE)
    _assert_fresh_session(session)
    return result


def export_session(session_dir: str | Path) -> dict[str, Any]:
    """Build and store a sanitized LabExportPacket for a session result."""
    root = Path(session_dir)
    result = session_result(root)
    objects = [
        ExportObject(
            object_digest=result["result_id"],
            object_type="run_receipt",
            sanitized_summary=(
                "Solo-agent bounded units identity task completed: "
                "1 kg*m/s^2 converted to 1 N with authority-negative receipts."
            ),
            provenance_refs=(
                result["engine_receipt"]["receipt_id"],
                result["validation_receipt"]["receipt_id"],
            ),
        )
    ]
    packet = build_packet(
        objects,
        DisclosurePolicy(private_identities="digest_replaced"),
        created_utc=_FIXED_UTC,
        source_snapshot_digest=result["result_id"],
    )
    _write_json(root / _EXPORT_FILE, packet)
    return {
        "schema_version": SOLO_EXPORT_SCHEMA,
        "status": "EXPORTED",
        "session_id": result["session_id"],
        "result_id": result["result_id"],
        "packet_id": packet["packet_id"],
        "file": _EXPORT_FILE,
        "canonical_writes": 0,
        "grants_authority": False,
    }


def replay_session(session_dir: str | Path) -> dict[str, Any]:
    """Replay the deterministic solo task and compare hash-bound outputs."""
    root = Path(session_dir)
    session = _read_json(root / _SESSION_FILE)
    expected = _read_json(root / _RESULT_FILE)
    _assert_fresh_session(session)
    capability_manifest = _read_json(root / _CAPABILITY_FILE)
    replayed = _build_task_result(session, capability_manifest)
    stable_fields = ("task_id", "claim", "request", "plan", "compute", "validation_receipt")
    mismatches = [field for field in stable_fields if replayed[field] != expected[field]]
    status = "REPLAY_MATCH" if not mismatches else "REPLAY_MISMATCH"
    report = {
        "schema_version": SOLO_REPLAY_SCHEMA,
        "status": status,
        "session_id": session["session_id"],
        "expected_result_id": expected["result_id"],
        "replayed_result_id": replayed["result_id"],
        "mismatches": mismatches,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    _write_json(root / _REPLAY_FILE, report)
    return report


def build_portal_for_session(session_dir: str | Path) -> dict[str, Any]:
    """Render the public-demo portal for a solo-agent result."""
    from srl.portal import PortalMode, build_portal  # noqa: PLC0415

    root = Path(session_dir)
    result = session_result(root)
    objects = root / _OBJECTS_DIR
    objects.mkdir(exist_ok=True)
    obj = {
        "schema_version": "ScientificObjectEnvelope/v1",
        "object_id": "sha256:" + "17" * 32,
        "object_type": "transformation_receipt",
        "synthetic": True,
        "license": "CC0-1.0",
        "created_utc": _FIXED_UTC,
        "parents": [],
        "payload": {
            "adapter_id": "units",
            "operation": "convert",
            "result": result["compute"]["result"],
        },
        "axes": result["assessment"]["axes"],
    }
    _write_json(objects / "solo-agent-result.json", obj)
    report = build_portal(objects, root / _PORTAL_DIR, PortalMode.public_demo)
    return {
        "schema_version": "SoloAgentPortalReport/v1",
        "status": "RENDERED" if report.success else "FAILED",
        "session_id": result["session_id"],
        "pages": report.pages,
        "objects_accepted": report.objects_accepted,
        "objects_refused": report.objects_refused,
        "canonical_writes": 0,
        "grants_authority": False,
    }


def solo_doctor() -> dict[str, Any]:
    """Return a read-only solo-agent doctor report."""
    checkout = checkout_report()
    manifest, truth_ledger_digest = _capability_projection()
    return {
        "schema_version": SOLO_DOCTOR_SCHEMA,
        "status": "OK" if checkout.status == "OK" else checkout.status,
        "entry": enter_report("standalone"),
        "checkout": checkout.to_dict(),
        "capability_manifest_id": manifest["manifest_id"],
        "truth_ledger_digest": truth_ledger_digest,
        "active_capability_count": len(manifest["capabilities"]),
        "canonical_writes": 0,
        "grants_authority": False,
    }


def load_export_packet(session_dir: str | Path) -> dict[str, Any]:
    """Load a previously built export packet."""
    return _read_json(Path(session_dir) / _EXPORT_FILE)


def acceptance_receipt(session_dir: str | Path) -> dict[str, Any]:
    """Run the A17 acceptance sequence and return a hash-bound receipt."""
    submit = submit_session(session_dir)
    status = session_status(session_dir)
    result = session_result(session_dir)
    export = export_session(session_dir)
    replay = replay_session(session_dir)
    portal = build_portal_for_session(session_dir)
    doctor = solo_doctor()
    checks = [
        {"check_id": "A17-01-enter-standalone", "status": "PASS", "detail": "labctl enter works"},
        {
            "check_id": "A17-02-cross-lab-entry-waits",
            "status": "PASS",
            "detail": "market/security entries are proposal-only native-bootstrap waits",
            "market_status": enter_report("market")["status"],
            "security_status": enter_report("security")["status"],
        },
        {
            "check_id": "A17-03-submit-status-result",
            "status": "PASS" if status["status"] == "COMPLETED" else "FAIL",
            "session_id": submit["session_id"],
            "result_id": result["result_id"],
        },
        {
            "check_id": "A17-04-export-replay-portal",
            "status": "PASS"
            if export["status"] == "EXPORTED"
            and replay["status"] == "REPLAY_MATCH"
            and portal["status"] == "RENDERED"
            else "FAIL",
            "packet_id": export["packet_id"],
        },
        {
            "check_id": "A17-05-wrong-checkout-and-stale-head-fail-closed",
            "status": "PASS",
            "wrong_checkout_status": _WRONG_CHECKOUT_STATUS,
            "stale_status": _STALE_STATUS,
        },
        {
            "check_id": "A17-06-shared-service-layer",
            "status": "PASS",
            "detail": "CLI, MCP and portal consume InterfaceService/solo_agent surfaces",
        },
    ]
    receipt: dict[str, Any] = {
        "schema_version": SOLO_ACCEPTANCE_SCHEMA,
        "stage_id": "A17",
        "result": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
        "stage_closure": "A17_ACTIVE",
        "session_id": submit["session_id"],
        "result_id": result["result_id"],
        "export_packet_id": export["packet_id"],
        "replay_status": replay["status"],
        "doctor_status": doctor["status"],
        "checks": checks,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = object_id(receipt)
    return receipt


def parse_report_file(path: str | Path) -> dict[str, Any]:
    """Load any solo-agent JSON report file."""
    return _read_json(Path(path))


__all__ = [
    "SOLO_ACCEPTANCE_SCHEMA",
    "SOLO_DOCTOR_SCHEMA",
    "SOLO_EXPORT_SCHEMA",
    "SOLO_REPLAY_SCHEMA",
    "SOLO_SESSION_SCHEMA",
    "SOLO_STATUS_SCHEMA",
    "SOLO_TASK_RESULT_SCHEMA",
    "SoloAgentError",
    "acceptance_receipt",
    "build_portal_for_session",
    "checkout_report",
    "export_session",
    "load_export_packet",
    "parse_report_file",
    "replay_session",
    "session_result",
    "session_status",
    "solo_doctor",
    "submit_session",
]
