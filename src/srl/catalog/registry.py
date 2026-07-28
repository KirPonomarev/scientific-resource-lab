"""Capability registry for SRL scientific catalog snapshots.

A :class:`CapabilityRegistryEntry` is the immutable identity of a capability:
what profile it serves, which adapter backs it (if any), the admitted pack that
proves it (if any), declared platforms, measured resources, license, provenance,
and admission stage. The registry intentionally does **not** store location or
availability: those are dynamic state attached to a snapshot separately. A
registry entry existing never implies the capability is ready to run.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from importlib import resources
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import validate_object_id
from srl.planning.profiles import PROFILE_NAMES

# Schema identity for the seed document. Bumped only on a contract change.
_REGISTRY_SEED_SCHEMA_VERSION: Final[str] = "CapabilityRegistrySeed/v1"

# Package constants for importlib.resources access to the packaged seed JSON.
_CATALOG_PACKAGE: Final[str] = "srl.catalog"
_CATALOG_SEED_FILE: Final[str] = "seed_entries.json"

# Admission stage names mirror the WP-C23 pipeline stages plus the honest
# sentinel for entries that have no admitted pack yet.
ADMISSION_STAGES: Final[tuple[str, ...]] = (
    "DISCOVERED",
    "SOURCE_VERIFIED",
    "LICENSE_CLEARED",
    "LOCKED",
    "BUILT",
    "BYTE_VERIFIED",
    "RUNTIME_PROBED",
    "ACTUAL_COMPUTE_PROBED",
    "EXPERIMENTAL_ACCEPTED",
)
NOT_ADMITTED_STAGE: Final[str] = "not_admitted"

# Allowed platform identifiers. Kept in sync with srl.packs.manifest.
_OS_NAMES: Final[frozenset[str]] = frozenset({"linux", "macos"})
_ARCH_NAMES: Final[frozenset[str]] = frozenset({"x86_64", "arm64"})


class CatalogError(ContractError):
    """Raised when a catalog registry or snapshot violates its contract.

    Carries the typed fail reason ``CONTRACT_INVALID`` by default.
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


@dataclass(frozen=True, slots=True)
class PlatformSpec:
    """One declared platform for a capability.

    A plain immutable container; structural validation lives in
    :func:`_build_platform` so it mirrors the :mod:`srl.packs.manifest` pattern
    (plain dataclass + builder over raw input).
    """

    os: str
    arch: str
    abi: str | None


@dataclass(frozen=True, slots=True)
class MeasuredResources:
    """Measured resource footprint of an admitted pack.

    ``expanded_bytes`` and ``rss_bytes`` are integers. ``wall_seconds`` is a
    non-negative number (int or float) because sub-second measurements are valid.
    Validation lives in :func:`_build_measured_resources`.
    """

    expanded_bytes: int
    rss_bytes: int
    wall_seconds: int | float


@dataclass(frozen=True, slots=True)
class Provenance:
    """Provenance of the upstream source that produced the admitted pack.

    Validation lives in :func:`_build_provenance`.
    """

    source_url: str | None
    source_sha256: str | None


@dataclass(frozen=True, slots=True)
class CapabilityRegistryEntry:
    """Immutable identity of one capability in the catalog.

    A plain immutable container. Structural validation is performed by the
    builders (:func:`_build_entry_from_raw` over seed JSON;
    :func:`build_entry` for programmatic construction), mirroring the
    :mod:`srl.packs.manifest` pattern (plain dataclass + builder). The
    dataclass field annotations are the type contract; direct construction with
    well-typed values is permitted.

    Attributes
    ----------
    capability_id:
        Stable capability identifier (e.g. ``cap.geometry_tda``).
    profile:
        One of the 15 B14 capability profile names.
    adapter_id:
        Logical adapter identifier, or ``None`` if no adapter is named yet.
    pack_manifest_digest:
        ``sha256:<hex>`` digest of the admitted pack manifest, or ``None``.
    platforms:
        Tuple of declared platforms (may be empty for future capabilities).
    measured_resources:
        Resource footprint measurement, or ``None`` if not measured.
    license_spdx:
        SPDX license identifier asserted for the capability/pack. ``NOASSERTION``
        is used for seed entries where no pack has been admitted.
    provenance:
        Upstream source provenance (url and content digest), both nullable.
    admission_stage:
        Either ``'not_admitted'`` or one of the WP-C23 :data:`ADMISSION_STAGES`.
    """

    capability_id: str
    profile: str
    adapter_id: str | None
    pack_manifest_digest: str | None
    platforms: tuple[PlatformSpec, ...]
    measured_resources: MeasuredResources | None
    license_spdx: str
    provenance: Provenance
    admission_stage: str

    def to_dict(self) -> dict[str, Any]:
        """Return the entry as a plain JSON-serializable dict."""
        measured: dict[str, Any] | None = None
        if self.measured_resources is not None:
            measured = {
                "expanded_bytes": self.measured_resources.expanded_bytes,
                "rss_bytes": self.measured_resources.rss_bytes,
                "wall_seconds": self.measured_resources.wall_seconds,
            }
        return {
            "capability_id": self.capability_id,
            "profile": self.profile,
            "adapter_id": self.adapter_id,
            "pack_manifest_digest": self.pack_manifest_digest,
            "platforms": [asdict(p) for p in self.platforms],
            "measured_resources": measured,
            "license_spdx": self.license_spdx,
            "provenance": asdict(self.provenance),
            "admission_stage": self.admission_stage,
        }


def _require_non_empty_str(value: Any, field: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise CatalogError."""
    if not isinstance(value, str) or value == "":
        msg = f"{field} must be a non-empty string, got {value!r}"
        raise CatalogError(msg)
    return value


def _validate_capability_id(value: Any) -> str:
    """Validate the capability_id field (non-empty string)."""
    return _require_non_empty_str(value, "capability_id")


def _validate_profile(value: Any) -> str:
    """Validate the profile field (one of the 15 B14 names)."""
    name = _require_non_empty_str(value, "profile")
    if name not in PROFILE_NAMES:
        msg = f"profile {name!r} must be one of {sorted(PROFILE_NAMES)}"
        raise CatalogError(msg)
    return name


def _validate_adapter_id(value: Any) -> str | None:
    """Validate the adapter_id field (non-empty string or None)."""
    if value is None:
        return None
    return _require_non_empty_str(value, "adapter_id")


def _validate_optional_digest(value: Any, field: str) -> str | None:
    """Validate an optional ``sha256:<hex>`` digest field."""
    if value is None:
        return None
    try:
        return validate_object_id(value)
    except Exception as exc:
        msg = f"{field} {value!r} is not a valid object id"
        raise CatalogError(msg) from exc


def _validate_platforms(value: Any) -> tuple[PlatformSpec, ...]:
    """Validate the platforms field (a tuple of :class:`PlatformSpec`)."""
    if not isinstance(value, tuple):
        msg = f"platforms must be a tuple, got {type(value).__name__}"
        raise CatalogError(msg)
    validated: list[PlatformSpec] = []
    for i, platform in enumerate(value):
        if not isinstance(platform, PlatformSpec):
            msg = f"platforms[{i}] must be a PlatformSpec, got {type(platform).__name__}"
            raise CatalogError(msg)
        if platform.os not in _OS_NAMES:
            msg = f"platforms[{i}].os {platform.os!r} must be one of {sorted(_OS_NAMES)}"
            raise CatalogError(msg)
        if platform.arch not in _ARCH_NAMES:
            msg = f"platforms[{i}].arch {platform.arch!r} must be one of {sorted(_ARCH_NAMES)}"
            raise CatalogError(msg)
        validated.append(platform)
    return tuple(validated)


def _validate_measured_resources(value: Any) -> MeasuredResources | None:
    """Validate the measured_resources field."""
    if value is None:
        return None
    if not isinstance(value, MeasuredResources):
        msg = f"measured_resources must be a MeasuredResources or null, got {type(value).__name__}"
        raise CatalogError(msg)
    if not isinstance(value.expanded_bytes, int) or isinstance(value.expanded_bytes, bool):
        msg = f"measured_resources.expanded_bytes must be an int, got {value.expanded_bytes!r}"
        raise CatalogError(msg)
    if value.expanded_bytes < 0:
        msg = f"measured_resources.expanded_bytes must be non-negative, got {value.expanded_bytes}"
        raise CatalogError(msg)
    if not isinstance(value.rss_bytes, int) or isinstance(value.rss_bytes, bool):
        msg = f"measured_resources.rss_bytes must be an int, got {value.rss_bytes!r}"
        raise CatalogError(msg)
    if value.rss_bytes < 0:
        msg = f"measured_resources.rss_bytes must be non-negative, got {value.rss_bytes}"
        raise CatalogError(msg)
    if not isinstance(value.wall_seconds, (int, float)) or isinstance(value.wall_seconds, bool):
        msg = (
            f"measured_resources.wall_seconds must be a number, "
            f"got {type(value.wall_seconds).__name__}"
        )
        raise CatalogError(msg)
    if value.wall_seconds < 0:
        msg = f"measured_resources.wall_seconds must be non-negative, got {value.wall_seconds}"
        raise CatalogError(msg)
    return value


def _validate_provenance(value: Any) -> Provenance:
    """Validate the provenance field.

    The ``Provenance`` dataclass annotations pin ``source_url`` to
    ``str | None`` and ``source_sha256`` to ``str | None``; construction from
    raw dicts is validated by :func:`_build_provenance`, so here we only check
    the type and the optional digest shape.
    """
    if not isinstance(value, Provenance):
        msg = f"provenance must be a Provenance, got {type(value).__name__}"
        raise CatalogError(msg)
    if value.source_sha256 is not None:
        try:
            validate_object_id(value.source_sha256)
        except Exception as exc:
            msg = f"provenance.source_sha256 {value.source_sha256!r} is not a valid object id"
            raise CatalogError(msg) from exc
    return value


def _validate_admission_stage(value: Any) -> str:
    """Validate the admission_stage field (a known stage or not_admitted)."""
    valid_stages = {*ADMISSION_STAGES, NOT_ADMITTED_STAGE}
    if value not in valid_stages:
        msg = f"admission_stage {value!r} must be one of {sorted(valid_stages)}"
        raise CatalogError(msg)
    return value  # type: ignore[no-any-return]


def build_entry(  # noqa: PLR0913 - mirrors the 9-field CapabilityRegistryEntry dataclass
    *,
    capability_id: Any,
    profile: Any,
    adapter_id: Any,
    pack_manifest_digest: Any,
    platforms: Any,
    measured_resources: Any,
    license_spdx: Any,
    provenance: Any,
    admission_stage: Any,
) -> CapabilityRegistryEntry:
    """Build and validate a :class:`CapabilityRegistryEntry`.

    Use this for programmatic construction (gate fixtures, tests). It validates
    every field and returns an immutable entry. Mirrors the
    :func:`srl.packs.manifest.build_manifest` pattern.

    Raises
    ------
    CatalogError
        With fail reason ``CONTRACT_INVALID`` if any field is malformed.
    """
    return CapabilityRegistryEntry(
        capability_id=_validate_capability_id(capability_id),
        profile=_validate_profile(profile),
        adapter_id=_validate_adapter_id(adapter_id),
        pack_manifest_digest=_validate_optional_digest(
            pack_manifest_digest, "pack_manifest_digest"
        ),
        platforms=_validate_platforms(platforms),
        measured_resources=_validate_measured_resources(measured_resources),
        license_spdx=_require_non_empty_str(license_spdx, "license_spdx"),
        provenance=_validate_provenance(provenance),
        admission_stage=_validate_admission_stage(admission_stage),
    )


def _validate_seed_doc(doc: Any) -> dict[str, Any]:
    """Validate the raw seed document shape and return it."""
    if not isinstance(doc, dict):
        msg = f"registry seed document must be an object, got {type(doc).__name__}"
        raise CatalogError(msg)
    if doc.get("schema_version") != _REGISTRY_SEED_SCHEMA_VERSION:
        msg = (
            f"registry seed schema_version must be {_REGISTRY_SEED_SCHEMA_VERSION!r}, "
            f"got {doc.get('schema_version')!r}"
        )
        raise CatalogError(msg)
    entries = doc.get("entries")
    if not isinstance(entries, list):
        msg = f"registry seed 'entries' must be an array, got {type(entries).__name__}"
        raise CatalogError(msg)
    return doc


def _build_platform(value: Any, field: str) -> PlatformSpec:
    """Build a PlatformSpec from a raw dict."""
    if not isinstance(value, dict):
        msg = f"{field} must be an object, got {type(value).__name__}"
        raise CatalogError(msg)
    required = {"os", "arch"}
    allowed = frozenset({*required, "abi"})
    actual = set(value.keys())
    missing = required - actual
    if missing:
        msg = f"{field} missing required key(s): {sorted(missing)}"
        raise CatalogError(msg)
    extra = actual - allowed
    if extra:
        msg = f"{field} has unexpected key(s): {sorted(extra)}"
        raise CatalogError(msg)
    abi = value.get("abi")
    if abi is not None and not isinstance(abi, str):
        msg = f"{field}.abi must be a string or null, got {type(abi).__name__}"
        raise CatalogError(msg)
    return PlatformSpec(os=value["os"], arch=value["arch"], abi=abi)


def _build_measured_resources(value: Any, field: str) -> MeasuredResources | None:
    """Build a MeasuredResources from a raw dict or None."""
    if value is None:
        return None
    if not isinstance(value, dict):
        msg = f"{field} must be an object or null, got {type(value).__name__}"
        raise CatalogError(msg)
    required = {"expanded_bytes", "rss_bytes", "wall_seconds"}
    missing = required - set(value.keys())
    if missing:
        msg = f"{field} missing required key(s): {sorted(missing)}"
        raise CatalogError(msg)
    return MeasuredResources(
        expanded_bytes=value["expanded_bytes"],
        rss_bytes=value["rss_bytes"],
        wall_seconds=value["wall_seconds"],
    )


def _build_provenance(value: Any, field: str) -> Provenance:
    """Build a Provenance from a raw dict."""
    if not isinstance(value, dict):
        msg = f"{field} must be an object, got {type(value).__name__}"
        raise CatalogError(msg)
    required = {"source_url", "source_sha256"}
    missing = required - set(value.keys())
    if missing:
        msg = f"{field} missing required key(s): {sorted(missing)}"
        raise CatalogError(msg)
    source_url = value["source_url"]
    if source_url is not None and not isinstance(source_url, str):
        msg = f"{field}.source_url must be a string or null, got {type(source_url).__name__}"
        raise CatalogError(msg)
    return Provenance(source_url=source_url, source_sha256=value["source_sha256"])


def _build_entry_from_raw(entry: Any) -> CapabilityRegistryEntry:
    """Build a validated :class:`CapabilityRegistryEntry` from a raw dict.

    Routes every field through :func:`build_entry` so raw-JSON construction and
    programmatic construction share one validation path.
    """
    if not isinstance(entry, dict):
        msg = f"seed entry must be an object, got {type(entry).__name__}"
        raise CatalogError(msg)
    required = {
        "capability_id",
        "profile",
        "adapter_id",
        "pack_manifest_digest",
        "platforms",
        "measured_resources",
        "license_spdx",
        "provenance",
        "admission_stage",
    }
    missing = required - set(entry.keys())
    if missing:
        msg = f"seed entry missing required key(s): {sorted(missing)}"
        raise CatalogError(msg)

    platforms_raw = entry["platforms"]
    if not isinstance(platforms_raw, list):
        msg = f"platforms must be an array, got {type(platforms_raw).__name__}"
        raise CatalogError(msg)
    platforms = tuple(_build_platform(p, f"platforms[{i}]") for i, p in enumerate(platforms_raw))
    measured = _build_measured_resources(entry["measured_resources"], "measured_resources")
    provenance = _build_provenance(entry["provenance"], "provenance")

    return build_entry(
        capability_id=entry["capability_id"],
        profile=entry["profile"],
        adapter_id=entry["adapter_id"],
        pack_manifest_digest=entry["pack_manifest_digest"],
        platforms=platforms,
        measured_resources=measured,
        license_spdx=entry["license_spdx"],
        provenance=provenance,
        admission_stage=entry["admission_stage"],
    )


def load_registry_seed() -> tuple[CapabilityRegistryEntry, ...]:
    """Load the packaged capability registry seed entries.

    Returns
    -------
    tuple[CapabilityRegistryEntry, ...]
        The 15 B14-derived seed entries, sorted by profile name.

    Raises
    ------
    CatalogError
        If the packaged seed file is missing, malformed JSON, or fails validation.
    """
    try:
        raw = (
            resources.files(_CATALOG_PACKAGE)
            .joinpath(_CATALOG_SEED_FILE)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        msg = f"could not read packaged registry seed {_CATALOG_SEED_FILE!r}: {exc}"
        raise CatalogError(msg) from exc

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"packaged registry seed is not valid JSON: {exc}"
        raise CatalogError(msg) from exc

    validated = _validate_seed_doc(doc)
    entries = tuple(_build_entry_from_raw(e) for e in validated["entries"])
    return tuple(sorted(entries, key=lambda e: e.capability_id))


def build_default_registry() -> tuple[CapabilityRegistryEntry, ...]:
    """Return the default capability registry entries.

    This is currently the packaged seed entries. Future work-packages may layer
    operator-local or network-discovered entries on top.
    """
    return load_registry_seed()


__all__ = [
    "ADMISSION_STAGES",
    "NOT_ADMITTED_STAGE",
    "CapabilityRegistryEntry",
    "CatalogError",
    "MeasuredResources",
    "PlatformSpec",
    "Provenance",
    "build_default_registry",
    "build_entry",
    "load_registry_seed",
]
