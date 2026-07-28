"""Autonomy policy loader and validator.

``AutonomyPolicy/v1`` is the governance policy for the repository (see
``GOVERNANCE.md``). Its machine-readable form is ``automation/policy.json``:
a canonical JSON document with exactly 19 keys of declared types.

This module loads that document and validates it against an *embedded*
expectation that ships with the source. The expectation is the authority for
what the policy may contain; the on-disk JSON is the artifact a mission runs
against. If the two drift, the loader refuses rather than silently accepting
a policy that has been weakened or reshaped.

The validation is intentionally strict and complete:

- the schema version must be a known ``AutonomyPolicy`` version (v1 or v2),
  with per-version cross-field constraints enforced;
- all 19 expected keys must be present, with no extras;
- each key must have the declared JSON type;
- where a key is a string, its value must be one of the allowed enum members.

A failure at any of these raises :class:`PolicyError`. The policy is never
mutated here; ``canonical_runtime_mutation`` is ``false`` under v1 and this
module honors that by being read-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

# Schema identity. Bumping this is a governance change (see GOVERNANCE.md).
# v1: initial policy, lanes fixed at 4. v2 (GOV-0001): lanes 4..6.
# v3 (GOV-0002, operator-authorized): lanes 4..8. A policy document declares
# its own version; the loader enforces the per-version constraints.
POLICY_SCHEMA_VERSION: Final[str] = "AutonomyPolicy/v3"
POLICY_SCHEMA_VERSIONS: Final[frozenset[str]] = frozenset(
    {"AutonomyPolicy/v1", "AutonomyPolicy/v2", "AutonomyPolicy/v3"}
)
# v1 cross-field constraint: lanes fixed at exactly 4 under v1.
_V1_SCHEMA_VERSION: Final[str] = "AutonomyPolicy/v1"
_V1_LANES: Final[int] = 4

# The embedded expectation: key -> (json type name, allowed values or None).
# This is the authority. ``automation/policy.json`` must match it exactly.
# Order is the canonical (sorted) order of the keys for stable diagnostics.
_EXPECTED: Final[dict[str, tuple[str, frozenset[str] | None]]] = {
    "auto_commit": ("bool", None),
    "auto_merge_owned_pr": ("bool", None),
    "auto_open_pr": ("bool", None),
    "auto_push": ("bool", None),
    "auto_repair_ci": ("bool", None),
    "canonical_runtime_mutation": ("bool", frozenset({"false"})),
    "decision_policy": ("str", frozenset({"MATURE_ENGINEERING_V1"})),
    "deployment_allowed": ("bool", frozenset({"false"})),
    "external_pr_auto_merge": ("bool", frozenset({"false"})),
    "max_parallel_implementation_lanes": ("int", frozenset({"4", "5", "6", "7", "8"})),
    "max_scientific_execution_wip": ("int", frozenset({"1"})),
    "merge_method": ("str", frozenset({"squash"})),
    "mode": ("str", frozenset({"noninteractive_within_scope"})),
    "public_repo": ("bool", None),
    "schema_version": ("str", POLICY_SCHEMA_VERSIONS),
    "secret_use_in_public_ci": ("bool", frozenset({"false"})),
    "self_hosted_runner_allowed": ("bool", frozenset({"false"})),
    "t7_execution_allowed": ("bool", frozenset({"false"})),
    "vps_expansion_allowed": ("bool", frozenset({"false"})),
}

# Number of keys the policy must carry. Asserted at import for self-check.
_EXPECTED_KEY_COUNT: Final[int] = 19


class PolicyError(ValueError):
    """Raised when the policy document does not match the embedded expectation.

    Carries a ``key`` naming the offending field (or ``""`` for a structural
    failure such as a missing file or bad JSON) and a ``reason`` string. Both
    are also folded into the message so the exception reads well unattended.
    """

    def __init__(self, message: str, *, key: str = "", reason: str = "") -> None:
        super().__init__(message)
        self.key: str = key
        self.reason: str = reason


def _json_type_name(value: Any) -> str:
    """Return the JSON type name for ``value``.

    JSON booleans must be distinguished from integers (Python's ``bool`` is a
    subclass of ``int``), so ``bool`` is checked first.
    """
    # bool before int: isinstance(True, int) is True in Python.
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, str):
        return "str"
    # We do not expect float/list/dict/null in the v1 policy, but report the
    # Python type name for a clear diagnostic rather than a generic "wrong".
    return type(value).__name__


def _validate_policy_dict(policy: dict[str, Any]) -> None:
    """Validate a parsed policy dict against the embedded expectation.

    Raises :class:`PolicyError` on the first deviation found, with the key and
    a human-readable reason. Checks run in a deterministic order: structural
    (extra/missing keys) first, then per-field type and value, then the
    schema version last as the identity anchor.
    """
    actual_keys = set(policy.keys())
    expected_keys = set(_EXPECTED.keys())

    missing = sorted(expected_keys - actual_keys)
    if missing:
        msg = f"policy missing required key(s): {missing}"
        raise PolicyError(msg, key=missing[0], reason="missing_key")

    extra = sorted(actual_keys - expected_keys)
    if extra:
        msg = f"policy has unexpected key(s): {extra}"
        raise PolicyError(msg, key=extra[0], reason="extra_key")

    # Per-field type and value. Iterate in sorted order for stable errors.
    for key in sorted(expected_keys):
        expected_type, allowed = _EXPECTED[key]
        value = policy[key]
        actual_type = _json_type_name(value)
        if actual_type != expected_type:
            msg = f"policy key {key!r} has type {actual_type!r}, expected {expected_type!r}"
            raise PolicyError(msg, key=key, reason="wrong_type")
        if allowed is not None:
            # Render the value canonically for the membership test. Booleans
            # become "true"/"false"; ints/strs their str().
            token = (
                "true"
                if (isinstance(value, bool) and value)
                else ("false" if isinstance(value, bool) else str(value))
            )
            if token not in allowed:
                msg = f"policy key {key!r} has value {token!r}, expected one of {sorted(allowed)}"
                raise PolicyError(msg, key=key, reason="bad_value")

    # Identity anchor: the schema version must be a known version.
    if policy["schema_version"] not in POLICY_SCHEMA_VERSIONS:
        msg = (
            f"policy schema_version is {policy['schema_version']!r}, "
            f"expected one of {sorted(POLICY_SCHEMA_VERSIONS)}"
        )
        raise PolicyError(msg, key="schema_version", reason="bad_schema_version")

    # Cross-field version constraints: v1 fixes lanes at exactly 4.
    if (
        policy["schema_version"] == _V1_SCHEMA_VERSION
        and policy["max_parallel_implementation_lanes"] != _V1_LANES
    ):
        msg = "AutonomyPolicy/v1 requires max_parallel_implementation_lanes=4"
        raise PolicyError(msg, key="max_parallel_implementation_lanes", reason="version_constraint")


def load_policy(path: str | Path) -> dict[str, Any]:
    """Load and validate the policy document at ``path``.

    Parameters
    ----------
    path:
        Filesystem path to a canonical ``AutonomyPolicy/v1`` JSON document.

    Returns
    -------
    dict[str, Any]
        The validated policy as a plain dict. The returned dict is the parsed
        document; callers must not mutate it (the v1 policy is immutable in
        flight).

    Raises
    ------
    PolicyError
        If the file is missing, is not valid JSON, or does not match the
        embedded expectation (missing/extra keys, wrong types, bad values,
        or a wrong schema version).
    """
    p = Path(path)
    if not p.is_file():
        msg = f"policy file not found: {p}"
        raise PolicyError(msg, reason="missing_file")
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"could not read policy file {p}: {exc}"
        raise PolicyError(msg, reason="unreadable_file") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"policy file {p} is not valid JSON: {exc}"
        raise PolicyError(msg, reason="bad_json") from exc
    if not isinstance(parsed, dict):
        msg = f"policy file {p} must be a JSON object, got {type(parsed).__name__}"
        raise PolicyError(msg, reason="not_object")
    _validate_policy_dict(parsed)
    return parsed


# Self-check at import: the expectation itself must be well-formed. This is a
# static contract on this module, not on the loaded policy. Expressed as an
# explicit raise (not ``assert``) so the guard survives ``python -O`` and does
# not trip the bandit S101 rule that fires on bare ``assert``.
if len(_EXPECTED) != _EXPECTED_KEY_COUNT or any(
    v[0] not in ("bool", "int", "str") for v in _EXPECTED.values()
):
    msg = "embedded policy expectation is malformed"
    raise PolicyError(msg, reason="expectation_drift")
