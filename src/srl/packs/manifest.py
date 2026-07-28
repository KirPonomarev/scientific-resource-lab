"""Resource pack manifest and validation for SRL autonomous packs.

A :class:`ResourcePackManifest` is the control-plane identity of a scientific
resource pack: a content-addressed bundle of code, data, and provenance that
can be safely extracted, verified, and materialized into a mutable staging area
before execution. The manifest is JSON-first and encodes as canonical JSON so
that independent agents produce byte-identical receipts.

License policy
--------------
The pack license is strictly enforced. An allowlist of permissive, well-known
open-source licenses is accepted; a second list of copyleft / source-available
licenses is rejected as incompatible; anything else is rejected as unknown.
Both rejections are hard contract failures (non-retriable).
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from srl.contracts.artifact_refs import validate_digest
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.planning.profiles import PROFILE_NAMES

# Schema identity. Bumped only on a contract change to the manifest shape.
PACK_MANIFEST_SCHEMA_VERSION: Final[str] = "ResourcePackManifest/v1"

# Fail reasons from the SRL registry (see automation/fail-reasons.json).
PACK_INTEGRITY_FAILURE_REASON: Final[str] = "PACK_INTEGRITY_FAILURE"
LICENSE_UNKNOWN_REASON: Final[str] = "LICENSE_UNKNOWN"
LICENSE_INCOMPATIBLE_REASON: Final[str] = "LICENSE_INCOMPATIBLE"
PLATFORM_UNSUPPORTED_REASON: Final[str] = "PLATFORM_UNSUPPORTED"

# Accepted permissive licenses for included packs.
LICENSE_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "PSF-2.0",
        "Python-2.0",
        "MPL-2.0",
        "CC0-1.0",
    }
)

# Incompatible license prefixes (pattern match on the SPDX identifier).
LICENSE_INCOMPATIBLE_PREFIXES: Final[tuple[str, ...]] = (
    "GPL-",
    "LGPL-",
    "AGPL-",
    "SSPL-",
    "BUSL-",
)

# Allowed platforms and architectures for portable pack declarations.
OS_NAMES: Final[frozenset[str]] = frozenset({"linux", "macos"})
ARCH_NAMES: Final[frozenset[str]] = frozenset({"x86_64", "arm64"})
ENTRYPOINT_KINDS: Final[frozenset[str]] = frozenset({"python_module", "binary"})


class PackManifestError(ContractError):
    """Raised when a pack manifest violates its structural contract.

    Carries the typed fail reason ``CONTRACT_INVALID`` by default.
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


class LicenseError(PackManifestError):
    """Raised when a pack license is unknown or incompatible.

    The fail reason is either ``LICENSE_UNKNOWN`` or ``LICENSE_INCOMPATIBLE``.
    """

    def __init__(self, message: str, *, fail_reason: str) -> None:
        super().__init__(message, fail_reason=fail_reason)


@dataclass(frozen=True, slots=True)
class PlatformSpec:
    """One supported execution platform for a pack."""

    os: str
    arch: str
    abi: str | None


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Provenance of the upstream source that produced the pack."""

    url: str | None
    commit: str | None
    source_sha256: str


@dataclass(frozen=True, slots=True)
class LicenseSpec:
    """License declaration with content-addressed license texts."""

    spdx: str
    texts_sha256: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntrypointSpec:
    """A declared entrypoint inside the pack tree."""

    entrypoint_id: str
    kind: str
    ref: str


@dataclass(frozen=True, slots=True)
class ProbesSpec:
    """Probe entrypoints used by the execution bridge."""

    runtime_probe: str
    actual_compute_probe: str


@dataclass(frozen=True, slots=True)
class ResourcePackManifest:
    """ResourcePackManifest/v1: the content-addressed identity of a pack."""

    schema_version: str
    pack_id: str
    name: str
    version: str
    capability_profiles: tuple[str, ...]
    platforms: tuple[PlatformSpec, ...]
    source: SourceSpec
    lock_sha256: str
    tree_sha256: str
    license: LicenseSpec
    sbom_sha256: str | None
    entrypoints: tuple[EntrypointSpec, ...]
    probes: ProbesSpec
    created_utc: str
    canonical_writes: int
    grants_authority: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the manifest as a plain JSON-serializable dict."""
        return asdict(self)

    def canonical_dumps(self) -> bytes:
        """Return canonical JSON bytes (sorted keys, compact, trailing newline)."""
        return dumps(self.to_dict())


def _validate_sha256(value: Any, field: str) -> str:
    """Validate a sha256 content digest, returning the prefixed string."""
    if not isinstance(value, str):
        msg = f"field {field!r} must be a string, got {type(value).__name__}"
        raise PackManifestError(msg)
    try:
        return validate_digest(value, field=field)
    except Exception as exc:
        msg = f"field {field!r} is not a valid sha256 digest: {exc}"
        raise PackManifestError(msg) from exc


def _validate_non_empty_string(value: Any, field: str) -> str:
    """Validate a required non-empty string field."""
    if not isinstance(value, str) or value == "":
        msg = f"field {field!r} must be a non-empty string, got {value!r}"
        raise PackManifestError(msg)
    return value


def _validate_optional_string(value: Any, field: str) -> str | None:
    """Validate an optional nullable string field."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"optional field {field!r} must be a string or null, got {type(value).__name__}"
        raise PackManifestError(msg)
    return value


def _validate_platform(value: Any, field: str) -> PlatformSpec:
    """Validate one platform spec object."""
    if not isinstance(value, dict):
        msg = f"field {field!r} must be an object, got {type(value).__name__}"
        raise PackManifestError(msg)
    required = {"os", "arch"}
    allowed = frozenset({*required, "abi"})
    actual = set(value.keys())
    missing = required - actual
    if missing:
        msg = f"platform spec missing required key(s): {sorted(missing)}"
        raise PackManifestError(msg)
    extra = actual - allowed
    if extra:
        msg = f"platform spec has unexpected key(s): {sorted(extra)}"
        raise PackManifestError(msg)
    os_value = value["os"]
    if os_value not in OS_NAMES:
        msg = f"platform.os {os_value!r} must be one of {sorted(OS_NAMES)}"
        raise PackManifestError(msg)
    arch_value = value["arch"]
    if arch_value not in ARCH_NAMES:
        msg = f"platform.arch {arch_value!r} must be one of {sorted(ARCH_NAMES)}"
        raise PackManifestError(msg)
    abi = _validate_optional_string(value.get("abi"), "platform.abi")
    return PlatformSpec(os=os_value, arch=arch_value, abi=abi)


def _validate_source(value: Any) -> SourceSpec:
    """Validate the source provenance block."""
    if not isinstance(value, dict):
        msg = f"source must be an object, got {type(value).__name__}"
        raise PackManifestError(msg)
    required = {"url", "commit", "source_sha256"}
    actual = set(value.keys())
    missing = required - actual
    if missing:
        msg = f"source block missing required key(s): {sorted(missing)}"
        raise PackManifestError(msg)
    extra = actual - required
    if extra:
        msg = f"source block has unexpected key(s): {sorted(extra)}"
        raise PackManifestError(msg)
    return SourceSpec(
        url=_validate_optional_string(value["url"], "source.url"),
        commit=_validate_optional_string(value["commit"], "source.commit"),
        source_sha256=_validate_sha256(value["source_sha256"], "source.source_sha256"),
    )


def _validate_license(value: Any) -> LicenseSpec:
    """Validate the license block and enforce the license policy."""
    if not isinstance(value, dict):
        msg = f"license must be an object, got {type(value).__name__}"
        raise PackManifestError(msg)
    required = {"spdx", "texts_sha256"}
    actual = set(value.keys())
    missing = required - actual
    if missing:
        msg = f"license block missing required key(s): {sorted(missing)}"
        raise PackManifestError(msg)
    extra = actual - required
    if extra:
        msg = f"license block has unexpected key(s): {sorted(extra)}"
        raise PackManifestError(msg)
    spdx = _validate_non_empty_string(value["spdx"], "license.spdx")
    if spdx in LICENSE_ALLOWLIST:
        pass  # Accepted.
    elif any(spdx.startswith(prefix) for prefix in LICENSE_INCOMPATIBLE_PREFIXES):
        msg = f"license {spdx!r} is incompatible with the SRL pack policy"
        raise LicenseError(msg, fail_reason=LICENSE_INCOMPATIBLE_REASON)
    else:
        msg = f"license {spdx!r} is not in the SRL pack allowlist"
        raise LicenseError(msg, fail_reason=LICENSE_UNKNOWN_REASON)

    texts = value["texts_sha256"]
    if not isinstance(texts, list):
        msg = f"license.texts_sha256 must be an array, got {type(texts).__name__}"
        raise PackManifestError(msg)
    validated_texts = tuple(
        _validate_sha256(item, f"license.texts_sha256[{i}]") for i, item in enumerate(texts)
    )
    return LicenseSpec(spdx=spdx, texts_sha256=validated_texts)


def _validate_entrypoint(value: Any, field: str) -> EntrypointSpec:
    """Validate one entrypoint spec object."""
    if not isinstance(value, dict):
        msg = f"field {field!r} must be an object, got {type(value).__name__}"
        raise PackManifestError(msg)
    required = {"entrypoint_id", "kind", "ref"}
    actual = set(value.keys())
    missing = required - actual
    if missing:
        msg = f"entrypoint spec missing required key(s): {sorted(missing)}"
        raise PackManifestError(msg)
    extra = actual - required
    if extra:
        msg = f"entrypoint spec has unexpected key(s): {sorted(extra)}"
        raise PackManifestError(msg)
    entrypoint_id = _validate_non_empty_string(value["entrypoint_id"], "entrypoint.entrypoint_id")
    kind = value["kind"]
    if kind not in ENTRYPOINT_KINDS:
        msg = f"entrypoint.kind {kind!r} must be one of {sorted(ENTRYPOINT_KINDS)}"
        raise PackManifestError(msg)
    ref = _validate_non_empty_string(value["ref"], "entrypoint.ref")
    return EntrypointSpec(entrypoint_id=entrypoint_id, kind=kind, ref=ref)


def _validate_probes(value: Any) -> ProbesSpec:
    """Validate the probes block."""
    if not isinstance(value, dict):
        msg = f"probes must be an object, got {type(value).__name__}"
        raise PackManifestError(msg)
    required = {"runtime_probe", "actual_compute_probe"}
    actual = set(value.keys())
    missing = required - actual
    if missing:
        msg = f"probes block missing required key(s): {sorted(missing)}"
        raise PackManifestError(msg)
    extra = actual - required
    if extra:
        msg = f"probes block has unexpected key(s): {sorted(extra)}"
        raise PackManifestError(msg)
    return ProbesSpec(
        runtime_probe=_validate_non_empty_string(value["runtime_probe"], "probes.runtime_probe"),
        actual_compute_probe=_validate_non_empty_string(
            value["actual_compute_probe"], "probes.actual_compute_probe"
        ),
    )


def _validate_top_structure(value: Any) -> dict[str, Any]:
    """Validate top-level dict shape and schema version.

    Returns the value dict after validation so callers can continue extracting
    fields without re-casting.
    """
    if not isinstance(value, dict):
        msg = f"manifest must be a JSON object, got {type(value).__name__}"
        raise PackManifestError(msg)

    expected_top = {
        "schema_version",
        "pack_id",
        "name",
        "version",
        "capability_profiles",
        "platforms",
        "source",
        "lock_sha256",
        "tree_sha256",
        "license",
        "sbom_sha256",
        "entrypoints",
        "probes",
        "created_utc",
        "canonical_writes",
        "grants_authority",
    }
    actual_top = set(value.keys())
    missing = expected_top - actual_top
    if missing:
        msg = f"manifest missing required key(s): {sorted(missing)}"
        raise PackManifestError(msg)
    extra = actual_top - expected_top
    if extra:
        msg = f"manifest has unexpected key(s): {sorted(extra)}"
        raise PackManifestError(msg)

    schema_version = _validate_non_empty_string(value["schema_version"], "schema_version")
    if schema_version != PACK_MANIFEST_SCHEMA_VERSION:
        msg = f"schema_version is {schema_version!r}, expected {PACK_MANIFEST_SCHEMA_VERSION!r}"
        raise PackManifestError(msg)
    return value


def _validate_profiles_field(value: dict[str, Any]) -> tuple[str, ...]:
    """Validate the capability_profiles array and return a tuple of names."""
    profiles = value["capability_profiles"]
    if not isinstance(profiles, list):
        msg = f"capability_profiles must be an array, got {type(profiles).__name__}"
        raise PackManifestError(msg)
    validated: list[str] = []
    for i, item in enumerate(profiles):
        if not isinstance(item, str) or item == "":
            msg = f"capability_profiles[{i}] must be a non-empty string, got {item!r}"
            raise PackManifestError(msg)
        if item not in PROFILE_NAMES:
            msg = (
                f"capability_profiles[{i}]={item!r} is not a known profile; "
                f"must be one of {sorted(PROFILE_NAMES)}"
            )
            raise PackManifestError(msg)
        validated.append(item)
    return tuple(validated)


def _validate_platforms_field(value: dict[str, Any]) -> tuple[PlatformSpec, ...]:
    """Validate the platforms array and return a tuple of platform specs."""
    platforms_raw = value["platforms"]
    if not isinstance(platforms_raw, list) or len(platforms_raw) == 0:
        msg = "platforms must be a non-empty array"
        raise PackManifestError(msg)
    return tuple(
        _validate_platform(item, f"platforms[{i}]") for i, item in enumerate(platforms_raw)
    )


def _validate_entrypoints_and_probes(
    value: dict[str, Any],
) -> tuple[tuple[EntrypointSpec, ...], ProbesSpec]:
    """Validate entrypoints and ensure probes point at declared entrypoint ids."""
    entrypoints_raw = value["entrypoints"]
    if not isinstance(entrypoints_raw, list):
        msg = f"entrypoints must be an array, got {type(entrypoints_raw).__name__}"
        raise PackManifestError(msg)
    validated_entrypoints = tuple(
        _validate_entrypoint(item, f"entrypoints[{i}]") for i, item in enumerate(entrypoints_raw)
    )
    entrypoint_ids = {ep.entrypoint_id for ep in validated_entrypoints}
    probes = _validate_probes(value["probes"])
    if probes.runtime_probe not in entrypoint_ids:
        msg = f"probes.runtime_probe {probes.runtime_probe!r} is not a declared entrypoint"
        raise PackManifestError(msg)
    if probes.actual_compute_probe not in entrypoint_ids:
        msg = (
            f"probes.actual_compute_probe {probes.actual_compute_probe!r} "
            "is not a declared entrypoint"
        )
        raise PackManifestError(msg)
    return validated_entrypoints, probes


def _validate_manifest_tail(value: dict[str, Any]) -> tuple[str, int, bool]:
    """Validate created_utc, canonical_writes, and grants_authority fields."""
    created_utc = _validate_non_empty_string(value["created_utc"], "created_utc")
    canonical_writes = value["canonical_writes"]
    if not isinstance(canonical_writes, int) or isinstance(canonical_writes, bool):
        msg = f"canonical_writes must be an integer, got {type(canonical_writes).__name__}"
        raise PackManifestError(msg)
    if canonical_writes != 0:
        msg = f"canonical_writes must be 0, got {canonical_writes!r}"
        raise PackManifestError(msg)
    grants_authority = value["grants_authority"]
    if not isinstance(grants_authority, bool):
        msg = f"grants_authority must be a boolean, got {type(grants_authority).__name__}"
        raise PackManifestError(msg)
    if grants_authority is not False:
        msg = f"grants_authority must be false, got {grants_authority!r}"
        raise PackManifestError(msg)
    return created_utc, canonical_writes, grants_authority


def build_manifest(value: dict[str, Any]) -> ResourcePackManifest:
    """Build and validate a :class:`ResourcePackManifest` from a raw dict.

    Parameters
    ----------
    value:
        Raw JSON-decoded dict claiming to be a ``ResourcePackManifest/v1``.

    Returns
    -------
    ResourcePackManifest
        A validated, immutable manifest object.

    Raises
    ------
    PackManifestError
        If the structure is invalid (``CONTRACT_INVALID``).
    LicenseError
        If the license is unknown or incompatible.
    """
    value = _validate_top_structure(value)

    pack_id = _validate_non_empty_string(value["pack_id"], "pack_id")
    name = _validate_non_empty_string(value["name"], "name")
    version = _validate_non_empty_string(value["version"], "version")

    validated_profiles = _validate_profiles_field(value)
    validated_platforms = _validate_platforms_field(value)

    source = _validate_source(value["source"])
    lock_sha256 = _validate_sha256(value["lock_sha256"], "lock_sha256")
    tree_sha256 = _validate_sha256(value["tree_sha256"], "tree_sha256")
    license_spec = _validate_license(value["license"])
    sbom = value["sbom_sha256"]
    sbom_sha256: str | None = None
    if sbom is not None:
        sbom_sha256 = _validate_sha256(sbom, "sbom_sha256")

    validated_entrypoints, probes = _validate_entrypoints_and_probes(value)
    created_utc, canonical_writes, grants_authority = _validate_manifest_tail(value)

    return ResourcePackManifest(
        schema_version=PACK_MANIFEST_SCHEMA_VERSION,
        pack_id=pack_id,
        name=name,
        version=version,
        capability_profiles=validated_profiles,
        platforms=validated_platforms,
        source=source,
        lock_sha256=lock_sha256,
        tree_sha256=tree_sha256,
        license=license_spec,
        sbom_sha256=sbom_sha256,
        entrypoints=validated_entrypoints,
        probes=probes,
        created_utc=created_utc,
        canonical_writes=canonical_writes,
        grants_authority=grants_authority,
    )


def compute_tree_sha256(root: str | Path) -> str:
    """Compute a deterministic tree_sha256 over a directory.

    The digest is ``sha256:<hex>`` over the canonical JSON encoding of a dict
    that maps every regular-file path (relative to ``root``) to the sha256 of
    its content. Paths are sorted alphabetically, use forward slashes, and
    never start with ``./``. The canonical encoding uses sorted keys, compact
    separators, UTF-8, and a trailing newline (matching
    :mod:`srl.contracts.canonical`).
    """
    root_path = Path(root)
    if not root_path.is_dir():
        msg = f"tree root must be a directory: {root_path}"
        raise PackManifestError(msg)

    tree: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Sort names for deterministic traversal order.
        dirnames.sort()
        filenames.sort()
        for filename in filenames:
            full = Path(dirpath) / filename
            # Skip non-regular files (symlinks, devices, etc.) when hashing the
            # materialized tree. Their presence is an extraction concern, not a
            # hash concern.
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            rel = full.relative_to(root_path).as_posix()
            content_hash = hashlib.sha256(full.read_bytes()).hexdigest()
            tree[rel] = f"sha256:{content_hash}"

    sorted_tree = {path: tree[path] for path in sorted(tree)}
    canonical_bytes = dumps(sorted_tree)
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    return f"sha256:{digest}"


__all__ = [
    "LICENSE_INCOMPATIBLE_REASON",
    "LICENSE_UNKNOWN_REASON",
    "PACK_INTEGRITY_FAILURE_REASON",
    "PACK_MANIFEST_SCHEMA_VERSION",
    "PLATFORM_UNSUPPORTED_REASON",
    "LicenseError",
    "LicenseSpec",
    "PackManifestError",
    "PlatformSpec",
    "ProbesSpec",
    "ResourcePackManifest",
    "SourceSpec",
    "build_manifest",
    "compute_tree_sha256",
]
