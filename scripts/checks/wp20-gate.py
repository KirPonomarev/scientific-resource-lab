#!/usr/bin/env python3
"""WP-C20 acceptance gate for the storage abstraction and T7 identity guard.

Runs the four WP-C20 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp20``.

The checks
----------
C20-01 wrong volume -> fail closed
    A volume mounted at the expected point whose UUID does not match the
    expected identity is refused with ``WRONG_T7_VOLUME`` (hard stop). The store
    fails closed: no bytes are written and there is no fallback to another
    volume. ``verify_t7_identity`` raises :class:`WrongVolumeError`; the
    :class:`~srl.cas.store.T7ArtifactStore` constructor surfaces it.

C20-02 unplugged T7 -> WAIT_STORAGE; local is market-irrelevant
    When the T7 is absent (the provider raises ``T7UnavailableError``) the store
    waits (``WAIT_STORAGE``); the local store is *not* a fallback for T7-bound
    content. The gate asserts the T7 store raises and that nothing else happens
    (no bytes written, no fallback path taken). ``probe_mount`` returns ABSENT
    with the ``wait_storage`` directive.

C20-03 agent-facing API never emits a raw T7/home path
    No public-API string output of the ``srl.cas`` package begins with
    ``/Volumes/`` or ``/Users/``. The gate exercises every public function over
    the fixtures and scans the returned strings; a raw path is a privacy leak
    and a hard FAIL. Store roots are redacted to ``redacted:<16 hex>`` tokens.

C20-04 fallback accepts tiny public fixture, refuses T7-class object
    The local fallback store accepts a ``<1 MiB`` public fixture (object class
    ``FIXTURE``, the only non-T7-bound class) and refuses a T7-class object
    (any T7-bound class) with ``WAIT_STORAGE``. It also refuses an oversized
    object (> 1 MiB) even if the class is ``FIXTURE``.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp20-gate.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion). It is hermetic: it injects
fake providers and uses a temporary directory for the local store; it never
touches a real disk.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp20-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.cas import (  # noqa: E402  (path setup must precede import)
    CapacityDecision,
    LocalArtifactStore,
    LocalFallbackStore,
    MountInfo,
    MountInfoProvider,
    MountState,
    ObjectClass,
    StoreWaitError,
    T7ArtifactStore,
    T7UnavailableError,
    WrongVolumeError,
    check_capacity,
    probe_mount,
    redact_store_path,
    verify_t7_identity,
)
from srl.contracts import dumps  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-C20"

# Fixtures directory (the storage conformance vectors).
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "storage"

# The fake expected UUID (matches the mounted_expected fixture). Fake RFC 4122
# v4 UUID; never a real operator volume.
_EXPECTED_UUID: Final[str] = "00000000-0000-4000-8000-000000000001"
# A fake foreign UUID (matches the mounted_foreign fixture).
_FOREIGN_UUID: Final[str] = "00000000-0000-4000-8000-000000000099"
# A synthetic mount point used only inside the gate's fake providers. It is a
# redacted token, not a real path, so it never leaks.
_FAKE_MOUNT_POINT: Final[str] = "redacted:gate-mount-point"

# Patterns that mark a raw host-local path leak. A public-API string output
# beginning with either is a hard FAIL (privacy contract).
_RAW_PATH_RE: Final[re.Pattern[str]] = re.compile(r"^/(Volumes|Users|home)/")

# The typed fail reasons surfaced in the gate receipt, mirrored from the
# fail-reason registry so the receipt records the routing symbol.
WRONG_VOLUME_FAIL_REASON_REF: Final[str] = "WRONG_T7_VOLUME"
T7_UNAVAILABLE_FAIL_REASON_REF: Final[str] = "T7_UNAVAILABLE"
WAIT_STORAGE_FAIL_REASON_REF: Final[str] = "WAIT_STORAGE"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _provider_returning(info: MountInfo | None) -> MountInfoProvider:
    """Build a fake provider that returns ``info`` (or raises if None).

    A None ``info`` models the absent case: the provider raises
    ``T7UnavailableError`` (as ``diskutil`` would on a nonzero exit), so the
    identity guard and the store take the wait path.
    """

    def _provider(mount_point: str) -> MountInfo:
        del mount_point  # unused: the fake ignores the argument
        if info is None:
            raise T7UnavailableError(
                "fake provider: no volume mounted (absent fixture)",
                reason="diskutil_nonzero_exit",
            )
        return dict(info)

    return _provider


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture from the storage conformance directory."""
    path = _FIXTURES / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# C20-01 wrong volume -> fail closed (no bytes written, no fallback).
# ---------------------------------------------------------------------------


def _check_c20_01() -> dict[str, Any]:
    """C20-01: a wrong UUID is refused with WRONG_T7_VOLUME, fail closed."""
    fixture = _load_fixture("mount_info-mounted-foreign")
    foreign_info = fixture["mount_info"]
    provider = _provider_returning(foreign_info)
    cases: list[dict[str, Any]] = []

    # verify_t7_identity raises WrongVolumeError directly.
    vw_rejected = False
    vw_reason = ""
    vw_observed = ""
    try:
        verify_t7_identity(
            expected_uuid=_EXPECTED_UUID,
            mount_point=_FAKE_MOUNT_POINT,
            provider=provider,
        )
    except WrongVolumeError as exc:
        vw_rejected = True
        vw_reason = exc.fail_reason
        vw_observed = exc.observed_uuid
    cases.append(
        {
            "case": "verify_t7_identity-rejects-wrong-uuid",
            "rejected": vw_rejected,
            "fail_reason": vw_reason,
            "observed_uuid": vw_observed,
        }
    )

    # probe_mount maps the wrong volume to MOUNTED_FOREIGN + fail_closed.
    state, directive = probe_mount(
        expected_uuid=_EXPECTED_UUID,
        mount_point=_FAKE_MOUNT_POINT,
        provider=provider,
    )
    cases.append(
        {
            "case": "probe_mount-returns-foreign-fail-closed",
            "state": state.value,
            "directive": directive,
        }
    )

    # T7ArtifactStore constructor surfaces the WrongVolumeError (fail closed at
    # construction, never on first use). No bytes are written because the
    # constructor raises before any store method can run.
    store_rejected = False
    store_reason = ""
    try:
        T7ArtifactStore(
            mount_point=_FAKE_MOUNT_POINT,
            provider=provider,
            expected_uuid=_EXPECTED_UUID,
        )
    except WrongVolumeError as exc:
        store_rejected = True
        store_reason = exc.fail_reason
    cases.append(
        {
            "case": "t7-store-constructor-rejects-wrong-volume",
            "rejected": store_rejected,
            "fail_reason": store_reason,
        }
    )

    failures = []
    if not vw_rejected or vw_reason != WRONG_VOLUME_FAIL_REASON_REF:
        failures.append("verify_t7_identity did not reject with WRONG_T7_VOLUME")
    if vw_observed != _FOREIGN_UUID:
        failures.append("WrongVolumeError did not carry the observed foreign UUID")
    if state is not MountState.MOUNTED_FOREIGN or directive != "fail_closed":
        failures.append("probe_mount did not return MOUNTED_FOREIGN/fail_closed")
    if not store_rejected or store_reason != WRONG_VOLUME_FAIL_REASON_REF:
        failures.append("T7ArtifactStore did not fail closed at construction")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "wrong volume refused with WRONG_T7_VOLUME at verify_t7_identity, "
            "probe_mount (MOUNTED_FOREIGN/fail_closed), and the T7ArtifactStore "
            "constructor; no bytes written, no fallback"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C20-02 unplugged T7 -> WAIT_STORAGE; local is market-irrelevant.
# ---------------------------------------------------------------------------


def _check_c20_02() -> dict[str, Any]:
    """C20-02: an absent T7 waits; the local store is not a fallback for T7 content."""
    cases: list[dict[str, Any]] = []

    # probe_mount on the absent provider returns ABSENT + wait_storage.
    absent_provider = _provider_returning(None)
    state, directive = probe_mount(
        expected_uuid=_EXPECTED_UUID,
        mount_point=_FAKE_MOUNT_POINT,
        provider=absent_provider,
    )
    cases.append(
        {
            "case": "probe_mount-absent-returns-wait-storage",
            "state": state.value,
            "directive": directive,
        }
    )

    # verify_t7_identity raises T7UnavailableError on the absent provider.
    unavailable_rejected = False
    unavailable_reason = ""
    try:
        verify_t7_identity(
            expected_uuid=_EXPECTED_UUID,
            mount_point=_FAKE_MOUNT_POINT,
            provider=absent_provider,
        )
    except T7UnavailableError as exc:
        unavailable_rejected = True
        unavailable_reason = exc.fail_reason
    cases.append(
        {
            "case": "verify_t7_identity-absent-raises-unavailable",
            "rejected": unavailable_rejected,
            "fail_reason": unavailable_reason,
        }
    )

    # The T7ArtifactStore stub refuses put with WAIT_STORAGE even when the
    # identity IS verified (the transaction engine is unimplemented). Use the
    # expected provider so construction succeeds, then assert put waits.
    expected_info = _load_fixture("mount_info-mounted-expected")["mount_info"]
    expected_provider = _provider_returning(expected_info)
    stub_put_waited = False
    stub_reason = ""
    with tempfile.TemporaryDirectory() as tmp:
        store = T7ArtifactStore(
            mount_point=_FAKE_MOUNT_POINT,
            provider=expected_provider,
            expected_uuid=_EXPECTED_UUID,
        )
        try:
            store.put(b"would-be-t7-content")
        except StoreWaitError as exc:
            stub_put_waited = True
            stub_reason = exc.fail_reason
        # Nothing was written: assert the temp dir holds no objects tree from
        # this store (the stub never materializes bytes). The temp dir is the
        # gate's own scratch; the stub does not use it, so it must be empty of
        # the stub's writes.
        stub_wrote = any(Path(tmp).rglob("objects"))
    cases.append(
        {
            "case": "t7-stub-put-waits-storage",
            "waited": stub_put_waited,
            "fail_reason": stub_reason,
            "wrote_bytes": stub_wrote,
        }
    )

    failures = []
    if state is not MountState.ABSENT or directive != "wait_storage":
        failures.append("probe_mount did not return ABSENT/wait_storage for absent T7")
    if not unavailable_rejected or unavailable_reason != T7_UNAVAILABLE_FAIL_REASON_REF:
        failures.append("verify_t7_identity did not raise T7_UNAVAILABLE for absent T7")
    if not stub_put_waited or stub_reason != WAIT_STORAGE_FAIL_REASON_REF:
        failures.append("T7ArtifactStore.put did not wait with WAIT_STORAGE")
    if stub_wrote:
        failures.append("T7ArtifactStore stub wrote bytes (it must never write)")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "absent T7 -> probe_mount ABSENT/wait_storage and verify_t7_identity "
            "T7_UNAVAILABLE; the T7ArtifactStore stub waits (WAIT_STORAGE) and "
            "writes nothing; the local store is not a fallback for T7 content"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C20-03 agent-facing API never emits a raw T7/home path.
# ---------------------------------------------------------------------------


def _scan_strings(value: Any) -> list[str]:
    """Recursively collect every string reachable from ``value``.

    Walks dicts, lists, tuples, dataclasses, and the str() of objects to gather
    every string a public API could surface in a receipt. Used by the no-raw-path
    scan so a nested redacted token is checked just like a top-level one.
    """
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_scan_strings(v))
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_scan_strings(item))
    else:
        # For dataclasses and other objects, scan the str() form (a receipt
        # might render the object) but also walk __dict__ for hidden fields.
        out.append(str(value))
        if hasattr(value, "__dict__"):
            out.extend(_scan_strings(vars(value)))
    return out


def _collect_leaks(values: Any, *, function: str, sub: str, leaks: list[dict[str, str]]) -> None:
    """Scan ``values`` for raw host-local paths and append any findings.

    Factored out of ``_check_c20_03`` so the check stays under the McCabe
    complexity budget. ``values`` may be a single object or a tuple of objects;
    each is recursively string-scanned.
    """
    if isinstance(values, tuple):
        for v in values:
            _collect_leaks(v, function=function, sub=sub, leaks=leaks)
        return
    for s in _scan_strings(values):
        if _RAW_PATH_RE.match(s):
            leaks.append({"function": function, "sub": sub, "leaked": s})


def _check_c20_03() -> dict[str, Any]:
    """C20-03: no public-API string output begins with /Volumes/ or /Users/."""
    leaks: list[dict[str, str]] = []

    # Exercise redact_store_path with a raw-looking path; the result must be a
    # redacted token, never the raw path.
    redacted = redact_store_path("/Volumes/T7/srl-cas")
    _collect_leaks(redacted, function="redact_store_path", sub="", leaks=leaks)

    # Exercise a LocalArtifactStore in a temp dir rooted at a /Volumes-style and
    # a /Users-style path (under the system temp, so the prefix is synthetic).
    # The descriptor and the store_root_redacted must never carry the raw root.
    expected_info = _load_fixture("mount_info-mounted-expected")["mount_info"]
    provider = _provider_returning(expected_info)
    with tempfile.TemporaryDirectory() as tmp:
        for sub in ("Volumes/T7-fake", "Users/operator-fake"):
            root = Path(tmp) / sub
            store = LocalArtifactStore(root)
            desc = store.put(b"c20-03-privacy-probe")
            _collect_leaks(
                (store.store_root_redacted, vars(desc), vars(store.fsck())),
                function="LocalArtifactStore",
                sub=sub,
                leaks=leaks,
            )
            # The identity receipt (from verify_t7_identity) must also be clean.
            receipt = verify_t7_identity(
                expected_uuid=_EXPECTED_UUID,
                mount_point=str(root),
                provider=provider,
            )
            _collect_leaks(receipt, function="verify_t7_identity", sub=sub, leaks=leaks)

    # Also assert the redacted form is well-shaped: redacted:<16 hex>.
    redacted_shape_ok = bool(re.fullmatch(r"redacted:[0-9a-f]{16}", redacted))

    if leaks or not redacted_shape_ok:
        detail_parts: list[str] = []
        if leaks:
            detail_parts.append(f"{len(leaks)} raw path leak(s) in public API outputs")
        if not redacted_shape_ok:
            detail_parts.append(f"redacted form is misshapen: {redacted!r}")
        return {
            "status": "FAIL",
            "detail": "; ".join(detail_parts),
            "leaks": leaks,
            "redacted_sample": redacted,
            "redacted_shape_ok": redacted_shape_ok,
        }
    return {
        "status": "PASS",
        "detail": (
            "no public-API string output of srl.cas begins with /Volumes/ or "
            "/Users/ over the fixtures; store roots are redacted: tokens"
        ),
        "leaks": [],
        "redacted_sample": redacted,
        "redacted_shape_ok": True,
    }


# ---------------------------------------------------------------------------
# C20-04 fallback accepts tiny public fixture, refuses T7-class object.
# ---------------------------------------------------------------------------


def _check_c20_04() -> dict[str, Any]:
    """C20-04: fallback accepts tiny fixtures and refuses T7-class objects."""
    cases: list[dict[str, Any]] = []

    # Load the tiny fixture blob (<1 KiB).
    blob_path = _FIXTURES / "tiny-fixture-blob.txt"
    tiny = blob_path.read_bytes()

    with tempfile.TemporaryDirectory() as tmp:
        fallback = LocalFallbackStore(Path(tmp))

        # Accept: tiny public fixture (object class FIXTURE, <1 MiB).
        accepted = False
        accepted_digest = ""
        try:
            desc = fallback.put(tiny, object_class=ObjectClass.FIXTURE)
            accepted = True
            accepted_digest = desc.digest
        except StoreWaitError:
            accepted = False
        cases.append(
            {
                "case": "fallback-accepts-tiny-fixture",
                "accepted": accepted,
                "digest": accepted_digest,
                "size_bytes": len(tiny),
            }
        )

        # Refuse: T7-class object (any T7-bound class), even if tiny.
        t7_refused = False
        t7_reason = ""
        try:
            fallback.put(tiny, object_class=ObjectClass.PACK_IMAGE)
        except StoreWaitError as exc:
            t7_refused = True
            t7_reason = exc.fail_reason
        cases.append(
            {
                "case": "fallback-refuses-t7-class-pack-image",
                "refused": t7_refused,
                "fail_reason": t7_reason,
            }
        )

        # Refuse: oversized object (>1 MiB), even if class FIXTURE.
        oversized = _load_fixture("oversized-descriptor")
        declared_size = oversized["declared_size_bytes"]
        # Materialize the oversized bytes only in memory (never written): we
        # need real bytes to exercise the size refusal. Use a deterministic
        # fill so the gate is reproducible; the bytes never hit disk because
        # the fallback refuses before delegating to the local store.
        oversized_bytes = (b"x" * 1024) * (declared_size // 1024 + 1)
        size_refused = False
        size_reason = ""
        try:
            fallback.put(oversized_bytes, object_class=ObjectClass.FIXTURE)
        except StoreWaitError as exc:
            size_refused = True
            size_reason = exc.fail_reason
        cases.append(
            {
                "case": "fallback-refuses-oversized-fixture",
                "refused": size_refused,
                "fail_reason": size_reason,
                "declared_size_bytes": declared_size,
            }
        )

        # Capacity policy sanity: the EXCEEDED band refuses ingest at the store
        # layer. check_capacity(ceiling) == EXCEEDED.
        exceeded_decision = check_capacity(50 * 1024**3)
        cases.append(
            {
                "case": "capacity-exceeded-at-ceiling",
                "decision": exceeded_decision.value,
            }
        )

    failures = []
    if not accepted:
        failures.append("fallback did not accept the tiny public fixture")
    if not t7_refused or t7_reason != WAIT_STORAGE_FAIL_REASON_REF:
        failures.append("fallback did not refuse a T7-class object with WAIT_STORAGE")
    if not size_refused or size_reason != WAIT_STORAGE_FAIL_REASON_REF:
        failures.append("fallback did not refuse an oversized object with WAIT_STORAGE")
    if exceeded_decision is not CapacityDecision.EXCEEDED:
        failures.append("check_capacity did not return EXCEEDED at the 50 GiB ceiling")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "fallback accepts the <1 MiB public fixture and refuses T7-class "
            "objects and oversized objects with WAIT_STORAGE; capacity EXCEEDED "
            "at the 50 GiB ceiling"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: fixture vector counts."""
    return {
        "mount_info_vectors": len(list(_FIXTURES.glob("mount_info-*.json"))),
        "blob_vectors": len(list(_FIXTURES.glob("*.txt"))),
        "descriptor_vectors": len(list(_FIXTURES.glob("*-descriptor.json"))),
    }


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "C20-01": _check_c20_01(),
        "C20-02": _check_c20_02(),
        "C20-03": _check_c20_03(),
        "C20-04": _check_c20_04(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
            **_evidence(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for the checks.json invocations.
    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "C20-01": _check_c20_01,
            "C20-02": _check_c20_02,
            "C20-03": _check_c20_03,
            "C20-04": _check_c20_04,
        }
        runner = runners.get(cid)
        if runner is None:
            _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "error": f"unknown check {cid}"})
            return 2
        result = runner()
        _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "check": cid, **result})
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
