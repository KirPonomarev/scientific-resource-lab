#!/usr/bin/env python3
"""V3.7 A03 environment factory and supply-chain gate.

This gate proves the software factory side of A03. It builds deterministic
environment profile manifests for uv/Python, native binaries, Julia depots and
Lean/prover tooling while refusing global mutable depots, revoked dependencies
and unknown-license ACTIVE claims. It performs no package installation and does
not claim scientific pack acceptance for later toolchain stages.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts import dumps  # noqa: E402
from srl.contracts.ids import object_id  # noqa: E402
from srl.packs.environment import (  # noqa: E402
    ENVIRONMENT_FACTORY_RECEIPT_SCHEMA_VERSION,
    GLOBAL_MUTABLE_DEPOT_REASON,
    UNKNOWN_LICENSE_REASON,
    EnvironmentDependency,
    EnvironmentFactoryError,
    EnvironmentKind,
    EnvironmentProfileRecord,
    EnvironmentProfileSpec,
    EnvironmentStatus,
    build_environment_factory_receipt,
    build_environment_profile,
    default_mutable_roots,
)
from srl.packs.governance import PackRevocationRegistry  # noqa: E402

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A03"
EXPECTED_KINDS: Final[set[str]] = {kind.value for kind in EnvironmentKind}


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def _dep(
    dependency_id: str,
    *,
    license_spdx: str = "MIT",
    digest_char: str = "a",
    depends_on: tuple[str, ...] = (),
) -> EnvironmentDependency:
    return EnvironmentDependency(
        dependency_id=dependency_id,
        version="1.0.0",
        license_spdx=license_spdx,
        artifact_sha256=_digest(digest_char),
        depends_on=depends_on,
    )


def _spec(
    profile_id: str,
    kind: EnvironmentKind,
    *,
    dependencies: tuple[EnvironmentDependency, ...],
    native_tools: tuple[str, ...] = (),
) -> EnvironmentProfileSpec:
    return EnvironmentProfileSpec(
        profile_id=profile_id,
        kind=kind,
        lock_sha256=_digest("b"),
        sbom_sha256=_digest("c"),
        dependencies=dependencies,
        mutable_roots=default_mutable_roots(profile_id),
        native_tools=native_tools,
    )


def _positive_specs() -> tuple[EnvironmentProfileSpec, ...]:
    return (
        _spec(
            "python-uv-core",
            EnvironmentKind.PYTHON_UV,
            dependencies=(
                _dep("python", digest_char="1"),
                _dep("uv", digest_char="2", depends_on=("python",)),
                _dep("sympy", digest_char="3", depends_on=("python",)),
            ),
            native_tools=("uv",),
        ),
        _spec(
            "native-binary-core",
            EnvironmentKind.NATIVE_BINARY,
            dependencies=(_dep("native-tool", digest_char="4"),),
            native_tools=("native-tool",),
        ),
        _spec(
            "julia-depot-core",
            EnvironmentKind.JULIA_DEPOT,
            dependencies=(
                _dep("julia", digest_char="5"),
                _dep("julia-symbolics", digest_char="6", depends_on=("julia",)),
            ),
            native_tools=("julia",),
        ),
        _spec(
            "lean-prover-core",
            EnvironmentKind.LEAN_PROVER,
            dependencies=(
                _dep("elan", digest_char="7"),
                _dep("lean4", license_spdx="Apache-2.0", digest_char="8", depends_on=("elan",)),
            ),
            native_tools=("elan", "lean4"),
        ),
    )


def _check_deterministic_rebuild() -> dict[str, Any]:
    failures: list[str] = []
    records: list[EnvironmentProfileRecord] = []
    revocations = PackRevocationRegistry(frozenset(), frozenset())
    for spec in _positive_specs():
        first = build_environment_profile(spec, revocations)
        second = build_environment_profile(spec, revocations)
        records.append(first)
        if (
            first.manifest != second.manifest
            or first.canonical_digest() != second.canonical_digest()
        ):
            failures.append(f"{spec.profile_id} rebuild is not deterministic")
        if first.status is not EnvironmentStatus.ACTIVE:
            failures.append(f"{spec.profile_id} did not become ACTIVE: {first.reasons}")
    receipt = build_environment_factory_receipt(tuple(records))
    profile_kinds = receipt["profile_kinds"]
    if (
        not isinstance(profile_kinds, list)
        or not all(isinstance(kind, str) for kind in profile_kinds)
        or set(profile_kinds) != EXPECTED_KINDS
    ):
        failures.append(f"profile kind coverage drifted: {receipt['profile_kinds']}")
    if receipt["schema_version"] != ENVIRONMENT_FACTORY_RECEIPT_SCHEMA_VERSION:
        failures.append("factory receipt schema drifted")
    return {
        "check_id": "A03-01-deterministic-profile-rebuild",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "four environment kinds rebuild byte-stable profile manifests",
        "factory_receipt": receipt,
    }


def _check_no_global_mutable_depot() -> dict[str, Any]:
    failures: list[str] = []
    records = tuple(
        build_environment_profile(spec, PackRevocationRegistry(frozenset(), frozenset()))
        for spec in _positive_specs()
    )
    forbidden = ("~", "$HOME", "/Users/", "/home/", "/Volumes/", ".venv", "site-packages", ".julia")
    rendered = json.dumps([record.to_dict() for record in records], sort_keys=True)
    for token in forbidden:
        if token in rendered:
            failures.append(f"profile manifest leaked global mutable depot token {token!r}")
    rejected = False
    try:
        EnvironmentProfileSpec(
            profile_id="bad-global-root",
            kind=EnvironmentKind.JULIA_DEPOT,
            lock_sha256=_digest("b"),
            sbom_sha256=_digest("c"),
            dependencies=(_dep("julia", digest_char="9"),),
            mutable_roots=("~/.julia",),
        )
    except EnvironmentFactoryError as exc:
        rejected = exc.fail_reason == GLOBAL_MUTABLE_DEPOT_REASON
    if not rejected:
        failures.append("global Julia depot was not rejected")
    return {
        "check_id": "A03-02-no-global-mutable-depot",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "mutable roots are isolated work namespaces and global depot is rejected",
    }


def _check_revocation_prevents_scheduling() -> dict[str, Any]:
    record = build_environment_profile(
        _spec(
            "revoked-transitive-core",
            EnvironmentKind.PYTHON_UV,
            dependencies=(
                _dep("root-tool", digest_char="a", depends_on=("revoked-lib",)),
                _dep("revoked-lib", digest_char="d"),
            ),
        ),
        PackRevocationRegistry(frozenset(), frozenset({"revoked-lib"})),
    )
    failures = []
    if record.status is not EnvironmentStatus.REVOKED:
        failures.append(f"revoked dependency yielded {record.status.value}")
    if record.reasons != ("revoked_dependency:revoked-lib",):
        failures.append(f"unexpected revocation reasons: {record.reasons}")
    return {
        "check_id": "A03-03-revoked-dependency-prevents-scheduling",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "transitive dependency revocation prevents profile scheduling",
        "record_digest": record.canonical_digest(),
    }


def _check_unknown_license_cannot_be_active() -> dict[str, Any]:
    record = build_environment_profile(
        _spec(
            "unknown-license-core",
            EnvironmentKind.NATIVE_BINARY,
            dependencies=(
                _dep("mystery-tool", license_spdx="LicenseRef-Unknown", digest_char="e"),
            ),
        ),
        PackRevocationRegistry(frozenset(), frozenset()),
    )
    failures = []
    if record.status is EnvironmentStatus.ACTIVE:
        failures.append("unknown-license profile became ACTIVE")
    if record.status is not EnvironmentStatus.WAIT_LICENSE:
        failures.append(f"unknown-license profile yielded {record.status.value}")
    if record.reasons != (f"{UNKNOWN_LICENSE_REASON}:mystery-tool",):
        failures.append(f"unexpected license reasons: {record.reasons}")
    return {
        "check_id": "A03-04-license-unknown-not-active",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "unknown license is parked at WAIT_LICENSE and cannot become ACTIVE",
        "record_digest": record.canonical_digest(),
    }


def build_gate_receipt() -> dict[str, Any]:
    checks = (
        _check_deterministic_rebuild(),
        _check_no_global_mutable_depot(),
        _check_revocation_prevents_scheduling(),
        _check_unknown_license_cannot_be_active(),
    )
    failures = [check for check in checks if check["status"] != "PASS"]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "status": "FAIL" if failures else "PASS",
        "terminal_state": "A03_ACCEPTED" if not failures else "A03_BLOCKED",
        "checks": list(checks),
        "stage_closure": "SOFTWARE_ENVIRONMENT_FACTORY_ACTIVE" if not failures else "BLOCKED",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    payload["receipt_id"] = object_id(payload)
    return payload


def main() -> int:
    receipt = build_gate_receipt()
    sys.stdout.buffer.write(dumps(receipt))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
