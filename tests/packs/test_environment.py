from __future__ import annotations

import pytest

from srl.packs.environment import (
    ENVIRONMENT_FACTORY_RECEIPT_SCHEMA_VERSION,
    GLOBAL_MUTABLE_DEPOT_REASON,
    UNKNOWN_LICENSE_REASON,
    EnvironmentDependency,
    EnvironmentFactoryError,
    EnvironmentKind,
    EnvironmentProfileSpec,
    EnvironmentStatus,
    build_environment_factory_receipt,
    build_environment_profile,
    default_mutable_roots,
)
from srl.packs.governance import PackRevocationRegistry


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
    profile_id: str = "python-core",
    kind: EnvironmentKind = EnvironmentKind.PYTHON_UV,
    dependencies: tuple[EnvironmentDependency, ...] = (_dep("sympy"),),
) -> EnvironmentProfileSpec:
    return EnvironmentProfileSpec(
        profile_id=profile_id,
        kind=kind,
        lock_sha256=_digest("b"),
        sbom_sha256=_digest("c"),
        dependencies=dependencies,
        mutable_roots=default_mutable_roots(profile_id),
        native_tools=("uv",),
    )


def test_environment_profile_rebuild_is_deterministic() -> None:
    spec = _spec()
    revocations = PackRevocationRegistry(frozenset(), frozenset())

    first = build_environment_profile(spec, revocations)
    second = build_environment_profile(spec, revocations)

    assert first.status is EnvironmentStatus.ACTIVE
    assert first.manifest == second.manifest
    assert first.canonical_digest() == second.canonical_digest()
    assert first.manifest["factory_executes_install"] is False


@pytest.mark.parametrize(
    ("profile_id", "kind"),
    (
        ("python-core", EnvironmentKind.PYTHON_UV),
        ("native-pari", EnvironmentKind.NATIVE_BINARY),
        ("julia-symbolics", EnvironmentKind.JULIA_DEPOT),
        ("lean-core", EnvironmentKind.LEAN_PROVER),
    ),
)
def test_all_environment_kinds_can_build_isolated_active_profiles(
    profile_id: str,
    kind: EnvironmentKind,
) -> None:
    record = build_environment_profile(
        _spec(profile_id=profile_id, kind=kind, dependencies=(_dep(profile_id),)),
        PackRevocationRegistry(frozenset(), frozenset()),
    )

    assert record.status is EnvironmentStatus.ACTIVE
    assert record.kind is kind
    assert record.manifest["mutable_roots"] == sorted(default_mutable_roots(profile_id))


def test_unknown_license_cannot_be_active() -> None:
    record = build_environment_profile(
        _spec(dependencies=(_dep("mystery", license_spdx="LicenseRef-Unknown"),)),
        PackRevocationRegistry(frozenset(), frozenset()),
    )

    assert record.status is EnvironmentStatus.WAIT_LICENSE
    assert record.reasons == (f"{UNKNOWN_LICENSE_REASON}:mystery",)


def test_revoked_transitive_dependency_prevents_scheduling() -> None:
    record = build_environment_profile(
        _spec(
            dependencies=(
                _dep("root", digest_char="d", depends_on=("revoked-lib",)),
                _dep("revoked-lib", digest_char="e"),
            )
        ),
        PackRevocationRegistry(frozenset(), frozenset({"revoked-lib"})),
    )

    assert record.status is EnvironmentStatus.REVOKED
    assert record.reasons == ("revoked_dependency:revoked-lib",)


@pytest.mark.parametrize(
    "bad_root",
    (
        "/" + "tmp/global-env",
        "~/julia-depot",
        "work/envs/../escape",
        "work/envs/.venv/python-core",
        "work/caches/python-core/site-packages",
    ),
)
def test_global_mutable_depot_is_rejected(bad_root: str) -> None:
    with pytest.raises(EnvironmentFactoryError) as excinfo:
        EnvironmentProfileSpec(
            profile_id="python-core",
            kind=EnvironmentKind.PYTHON_UV,
            lock_sha256=_digest("b"),
            sbom_sha256=_digest("c"),
            dependencies=(_dep("sympy"),),
            mutable_roots=(bad_root,),
        )

    assert excinfo.value.fail_reason == GLOBAL_MUTABLE_DEPOT_REASON


def test_dependency_dag_must_be_closed_and_acyclic() -> None:
    with pytest.raises(EnvironmentFactoryError):
        build_environment_profile(
            _spec(dependencies=(_dep("root", depends_on=("missing",)),)),
            PackRevocationRegistry(frozenset(), frozenset()),
        )

    with pytest.raises(EnvironmentFactoryError):
        build_environment_profile(
            _spec(
                dependencies=(
                    _dep("a", digest_char="d", depends_on=("b",)),
                    _dep("b", digest_char="e", depends_on=("a",)),
                )
            ),
            PackRevocationRegistry(frozenset(), frozenset()),
        )


def test_environment_factory_receipt_lists_active_and_wait_profiles() -> None:
    active = build_environment_profile(
        _spec(profile_id="python-core"),
        PackRevocationRegistry(frozenset(), frozenset()),
    )
    wait = build_environment_profile(
        _spec(
            profile_id="julia-symbolics",
            kind=EnvironmentKind.JULIA_DEPOT,
            dependencies=(_dep("julia-mystery", license_spdx="LicenseRef-Unknown"),),
        ),
        PackRevocationRegistry(frozenset(), frozenset()),
    )

    receipt = build_environment_factory_receipt((active, wait))

    assert receipt["schema_version"] == ENVIRONMENT_FACTORY_RECEIPT_SCHEMA_VERSION
    assert receipt["active_profile_ids"] == ["python-core"]
    assert receipt["wait_profile_ids"] == ["julia-symbolics"]
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False
