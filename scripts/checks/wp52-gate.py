#!/usr/bin/env python3
"""WP-F52 acceptance gate for the static evidence portal.

Runs the five WP-F52 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp52``.

The checks
----------
F52-01 demo build from synthetic fixtures produces all 6 view types
    Build the portal in ``public_demo`` mode from the public fixtures and
    verify that index, object-detail, lineage, evidence, resources, and
    interfaces pages are generated.

F52-02 planted private marker -> build refused typed
    Inject a fixture containing an absolute local path and a credential keyword.
    The public-demo build must refuse it with a ``PUBLIC_LEAK_DETECTED``
    refusal and report failure.

F52-03 HTML escaping (<script> escaped)
    Inject a fixture whose payload contains ``<script>alert(1)</script>`` and
    verify that the generated HTML contains the escaped sequence, not the raw
    tag.

F52-04 zero external resource references in output
    Scan every generated HTML page for external references (``http://``,
    ``https://``, ``<script``, ``<link``, ``<img``, ``src=``) and assert none
    are present.

F52-05 demo watermark on every demo page
    Assert that every HTML page generated in ``public_demo`` mode contains the
    demo watermark banner.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp52-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts.canonical import dumps  # noqa: E402
from srl.portal import PortalMode, build_portal  # noqa: E402

# Receipt identity.
_GATE_SCHEMA: Final[str] = "GateReceipt/v1"
_WP_ID: Final[str] = "WP-F52"

# View-type filenames we expect the demo build to emit.
_VIEW_TYPES: Final[tuple[str, ...]] = (
    "index.html",
    "lineage.html",
    "evidence.html",
    "resources.html",
    "interfaces.html",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _wrap_fixture(path: Path) -> dict[str, Any]:
    """Wrap a raw fixture file in an envelope that records its public source."""
    data = json.loads(path.read_text(encoding="utf-8").strip() or "null")
    object_type = "artifact"
    if isinstance(data, dict) and data.get("schema_version", "").startswith("ScientificClaim"):
        object_type = "claim"
    return {
        "schema_version": "ScientificObjectEnvelope/v1",
        "object_type": object_type,
        "created_utc": "2026-07-28T00:00:00Z",
        "parents": [],
        "payload": data,
        "provenance": {"source_path": f"fixtures/public/{path.name}"},
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _write_object(objects_dir: Path, name: str, obj: dict[str, Any]) -> None:
    """Write a single JSON object to the objects directory."""
    (objects_dir / name).write_text(json.dumps(obj) + "\n", encoding="utf-8")


def _build_demo(objects_dir: Path) -> Path:
    """Build a public-demo portal and return the output directory."""
    out_dir = Path(tempfile.mkdtemp(prefix="srl-portal-f52-"))
    build_portal(objects_dir, out_dir, PortalMode.public_demo)
    return out_dir


def _check_f52_01() -> dict[str, Any]:
    """F52-01: demo build from synthetic fixtures produces all 6 view types."""
    public_dir = _REPO_ROOT / "fixtures" / "public"
    objects_dir = Path(tempfile.mkdtemp(prefix="srl-portal-objects-f52-01-"))
    try:
        for fixture in sorted(public_dir.glob("*.json")):
            if fixture.name == "MANIFEST.json":
                continue
            _write_object(objects_dir, fixture.name, _wrap_fixture(fixture))
        out_dir = _build_demo(objects_dir)
        try:
            generated = {p.name for p in out_dir.iterdir() if p.suffix == ".html"}
            view_files = {name for name in _VIEW_TYPES}
            missing = sorted(view_files - generated)
            has_object_detail = any(p.name.startswith("obj_") for p in out_dir.iterdir())
            if missing or not has_object_detail:
                return {
                    "status": "FAIL",
                    "detail": "missing expected view types",
                    "missing": missing,
                    "has_object_detail": has_object_detail,
                    "generated": sorted(generated),
                }
            return {
                "status": "PASS",
                "detail": "all 6 view types generated from public fixtures",
                "generated": sorted(generated),
            }
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
    finally:
        shutil.rmtree(objects_dir, ignore_errors=True)


def _check_f52_02() -> dict[str, Any]:
    """F52-02: a planted private marker causes a typed PUBLIC_LEAK_DETECTED refusal."""
    objects_dir = Path(tempfile.mkdtemp(prefix="srl-portal-objects-f52-02-"))
    try:
        bad = {
            "schema_version": "ScientificObjectEnvelope/v1",
            "object_type": "artifact",
            "created_utc": "2026-07-28T00:00:00Z",
            "parents": [],
            "payload": {
                "source_path": "fixtures/public/private-marker.json",
                "local_path": "/"
                + "Users"
                + "/alice/secret.txt",  # synthetic marker, built at runtime
                "password": "hunter2",
            },
            "canonical_writes": 0,
            "grants_authority": False,
        }
        _write_object(objects_dir, "private-marker.json", bad)
        out_dir = Path(tempfile.mkdtemp(prefix="srl-portal-out-f52-02-"))
        try:
            report = build_portal(objects_dir, out_dir, PortalMode.public_demo)
            has_leak_refusal = any(
                refusal.get("reason") == "PUBLIC_LEAK_DETECTED" for refusal in report.refusals
            )
            if report.success or not has_leak_refusal:
                return {
                    "status": "FAIL",
                    "detail": "private marker was not refused with PUBLIC_LEAK_DETECTED",
                    "success": report.success,
                    "refusals": report.refusals,
                }
            return {
                "status": "PASS",
                "detail": "planted private marker refused with PUBLIC_LEAK_DETECTED",
                "refusals": report.refusals,
            }
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
    finally:
        shutil.rmtree(objects_dir, ignore_errors=True)


def _check_f52_03() -> dict[str, Any]:
    """F52-03: a <script> payload is escaped in generated HTML."""
    payload_text = "<script>alert(1)</script>"
    objects_dir = Path(tempfile.mkdtemp(prefix="srl-portal-objects-f52-03-"))
    try:
        obj = {
            "schema_version": "ScientificObjectEnvelope/v1",
            "object_type": "claim",
            "created_utc": "2026-07-28T00:00:00Z",
            "parents": [],
            "payload": {"statement": payload_text, "provenance": "fixtures/public/xss.json"},
            "canonical_writes": 0,
            "grants_authority": False,
        }
        _write_object(objects_dir, "xss.json", obj)
        out_dir = _build_demo(objects_dir)
        try:
            pages = list(out_dir.glob("*.html"))
            joined = "\n".join(p.read_text(encoding="utf-8") for p in pages)
            escaped = "&lt;script&gt;alert(1)&lt;/script&gt;"
            if payload_text in joined:
                return {
                    "status": "FAIL",
                    "detail": "raw <script> payload found in generated HTML",
                }
            if escaped not in joined:
                return {
                    "status": "FAIL",
                    "detail": "escaped <script> payload not found in generated HTML",
                }
            return {
                "status": "PASS",
                "detail": "<script> payload escaped in every generated page",
            }
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
    finally:
        shutil.rmtree(objects_dir, ignore_errors=True)


def _check_f52_04() -> dict[str, Any]:
    """F52-04: no external resource references in generated HTML."""
    objects_dir = Path(tempfile.mkdtemp(prefix="srl-portal-objects-f52-04-"))
    try:
        obj = {
            "schema_version": "ScientificObjectEnvelope/v1",
            "object_type": "claim",
            "created_utc": "2026-07-28T00:00:00Z",
            "parents": [],
            "payload": {"statement": "hello world"},
            "provenance": {"source_path": "fixtures/public/clean.json"},
            "canonical_writes": 0,
            "grants_authority": False,
        }
        _write_object(objects_dir, "clean.json", obj)
        out_dir = _build_demo(objects_dir)
        try:
            forbidden = ["http://", "https://", "<script", "<link", "<img", "src="]
            offenders: list[dict[str, str]] = []
            for page in out_dir.iterdir():
                if page.suffix != ".html":
                    continue
                text = page.read_text(encoding="utf-8")
                for marker in forbidden:
                    if marker in text:
                        offenders.append({"page": page.name, "marker": marker})
            if offenders:
                return {
                    "status": "FAIL",
                    "detail": "external resource references found in output",
                    "offenders": offenders,
                }
            return {
                "status": "PASS",
                "detail": "no external resource references in generated HTML",
            }
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
    finally:
        shutil.rmtree(objects_dir, ignore_errors=True)


def _check_f52_05() -> dict[str, Any]:
    """F52-05: every public-demo page carries the demo watermark."""
    objects_dir = Path(tempfile.mkdtemp(prefix="srl-portal-objects-f52-05-"))
    try:
        obj = {
            "schema_version": "ScientificObjectEnvelope/v1",
            "object_type": "claim",
            "created_utc": "2026-07-28T00:00:00Z",
            "parents": [],
            "payload": {"statement": "demo watermark test"},
            "provenance": {"source_path": "fixtures/public/watermark.json"},
            "canonical_writes": 0,
            "grants_authority": False,
        }
        _write_object(objects_dir, "watermark.json", obj)
        out_dir = _build_demo(objects_dir)
        try:
            pages = sorted(p for p in out_dir.iterdir() if p.suffix == ".html")
            missing: list[str] = []
            for page in pages:
                text = page.read_text(encoding="utf-8")
                if "DEMO" not in text:
                    missing.append(page.name)
            if missing:
                return {
                    "status": "FAIL",
                    "detail": "demo watermark missing from pages",
                    "missing": missing,
                }
            return {
                "status": "PASS",
                "detail": "demo watermark present on every generated page",
                "page_count": len(pages),
            }
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
    finally:
        shutil.rmtree(objects_dir, ignore_errors=True)


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "F52-01": _check_f52_01(),
        "F52-02": _check_f52_02(),
        "F52-03": _check_f52_03(),
        "F52-04": _check_f52_04(),
        "F52-05": _check_f52_05(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": _GATE_SCHEMA,
        "wp_id": _WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for checks.json invocations.
    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "F52-01": _check_f52_01,
            "F52-02": _check_f52_02,
            "F52-03": _check_f52_03,
            "F52-04": _check_f52_04,
            "F52-05": _check_f52_05,
        }
        runner = runners.get(cid)
        if runner is None:
            _emit(
                {"schema_version": _GATE_SCHEMA, "wp_id": _WP_ID, "error": f"unknown check {cid}"}
            )
            return 2
        result = runner()
        _emit({"schema_version": _GATE_SCHEMA, "wp_id": _WP_ID, "check": cid, **result})
        return 0 if result["status"] == "PASS" else 1

    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
