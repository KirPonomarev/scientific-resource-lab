"""CapabilityCatalog/v1: the in-repo map of profiles to (future) adapters.

The catalog is the deterministic, content-addressed table the router consults
to decide, for each capability profile, whether an adapter is available. It is
the *only* place a profile's adapter availability lives; the router never
hard-codes an adapter id.

The shipped catalog (``catalog_data.json``) marks every adapter ``future`` or
``remote_required`` because **no scientific backend ships in this codebase**.
This is load-bearing: the router MUST produce ``WAIT_CAPABILITY`` for every
applicable profile (absence of an adapter is an honest wait, never a silent
fallback to a local substitute). A future WP that lands a real adapter flips
the catalog entry to ``available``; until then, every applicable profile waits.

Determinism
-----------
The catalog document is canonical JSON (sorted keys, compact separators, UTF-8,
trailing newline). Its ``catalog_digest`` is ``sha256:`` + the SHA-256 of the
canonical bytes of the document WITHOUT the ``catalog_digest`` field. Two
processes loading the same ``catalog_data.json`` compute the same digest; the
planner threads this digest into the plan as ``catalog_hash`` so a re-plan
after a catalog change is detectable.
"""

from __future__ import annotations

import json
from copy import deepcopy
from importlib import resources
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id
from srl.planning.profiles import PROFILE_NAMES

# The catalog document's schema-version anchor.
_CATALOG_V1: Final[str] = "CapabilityCatalog/v1"

# The availability states a catalog entry may carry.
#   available       — a local adapter is present and may run.
#   future          — no adapter yet; an honest WAIT_CAPABILITY.
#   remote_required — the capability can ONLY run on a remote executor; NEVER
#                     falls back to local (WAIT_CAPABILITY even if a local
#                     adapter were named — the router refuses to substitute).
AVAILABILITY_STATES: Final[frozenset[str]] = frozenset({"available", "future", "remote_required"})

# The typed fail reason for a catalog-structural violation.
CATALOG_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Constants used by the shipped catalog-data file path.
_CATALOG_PACKAGE: Final[str] = "srl.planning"
_CATALOG_DATA_FILE: Final[str] = "catalog_data.json"


class CatalogError(ContractError):
    """Raised when a capability catalog document is malformed.

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``).
    """


class CapabilityEntry:
    """One catalog entry: a profile -> (adapter_id, availability) binding.

    Attributes
    ----------
    capability_id:
        The catalog capability identifier (e.g. ``cap.geometry_tda``).
    profile:
        The profile name this entry binds (one of the 15).
    adapter_id:
        The logical adapter identifier (e.g. ``ripser``), or ``None`` if no
        adapter is named yet.
    availability:
        ``available``, ``future``, or ``remote_required``.
    """

    __slots__ = ("adapter_id", "availability", "capability_id", "profile")

    def __init__(
        self,
        *,
        capability_id: str,
        profile: str,
        adapter_id: str | None,
        availability: str,
    ) -> None:
        if not isinstance(capability_id, str) or not capability_id:
            msg = "capability_id must be a non-empty string"
            raise CatalogError(msg)
        if profile not in PROFILE_NAMES:
            msg = f"catalog entry profile {profile!r} must be one of {sorted(PROFILE_NAMES)}"
            raise CatalogError(msg)
        if adapter_id is not None and (not isinstance(adapter_id, str) or not adapter_id):
            msg = "adapter_id must be a non-empty string or null"
            raise CatalogError(msg)
        if availability not in AVAILABILITY_STATES:
            msg = f"availability {availability!r} must be one of {sorted(AVAILABILITY_STATES)}"
            raise CatalogError(msg)
        self.capability_id: Final[str] = capability_id
        self.profile: Final[str] = profile
        self.adapter_id: Final[str | None] = adapter_id
        self.availability: Final[str] = availability

    def to_dict(self) -> dict[str, Any]:
        """Return the wire dict form of this entry (canonical-JSON-ready)."""
        return {
            "capability_id": self.capability_id,
            "profile": self.profile,
            "adapter_id": self.adapter_id,
            "availability": self.availability,
        }


def _validate_catalog_doc(doc: Any) -> dict[str, Any]:
    """Validate the raw catalog document shape and return it (checked, not mutated).

    Raises
    ------
    CatalogError
        If the document is not an object, has the wrong schema_version, or its
        capabilities array is malformed (missing keys, bad enum, unknown
        profile, duplicate profile).
    """
    if not isinstance(doc, dict):
        msg = f"catalog document must be an object, got {type(doc).__name__}"
        raise CatalogError(msg)
    if doc.get("schema_version") != _CATALOG_V1:
        msg = f"catalog schema_version must be {_CATALOG_V1!r}, got {doc.get('schema_version')!r}"
        raise CatalogError(msg)
    capabilities = doc.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        msg = "catalog 'capabilities' must be a non-empty array"
        raise CatalogError(msg)
    seen_profiles: set[str] = set()
    for entry in capabilities:
        if not isinstance(entry, dict):
            msg = f"catalog entry must be an object, got {type(entry).__name__}"
            raise CatalogError(msg)
        for key in ("capability_id", "profile", "adapter_id", "availability"):
            if key not in entry:
                msg = f"catalog entry missing key {key!r}"
                raise CatalogError(msg)
        # Construct CapabilityEntry to validate fields (raises CatalogError).
        ce = CapabilityEntry(
            capability_id=entry["capability_id"],
            profile=entry["profile"],
            adapter_id=entry["adapter_id"],
            availability=entry["availability"],
        )
        if ce.profile in seen_profiles:
            msg = f"catalog has duplicate entry for profile {ce.profile!r}"
            raise CatalogError(msg)
        seen_profiles.add(ce.profile)
    return doc


def catalog_digest(doc: dict[str, Any]) -> str:
    """Compute the ``catalog_digest``: sha256 over the canonical bytes of ``doc``.

    Computed over the catalog document WITHOUT the ``catalog_digest`` field (so
    the digest is idempotent: calling this on a doc with or without the field
    yields the same value). The document is validated first (defense in depth).
    """
    validated = _validate_catalog_doc(doc)
    body = {k: v for k, v in validated.items() if k != "catalog_digest"}
    return object_id(body)


class CapabilityCatalog:
    """A loaded, validated, content-addressed capability catalog.

    Build with :func:`load_default_catalog` (the shipped catalog) or
    :func:`load_catalog` (a custom document).

    Attributes
    ----------
    digest:
        The ``catalog_digest`` (sha256 over the canonical catalog bytes).
    entries:
        A dict of profile name -> :class:`CapabilityEntry`.
    """

    __slots__ = ("digest", "doc", "entries")

    def __init__(self, doc: dict[str, Any]) -> None:
        validated = _validate_catalog_doc(doc)
        # Deep-copy so callers cannot mutate the catalog after digest.
        self.doc: Final[dict[str, Any]] = deepcopy(validated)
        self.entries: Final[dict[str, CapabilityEntry]] = {
            entry["profile"]: CapabilityEntry(
                capability_id=entry["capability_id"],
                profile=entry["profile"],
                adapter_id=entry["adapter_id"],
                availability=entry["availability"],
            )
            for entry in validated["capabilities"]
        }
        self.digest: Final[str] = object_id(
            {k: v for k, v in validated.items() if k != "catalog_digest"}
        )

    def entry_for(self, profile: str) -> CapabilityEntry | None:
        """Return the catalog entry for ``profile``, or ``None`` if absent."""
        return self.entries.get(profile)

    def capability_id_for(self, profile: str) -> str:
        """Return the capability_id for ``profile``.

        If the catalog has no entry for the profile (it is unknown to the
        catalog), returns the synthesized id ``cap.<profile>`` so the router
        can still emit a WAIT_CAPABILITY step with a stable capability_id.
        """
        entry = self.entries.get(profile)
        if entry is not None:
            return entry.capability_id
        return f"cap.{profile}"

    def is_available(self, profile: str) -> bool:
        """Return True iff the profile has an ``available`` local adapter."""
        entry = self.entries.get(profile)
        return entry is not None and entry.availability == "available"

    def is_remote_required(self, profile: str) -> bool:
        """Return True iff the profile is ``remote_required`` (never falls back to local)."""
        entry = self.entries.get(profile)
        return entry is not None and entry.availability == "remote_required"

    def to_dict(self) -> dict[str, Any]:
        """Return the wire dict form (with catalog_digest filled in)."""
        out = deepcopy(self.doc)
        out["catalog_digest"] = self.digest
        return out


def load_default_catalog() -> CapabilityCatalog:
    """Load and return the shipped default catalog (``catalog_data.json``).

    Reads the packaged JSON via :mod:`importlib.resources` so the catalog a
    running program uses is the one that shipped with the installed wheel —
    never a loose local file.

    Raises
    ------
    CatalogError
        If the packaged file is missing, malformed JSON, or fails validation.
    """
    try:
        raw = (
            resources.files(_CATALOG_PACKAGE)
            .joinpath(_CATALOG_DATA_FILE)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        msg = f"could not read packaged catalog {_CATALOG_DATA_FILE!r}: {exc}"
        raise CatalogError(msg) from exc

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"packaged catalog is not valid JSON: {exc}"
        raise CatalogError(msg) from exc
    return load_catalog(doc)


def load_catalog(doc: dict[str, Any]) -> CapabilityCatalog:
    """Load and validate a custom catalog document.

    Raises
    ------
    CatalogError
        If the document is malformed.
    """
    return CapabilityCatalog(doc)


__all__ = [
    "AVAILABILITY_STATES",
    "CATALOG_FAIL_REASON",
    "CapabilityCatalog",
    "CapabilityEntry",
    "CatalogError",
    "catalog_digest",
    "load_catalog",
    "load_default_catalog",
]
