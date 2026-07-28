"""PilotSpec/v1 loader, freezer, and honesty guards (WP-G60).

This module is the typed Python surface over the ``PilotSpec/v1`` JSON Schema
(see ``src/srl/contracts/schemas/v1/pilot-spec.json``). It does three things:

1. **Load** a spec from a JSON document (file or already-parsed object),
   validating it against the schema and enforcing the two const-false safety
   invariants in Python (defense in depth with the schema's ``const`` keywords).
2. **Freeze** a spec to its canonical bytes and content-addressed ``pilot_id``
   (``sha256:`` over the canonical encoding WITHOUT the ``pilot_id`` field),
   mirroring the self-hash-free content-addressing pattern used by the run
   request and plan identities.
3. **Guard** against prospective-holdout materialization: any field name or
   value pattern that indicates a holdout is being materialized is rejected as
   a contract violation (a STOP_INTEGRITY-style guard, surfaced with fail
   reason ``CONTRACT_INVALID`` and an explicit invariant name).

The two const-false invariants
------------------------------
A ``PilotSpec/v1`` pins three booleans to ``false`` as ``const``:

- ``status_promotion_allowed`` — a pilot cannot promote a claim's status;
- ``prospective_holdout_materialization_allowed`` — a pilot cannot authorize
  materializing a prospective holdout;
- ``grants_authority`` — a pilot is a description, not an authority.

The first and third are enforced at the schema layer (``const: false``); this
module re-checks them in Python so a caller that builds a spec dict directly
(sans schema) still hits the invariant. The schema already rejects a ``true``
value, but the Python guard makes the invariant explicit and testable in
insolation.

The holdout guard
-----------------
The schema pins ``prospective_holdout_materialization_allowed`` to ``false``,
but a spec could also *encode* a holdout materialization intent through other
field names or values (e.g. a ``holdout_materialized: true`` marker, or a
``note`` describing prospective data collection). The holdout guard scans the
spec recursively for such markers and rejects them with the
``prospective_holdout_materialization`` invariant. This is a STOP_INTEGRITY-
style guard: the prospective holdout is the integrity boundary of a
retrospective pilot, and materializing it would cross that boundary.

Content addressing
------------------
:func:`freeze_spec` returns the canonical bytes; :func:`pilot_id` returns the
content-addressed id. The id is computed over the canonical encoding of the
spec WITHOUT the ``pilot_id`` field (the standard self-hash-free pattern), so
two independent agents that author the same pilot compute the same id.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import IO, Any, Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.schema import validate as schema_validate

# The schema name this module validates against. Pinned so a typo fails loudly.
PILOT_SPEC_SCHEMA_NAME: Final[str] = "PilotSpec"
PILOT_SPEC_SCHEMA_VERSION: Final[str] = "PilotSpec/v1"

# The canonical fail reason for spec-structural failures (schema violation,
# const-false violation, holdout materialization). All are CONTRACT_INVALID
# (class ``contract``, ``hard_stop=false``).
PILOT_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# The two const-false safety fields a pilot must pin. The third
# (``grants_authority``) is enforced by the schema's ``const: false`` and by
# the generic receipt-invariants family; the two below are the pilot-specific
# honesty consts this module guards explicitly.
_CONST_FALSE_FIELDS: Final[tuple[str, ...]] = (
    "status_promotion_allowed",
    "prospective_holdout_materialization_allowed",
)

#: The field carrying the spec's own content-addressed identity. Excluded
#: from the freeze body so the id is not a self-hash (mirrors request_id /
#: plan_id / object_id).
PILOT_ID_FIELD: Final[str] = "pilot_id"

# ---------------------------------------------------------------------------
# Holdout-marker detection.
#
# A retrospective pilot reads ALREADY-EXTANT data. Materializing a prospective
# holdout (data held out for out-of-sample validation that does not yet exist
# at authoring time) is a separate authority path this codebase does not
# provide. The schema pins the dedicated boolean to false; this guard catches
# holdout intent encoded through OTHER field names or values.
#
# The matchers are deliberately conservative: they key off unambiguous
# markers (field names asserting a holdout was materialized, or value strings
# naming prospective collection), not off the legitimate
# ``prospective_holdout_materialization_allowed: false`` const itself. The
# legitimate const is allowed; an affirmative holdout marker is not.
# ---------------------------------------------------------------------------

# Field names whose PRESENCE asserts a prospective holdout was materialized or
# is requested. Matched case-insensitively against every key in the spec,
# recursively, EXCEPT the known safety-const fields (see _ALLOWED_HOLDOUT_KEYS)
# which legitimately name the holdout boundary and pin it to false.
#
# An affirmative marker is a field that names a holdout WITHOUT the
# ``..._allowed`` safety-const suffix: e.g. ``holdout_materialized``,
# ``materialized_holdout``, ``holdout_collected``. The presence of any such
# field is the marker (a retrospective pilot should not name a materialized
# holdout at all).
_HOLDOUT_FIELD_NAME_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # "holdout_materialized" or "holdout_materialization" (not the _allowed form).
    re.compile(r"holdout[_-]materializ(?:ed|ation)\b", re.IGNORECASE),
    # "materialized_holdout" / "materialization_holdout" (reversed word order).
    re.compile(r"materializ(?:ed|ation)[_-]holdout\b", re.IGNORECASE),
    # "holdout_collected" / "holdout_fetched" (a holdout being pulled).
    re.compile(r"holdout[_-](?:collected|fetched|pulled|drawn)\b", re.IGNORECASE),
)

# Known field names that legitimately name the prospective-holdout boundary and
# pin it to false. These are EXCLUDED from the field-name marker scan so the
# pinned safety const is not mistaken for an affirmative marker.
_ALLOWED_HOLDOUT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "prospective_holdout_materialization_allowed",
        "status_promotion_allowed",
    }
)

# Value strings (matched against string values only) that name prospective
# holdout collection / materialization. Matched case-insensitively as a
# substring so a free-form note or scope string cannot smuggle it through.
_HOLDOUT_VALUE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"materializ(?:e|ed|ation)\s+(?:a\s+)?prospective\s+holdout", re.IGNORECASE),
    re.compile(r"prospective\s+holdout\s+(?:materializ|collect|fetch|pull)", re.IGNORECASE),
    re.compile(r"holdout\s+(?:was\s+)?materialized", re.IGNORECASE),
)

#: The invariant name surfaced when a holdout marker is detected. Named so a
#: gate or test can assert against it.
HOLDOUT_INVARIANT: Final[str] = "prospective_holdout_materialization"

#: The invariant name surfaced when a const-false field is violated.
CONST_FALSE_INVARIANT: Final[str] = "pilot_safety_const"


class PilotSpecError(ContractError):
    """Raised when a ``PilotSpec/v1`` fails structural or honesty validation.

    Attributes
    ----------
    invariant:
        The named invariant that failed: ``pilot_safety_const`` for a
        const-false violation, ``prospective_holdout_materialization`` for a
        detected holdout marker, or empty for a bare schema violation.
    """

    def __init__(
        self,
        message: str,
        *,
        invariant: str = "",
        fail_reason: str = PILOT_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.invariant: Final[str] = invariant


def _is_bool_true(value: Any) -> bool:
    """Return True iff ``value`` is exactly the bool ``True`` (not 1, not truthy)."""
    # Guard against the int/bool conflation: in Python ``True == 1``, but a
    # safety const set to ``1`` is a distinct (and already schema-rejected)
    # shape. We check the exact bool True here for the Python defense-in-depth.
    return value is True


def _validate_const_false(spec: dict[str, Any]) -> None:
    """Enforce the two const-false safety invariants in Python.

    The schema already pins these as ``const: false``; this re-checks them so
    a caller that builds a spec dict directly (bypassing the schema) still
    hits the invariant, and so the gate can assert the invariant name.
    """
    for field in _CONST_FALSE_FIELDS:
        value = spec.get(field)
        if _is_bool_true(value):
            msg = (
                f"PilotSpec field {field!r} is {value!r}; a pilot must pin it "
                f"to false (a pilot cannot promote status, materialize a "
                f"prospective holdout, or grant authority)"
            )
            raise PilotSpecError(msg, invariant=CONST_FALSE_INVARIANT)


def _field_name_finding(key: Any, child_path: str) -> str | None:
    """Return a finding string if ``key`` is an affirmative holdout field name.

    The known safety-const fields (which legitimately name the boundary and
    pin it to false) are excluded. Returns None if ``key`` is clean.
    """
    if not isinstance(key, str) or key in _ALLOWED_HOLDOUT_KEYS:
        return None
    for pattern in _HOLDOUT_FIELD_NAME_PATTERNS:
        if pattern.search(key):
            return f"holdout-indicating field name {key!r} at {child_path!r}"
    return None


def _scan_for_holdout_markers(node: Any, path: str) -> list[str]:
    """Recursively collect holdout-marker findings in ``node``.

    Returns a list of human-readable findings (one per marker). Empty list
    means no marker found. ``path`` is a dotted/bracketed JSON-pointer-style
    path used only for the finding message.
    """
    findings: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            # Field-name matchers: the PRESENCE of an affirmative holdout field
            # is the marker. The known safety-const fields are excluded inside
            # _field_name_finding.
            finding = _field_name_finding(key, child_path)
            if finding is not None:
                findings.append(finding)
            findings.extend(_scan_for_holdout_markers(value, child_path))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            child_path = f"{path}[{idx}]"
            findings.extend(_scan_for_holdout_markers(item, child_path))
    elif isinstance(node, str):
        for pattern in _HOLDOUT_VALUE_PATTERNS:
            if pattern.search(node):
                findings.append(f"holdout-indicating value at {path!r}")
                break
    return findings


def validate_holdout_free(spec: dict[str, Any]) -> None:
    """Reject any field/value pattern indicating prospective holdout materialization.

    A retrospective pilot reads already-extant data. Any marker indicating a
    prospective holdout is being materialized (a field name asserting a
    holdout, or a value string naming prospective holdout collection) is a
    contract violation: it would cross the integrity boundary between a
    retrospective analysis and prospective data collection.

    The legitimate ``prospective_holdout_materialization_allowed: false`` const
    is NOT a marker — it is the pinned safety const, and its value is false.
    This function catches holdout intent encoded through OTHER names/values.

    Raises
    ------
    PilotSpecError
        With invariant ``prospective_holdout_materialization`` if any marker
        is found. The message lists the findings.
    """
    findings = _scan_for_holdout_markers(spec, "")
    if findings:
        msg = (
            "PilotSpec encodes a prospective-holdout materialization marker, "
            "which crosses the retrospective/prospective integrity boundary "
            f"({HOLDOUT_INVARIANT}): {'; '.join(findings)}"
        )
        raise PilotSpecError(msg, invariant=HOLDOUT_INVARIANT)


def _enforce_all_invariants(spec: dict[str, Any]) -> None:
    """Run the schema validation + the two Python honesty guards."""
    schema_validate(spec, PILOT_SPEC_SCHEMA_NAME)
    _validate_const_false(spec)
    validate_holdout_free(spec)


def load_pilot_spec(file: IO[str] | Path | str) -> dict[str, Any]:
    """Load and validate a ``PilotSpec/v1`` from a JSON source.

    Parameters
    ----------
    file:
        A JSON source: an open text file handle, a :class:`pathlib.Path`, or a
        JSON string. The contents must be a JSON object that validates against
        ``PilotSpec/v1`` and satisfy the two const-false invariants and the
        holdout guard.

    Returns
    -------
    dict[str, Any]
        The validated spec (the parsed dict). The caller owns the returned
        reference; this function does not memoize.

    Raises
    ------
    PilotSpecError
        With invariant ``pilot_safety_const`` if a const-false field is true;
        with invariant ``prospective_holdout_materialization`` if a holdout
        marker is found; or with no invariant (bare CONTRACT_INVALID) if the
        spec fails the schema.
    ContractError
        If the source cannot be read or parsed as canonical JSON.
    """
    if isinstance(file, Path):
        text = file.read_text(encoding="utf-8")
    elif isinstance(file, str):
        text = file
    else:
        # Treat as a readable text stream (IO[str]).
        text = file.read()
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"PilotSpec source is not valid JSON: {exc}"
        raise PilotSpecError(msg) from exc
    if not isinstance(spec, dict):
        msg = f"PilotSpec must be a JSON object, got {type(spec).__name__}"
        raise PilotSpecError(msg)
    _enforce_all_invariants(spec)
    return spec


def freeze_spec(spec: dict[str, Any]) -> bytes:
    """Return the canonical frozen bytes of ``spec``.

    The frozen bytes are the canonical JSON encoding (sorted keys, compact
    separators, UTF-8, no NaN/Infinity, trailing newline) of the WHOLE spec
    INCLUDING its ``pilot_id``. Two specs that are byte-identical after
    canonicalization are the same pilot.

    This function does NOT re-validate the spec; callers that need validation
    use :func:`load_pilot_spec` or :func:`_enforce_all_invariants`. It exists
    so a gate can assert deterministic freezing independent of validation.

    Raises
    ------
    ContractError
        If ``spec`` cannot be canonicalized (propagated from
        :func:`srl.contracts.canonical.dumps`).
    """
    return dumps(spec)


def pilot_id(spec: dict[str, Any]) -> str:
    """Recompute the ``pilot_id`` of ``spec`` (sha256 over canonical bytes, no id).

    The id is ``"sha256:"`` + the SHA-256 hex of the canonical encoding of the
    spec WITHOUT its ``pilot_id`` field (the self-hash-free pattern). Mirrors
    :func:`srl.planning.request.request_id` and
    :func:`srl.planning.planner.plan_id`.

    Raises
    ------
    ContractError
        If the body cannot be canonicalized.
    """
    body = {k: v for k, v in spec.items() if k != PILOT_ID_FIELD}
    digest = hashlib.sha256(dumps(body)).hexdigest()
    return "sha256:" + digest


def freeze_and_id(spec: dict[str, Any]) -> tuple[bytes, str]:
    """Return both the canonical frozen bytes and the recomputed ``pilot_id``.

    Convenience for a gate that wants both: validates the spec is
    canonicalizable and reports the recomputed id so a caller can assert it
    matches the spec's stored ``pilot_id`` field (determinism check).
    """
    return freeze_spec(spec), pilot_id(spec)


__all__ = [
    "CONST_FALSE_INVARIANT",
    "HOLDOUT_INVARIANT",
    "PILOT_FAIL_REASON",
    "PILOT_ID_FIELD",
    "PILOT_SPEC_SCHEMA_NAME",
    "PILOT_SPEC_SCHEMA_VERSION",
    "PilotSpecError",
    "freeze_and_id",
    "freeze_spec",
    "load_pilot_spec",
    "pilot_id",
    "validate_holdout_free",
]
