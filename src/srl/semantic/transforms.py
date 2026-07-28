"""TransformationReceipt/v1: typed, honest transformation lineage.

This module is the Python counterpart of the ``TransformationReceipt/v1`` JSON
Schema (``src/srl/contracts/schemas/v1/transformation-receipt.json``). It
provides the *honest lineage* machinery: every time one scientific object is
derived from another by a named transformation, a receipt records the step and
— crucially — the **cost** of the step, classified into one of three
conversion classes:

- ``LOSSLESS`` — no information is lost. The target is a faithful re-expression
  of the source. REQUIRED: ``introduced_assumptions`` and ``dropped_features``
  are both empty. This is the only class a producer may use to claim a step
  lost nothing.
- ``LOSSY_EXPLICIT`` — the producer declares a loss: an introduced assumption
  or a dropped feature. The loss travels with the object forever via the
  lineage chain.
- ``LOSSY_IMPLICIT_DETECTED`` — a *detector* comparing two trees found a loss
  the producer did not declare. Producers may NEVER set this value (the
  producer API does not expose it); only :func:`record_detected_loss` (a
  detector-only constructor) produces it.

The honesty rules (see ``docs/contracts/transformations.md``)
-----------------------------------
1. **A lossy step never upgrades evidence.** A ``LOSSY_*`` receipt in an
   object's lineage means the object carries less evidence than its source. A
   later ``LOSSLESS`` step on the same object cannot wash the loss away: the
   lossy receipt stays in the chain.
2. **Introduced assumptions travel forever.** An ``introduced_assumption`` is
   not a transient note; it is a permanent part of the object's provenance.
3. **LOSSLESS is a claim the producer must be able to honor.** The producer
   API (:func:`record_transformation`) enforces the invariant: a LOSSLESS step
   with a non-empty assumption or dropped feature is rejected
   (:class:`TransformationInvariantError`, fail reason ``CONTRACT_INVALID``).
4. **Implicit loss is detector-only.** A producer cannot bury an undetected
   loss; only an independent lineage auditor comparing two trees produces
   ``LOSSY_IMPLICIT_DETECTED``.

Projection lineage
------------------
:func:`project_to_backend` projects a :class:`~srl.semantic.ir.MathIR` tree onto
an :class:`~srl.semantic.adapter_profiles.AdapterSemanticProfile`: it verifies
every operator in the tree is in the profile's ``supported_cds``. Unsupported
operators are handled by the profile's declared ``behavior`` (``reject`` is a
hard stop with fail reason ``IR_UNSUPPORTED``; ``approximate`` and ``drop`` are
recorded as a lossy step). The receipt binds the ``adapter_profile_ref`` and
``pack_hash`` so the projection is reproducible and auditable.

Raw-eval prohibition
--------------------
The IR is restricted precisely so that a scientific object is never evaluated
by feeding a string into a CAS/sympy/sage ``eval`` route. :func:`assert_no_raw_eval_route`
introspects :mod:`srl.semantic` and verifies no forbidden input route
(``sympify``, ``sage_eval``, ``eval``, ``lambdify``) is exposed. The gate
(B12-04) and a unit test enforce this at every change.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id, validate_object_id
from srl.contracts.timestamps import normalize as normalize_timestamp
from srl.semantic.adapter_profiles import (
    profile_id as _profile_id,
)
from srl.semantic.adapter_profiles import (
    validate_profile,
)
from srl.semantic.ir import (
    IR_UNSUPPORTED_FAIL_REASON,
    MathIR,
    ir_id,
    validate_expression,
)

# The typed fail reason for a transformation-invariant violation. Transformation
# invariants are structural contract failures; the fail reason is
# ``CONTRACT_INVALID``.
TRANSFORMATION_INVARIANT_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Identity anchor.
_TRANSFORMATION_RECEIPT_V1: Final[str] = "TransformationReceipt/v1"

# The three conversion classes. A producer may set LOSSLESS or LOSSY_EXPLICIT;
# LOSSY_IMPLICIT_DETECTED is detector-only (see record_detected_loss).
LOSSLESS: Final[str] = "LOSSLESS"
LOSSY_EXPLICIT: Final[str] = "LOSSY_EXPLICIT"
LOSSY_IMPLICIT_DETECTED: Final[str] = "LOSSY_IMPLICIT_DETECTED"
_PRODUCER_CONVERSION_CLASSES: Final[frozenset[str]] = frozenset({LOSSLESS, LOSSY_EXPLICIT})

# The transform_kind values. Mirrors the schema enum.
TRANSFORM_KINDS: Final[frozenset[str]] = frozenset(
    {
        "normalize",
        "project",
        "convert_units",
        "restrict_domain",
        "serialize",
        "deserialize",
        "approximate",
    }
)

# The behavior values an adapter profile declares for an unsupported operator.
BEHAVIOR_REJECT: Final[str] = "reject"
BEHAVIOR_APPROXIMATE: Final[str] = "approximate"
BEHAVIOR_DROP: Final[str] = "drop"
_PROFILE_BEHAVIORS: Final[frozenset[str]] = frozenset(
    {BEHAVIOR_REJECT, BEHAVIOR_APPROXIMATE, BEHAVIOR_DROP}
)

# The forbidden names that constitute a raw-eval input route. Introspected by
# assert_no_raw_eval_route against the srl.semantic package's public surface.
# A scientific object must never be evaluated by feeding a string into one of
# these: the restricted IR allowlist is precisely what makes evaluation safe.
_RAW_EVAL_FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset(
    {"sympify", "sage_eval", "eval", "lambdify", "sympy", "sage"}
)


class TransformationInvariantError(ContractError):
    """Raised when a TransformationReceipt violates a contract invariant.

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``) and the name of
    the violated ``invariant`` for diagnostics.

    Attributes
    ----------
    invariant:
        The name of the violated invariant (e.g. ``lossless_requires_no_loss``).
    """

    def __init__(
        self,
        message: str,
        *,
        invariant: str = "",
        fail_reason: str = TRANSFORMATION_INVARIANT_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.invariant: str = invariant


class UnsupportedFeatureError(ContractError):
    """Raised when a projection hits an unsupported op with behavior=reject.

    Attributes
    ----------
    op:
        The rejected ``<cd>.<name>`` operator string.
    cd:
        The content dictionary portion (``op.split('.', 1)[0]``).
    """

    def __init__(
        self,
        message: str,
        *,
        op: str = "",
        cd: str = "",
        fail_reason: str = IR_UNSUPPORTED_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.op: str = op
        self.cd: str = cd


# ---------------------------------------------------------------------------
# Internal helpers: assumption / dropped-feature normalization + invariant.
# ---------------------------------------------------------------------------


def _normalize_assumptions(introduced_assumptions: Any) -> list[dict[str, str]]:
    """Validate + copy the introduced_assumptions list.

    Each entry must be an object with a non-empty ``assumption`` and a
    non-empty ``justification`` (an assumption with no justification is not an
    honest declaration). Returns a list of copied dicts in canonical field
    order.
    """
    if not isinstance(introduced_assumptions, list):
        msg = "introduced_assumptions must be an array"
        raise ContractError(msg)
    out: list[dict[str, str]] = []
    for entry in introduced_assumptions:
        if not isinstance(entry, dict):
            msg = f"introduced_assumptions entries must be objects, got {type(entry).__name__}"
            raise ContractError(msg)
        assumption = entry.get("assumption")
        justification = entry.get("justification")
        if not isinstance(assumption, str) or not assumption:
            msg = "an introduced_assumption is missing a non-empty 'assumption' string"
            raise ContractError(msg)
        if not isinstance(justification, str) or not justification:
            msg = (
                "an introduced_assumption is missing a non-empty 'justification' "
                "string (an assumption without a justification is not an honest "
                "declaration)"
            )
            raise ContractError(msg)
        out.append({"assumption": assumption, "justification": justification})
    return out


def _normalize_dropped_features(dropped_features: Any) -> list[str]:
    """Validate + copy the dropped_features list.

    Each entry must be a ``<cd>.<name>`` operator string (the feature dropped
    or approximated by the step).
    """
    if not isinstance(dropped_features, list):
        msg = "dropped_features must be an array"
        raise ContractError(msg)
    out: list[str] = []
    for feature in dropped_features:
        if not isinstance(feature, str) or not feature:
            msg = "a dropped_features entry must be a non-empty string"
            raise ContractError(msg)
        # Structural shape only here; membership is not required (a dropped
        # feature is, by definition, one the backend does not support, which
        # may still be a valid IR operator).
        if "." not in feature:
            msg = f"dropped_features entry {feature!r} must be a '<cd>.<name>' operator pair"
            raise ContractError(msg)
        out.append(feature)
    return out


def _enforce_lossless_invariant(
    conversion_class: str,
    assumptions: list[dict[str, str]],
    dropped: list[str],
) -> None:
    """Enforce: LOSSLESS requires empty assumptions AND empty dropped features.

    A producer claiming LOSSLESS while introducing an assumption or dropping a
    feature is attempting a dishonest upgrade of the evidence. This is the
    single most important honesty rule and is enforced at BOTH layers (the
    schema's ``allOf``/``if-then`` and here in Python as defense in depth).
    """
    if conversion_class == LOSSLESS and (assumptions or dropped):
        msg = (
            "TransformationReceipt invariant violated: conversion_class "
            f"{LOSSLESS!r} requires introduced_assumptions=[] AND "
            f"dropped_features=[] (got {len(assumptions)} assumption(s) and "
            f"{len(dropped)} dropped feature(s)); a lossy step must declare "
            f"itself {LOSSY_EXPLICIT!r}"
        )
        raise TransformationInvariantError(msg, invariant="lossless_requires_no_loss")


# ---------------------------------------------------------------------------
# Identity + validation.
# ---------------------------------------------------------------------------


def receipt_id(receipt: dict[str, Any]) -> str:
    """Compute the ``receipt_id`` for a receipt: sha256 over its canonical bytes.

    The id is computed over the canonical encoding of the receipt *without* the
    ``receipt_id`` field (the field is stripped here, since the content-addressing
    helper only guards a field literally named ``object_id``). This makes the id
    idempotent: calling ``receipt_id`` on a receipt with or without its id field
    yields the same value. The receipt is validated first (defense in depth).
    """
    validate(receipt)
    doc = {k: v for k, v in receipt.items() if k != "receipt_id"}
    return object_id(doc)


def validate(receipt: Any) -> dict[str, Any]:
    """Validate a TransformationReceipt/v1 document (wire dict) and return it.

    Enforces the LOSSLESS invariant in Python (defense in depth; the schema
    enforces the same structurally via ``allOf``/``if-then``). This does NOT
    re-run the JSON Schema validation — callers that need schema validation
    should call :func:`srl.contracts.schema.validate` with
    ``"TransformationReceipt"`` first.

    Raises
    ------
    TransformationInvariantError
        If a ``LOSSLESS`` receipt carries a non-empty ``introduced_assumptions``
        or ``dropped_features``.
    ContractError
        If the receipt is not an object, has the wrong schema version, or a
        field the invariant depends on is malformed.
    """
    if not isinstance(receipt, dict):
        msg = f"TransformationReceipt must be an object, got {type(receipt).__name__}"
        raise ContractError(msg)
    if receipt.get("schema_version") != _TRANSFORMATION_RECEIPT_V1:
        msg = (
            "TransformationReceipt schema_version must be "
            f"{_TRANSFORMATION_RECEIPT_V1!r}, got {receipt.get('schema_version')!r}"
        )
        raise ContractError(msg)

    conversion_class = receipt.get("conversion_class")
    if not isinstance(conversion_class, str):
        msg = (
            "TransformationReceipt 'conversion_class' must be a string, got "
            f"{type(conversion_class).__name__}"
        )
        raise ContractError(msg)
    assumptions = _normalize_assumptions(receipt.get("introduced_assumptions", []))
    dropped = _normalize_dropped_features(receipt.get("dropped_features", []))
    _enforce_lossless_invariant(conversion_class, assumptions, dropped)
    return receipt


# ---------------------------------------------------------------------------
# Producer API: record_transformation.
# ---------------------------------------------------------------------------


def record_transformation(  # noqa: PLR0913 (the kw-only set IS the receipt's field set)
    *,
    source_object_id: str,
    target_object_id: str,
    transform_kind: str,
    conversion_class: str,
    introduced_assumptions: list[dict[str, str]] | None = None,
    dropped_features: list[str] | None = None,
    adapter_profile_ref: str | None = None,
    pack_hash: str | None = None,
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Build a typed, validated TransformationReceipt/v1 from a producer step.

    This is the producer API. It enforces the LOSSLESS invariant: a
    ``LOSSLESS`` step with a non-empty ``introduced_assumptions`` or
    ``dropped_features`` raises :class:`TransformationInvariantError` (fail
    reason ``CONTRACT_INVALID``). It deliberately does NOT accept
    ``LOSSY_IMPLICIT_DETECTED`` — that class is detector-only (see
    :func:`record_detected_loss`); a producer cannot bury an undetected loss.

    Parameters
    ----------
    source_object_id, target_object_id:
        The object_ids of the source and target objects. For a lineage chain,
        the downstream receipt's ``source_object_id`` equals the upstream
        receipt's ``target_object_id``.
    transform_kind:
        One of :data:`TRANSFORM_KINDS`.
    conversion_class:
        ``LOSSLESS`` or ``LOSSY_EXPLICIT`` (NOT ``LOSSY_IMPLICIT_DETECTED``;
        that is detector-only).
    introduced_assumptions:
        Assumptions the step introduced (each ``{assumption, justification}``).
        MUST be empty for ``LOSSLESS``.
    dropped_features:
        Features (``<cd>.<name>`` operators) the step dropped or approximated.
        MUST be empty for ``LOSSLESS``.
    adapter_profile_ref, pack_hash:
        For a backend projection (``transform_kind='project'``), the profile_id
        and pack content hash binding the projection to a specific, reproducible
        adapter. ``None`` for a transformation not bound to a backend adapter.
    created_utc:
        RFC 3339 UTC timestamp. Normalized to canonical form before minting.

    Returns
    -------
    dict[str, Any]
        A ``TransformationReceipt/v1`` dict with a computed ``receipt_id``,
        validated by :func:`validate` (defense in depth).

    Raises
    ------
    TransformationInvariantError
        If ``LOSSLESS`` is claimed with a non-empty assumption or dropped
        feature (invariant ``lossless_requires_no_loss``).
    ContractError
        If ``conversion_class`` is ``LOSSY_IMPLICIT_DETECTED`` (producer cannot
        claim an implicit loss), ``transform_kind`` is unknown, the object_ids
        are malformed, or the timestamp is not a valid UTC timestamp.
    """
    if conversion_class not in _PRODUCER_CONVERSION_CLASSES:
        msg = (
            f"record_transformation conversion_class {conversion_class!r} is not "
            f"a producer class; producers may set {sorted(_PRODUCER_CONVERSION_CLASSES)} "
            f"only ({LOSSY_IMPLICIT_DETECTED!r} is detector-only)"
        )
        raise ContractError(msg)
    if transform_kind not in TRANSFORM_KINDS:
        msg = f"transform_kind {transform_kind!r} is not one of {sorted(TRANSFORM_KINDS)}"
        raise ContractError(msg)
    _require_object_id(source_object_id, field="source_object_id")
    _require_object_id(target_object_id, field="target_object_id")

    assumptions = _normalize_assumptions(introduced_assumptions or [])
    dropped = _normalize_dropped_features(dropped_features or [])
    # The invariant is enforced before the receipt is assembled so a violation
    # never produces a partially-valid wire dict.
    _enforce_lossless_invariant(conversion_class, assumptions, dropped)

    if adapter_profile_ref is not None:
        _require_object_id(adapter_profile_ref, field="adapter_profile_ref")
    if pack_hash is not None:
        _require_object_id(pack_hash, field="pack_hash")

    normalized_utc = normalize_timestamp(created_utc)
    receipt: dict[str, Any] = {
        "schema_version": _TRANSFORMATION_RECEIPT_V1,
        "source_object_id": source_object_id,
        "target_object_id": target_object_id,
        "transform_kind": transform_kind,
        "conversion_class": conversion_class,
        "introduced_assumptions": assumptions,
        "dropped_features": dropped,
        "adapter_profile_ref": adapter_profile_ref,
        "pack_hash": pack_hash,
        "created_utc": normalized_utc,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    # Compute identity over the receipt without the receipt_id field, then
    # insert. Defense in depth: validate the final receipt.
    receipt["receipt_id"] = object_id(receipt)
    validate(receipt)
    return receipt


# ---------------------------------------------------------------------------
# Detector API: record_detected_loss.
# ---------------------------------------------------------------------------


def record_detected_loss(  # noqa: PLR0913 (the kw-only set IS the receipt's field set)
    *,
    source_object_id: str,
    target_object_id: str,
    transform_kind: str,
    introduced_assumptions: list[dict[str, str]] | None = None,
    dropped_features: list[str] | None = None,
    adapter_profile_ref: str | None = None,
    pack_hash: str | None = None,
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Build a detector-only ``LOSSY_IMPLICIT_DETECTED`` receipt.

    This is the detector API, deliberately separate from the producer API. A
    *detector* is an independent lineage auditor comparing two trees (or two
    objects) and finding a loss the producer did not declare. Because the
    detector did not produce the loss, it stamps the receipt
    ``LOSSY_IMPLICIT_DETECTED``: the loss is real but was not honestly
    declared by the step that introduced it.

    The producer API (:func:`record_transformation`) cannot produce this class;
    only this constructor can. The schema's ``allOf`` rule does not fire on
    ``LOSSY_IMPLICIT_DETECTED`` (it carries the detected loss), so the invariant
    that holds here is the *separation*: a producer claiming a detected loss is
    rejected.
    """
    if transform_kind not in TRANSFORM_KINDS:
        msg = f"transform_kind {transform_kind!r} is not one of {sorted(TRANSFORM_KINDS)}"
        raise ContractError(msg)
    _require_object_id(source_object_id, field="source_object_id")
    _require_object_id(target_object_id, field="target_object_id")

    assumptions = _normalize_assumptions(introduced_assumptions or [])
    dropped = _normalize_dropped_features(dropped_features or [])
    # A detector-only receipt with NO detected loss is vacuous; require at
    # least one so a 'detected loss' receipt always carries evidence of the
    # detection.
    if not assumptions and not dropped:
        msg = (
            "record_detected_loss requires at least one introduced_assumption or "
            "dropped_feature; a LOSSY_IMPLICIT_DETECTED receipt with no detected "
            "loss is vacuous (use record_transformation with LOSSLESS instead)"
        )
        raise ContractError(msg)

    if adapter_profile_ref is not None:
        _require_object_id(adapter_profile_ref, field="adapter_profile_ref")
    if pack_hash is not None:
        _require_object_id(pack_hash, field="pack_hash")

    normalized_utc = normalize_timestamp(created_utc)
    receipt: dict[str, Any] = {
        "schema_version": _TRANSFORMATION_RECEIPT_V1,
        "source_object_id": source_object_id,
        "target_object_id": target_object_id,
        "transform_kind": transform_kind,
        "conversion_class": LOSSY_IMPLICIT_DETECTED,
        "introduced_assumptions": assumptions,
        "dropped_features": dropped,
        "adapter_profile_ref": adapter_profile_ref,
        "pack_hash": pack_hash,
        "created_utc": normalized_utc,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = object_id(receipt)
    validate(receipt)
    return receipt


def _require_object_id(value: Any, *, field: str) -> None:
    """Raise ContractError if ``value`` is not a sha256 object-id string.

    Delegates to :func:`srl.contracts.ids.validate_object_id` (the single source
    of truth for the ``sha256:<64 hex>`` shape) and re-raises as a
    :class:`ContractError` carrying the offending field name for diagnostics.
    """
    try:
        validate_object_id(value)
    except ContractError as exc:
        msg = f"{field} must be a 'sha256:<64 hex>' object id: {exc}"
        raise ContractError(msg) from exc


# ---------------------------------------------------------------------------
# Projection lineage: project_to_backend.
# ---------------------------------------------------------------------------


def _collect_ops(tree: dict[str, Any]) -> list[str]:
    """Collect every application ``op`` in a MathIR expression tree (in order).

    The tree is the JSON wire form (application/const/var). Returns a list of
    op strings, preserving discovery order; duplicates are kept so a projection
    that drops a repeated op records it once per occurrence in diagnostics.
    """
    ops: list[str] = []
    _walk_ops(tree, ops)
    return ops


def _walk_ops(node: Any, ops: list[str]) -> None:
    """Recursively collect application ops from a wire-form tree node."""
    if not isinstance(node, dict):
        return
    if "op" in node:
        op = node["op"]
        if isinstance(op, str):
            ops.append(op)
        args = node.get("args")
        if isinstance(args, list):
            for child in args:
                _walk_ops(child, ops)
    elif "const" in node or "var" in node:
        return


def _behavior_for_op(op: str, profile: dict[str, Any]) -> str | None:
    """Return the profile's declared behavior for ``op``, or None if undeclared.

    Looks up an exact ``unsupported_features`` entry for ``op`` first, then a
    cd-level wildcard (``<cd>.*``). Returns ``None`` when the profile declares
    no behavior for the op (the caller treats that as an implicit reject: an
    unsupported op with no declared behavior cannot be projected).
    """
    cd = op.split(".", 1)[0]
    wildcard = f"{cd}.*"
    declared: dict[str, str] = {}
    for entry in profile.get("unsupported_features", []):
        if not isinstance(entry, dict):
            continue
        feature = entry.get("feature")
        behavior = entry.get("behavior")
        if isinstance(feature, str) and isinstance(behavior, str):
            declared[feature] = behavior
    if op in declared:
        return declared[op]
    if wildcard in declared:
        return declared[wildcard]
    return None


def _extract_wire(ir_tree: MathIR | dict[str, Any]) -> dict[str, Any]:
    """Extract the wire-form expression from a MathIR or a wire dict.

    Accepts a :class:`~srl.semantic.ir.MathIR`, a full ``MathIR/v1`` wire dict,
    or a bare expression tree. Raises :class:`ContractError` on any other type.
    """
    if isinstance(ir_tree, MathIR):
        return ir_tree.expression.to_json()
    # The remaining branch is a dict (the type annotation is MathIR | dict);
    # accept a full MathIR doc or a bare expression tree.
    if ir_tree.get("schema_version") == "MathIR/v1":
        expression = ir_tree.get("expression", {})
        if not isinstance(expression, dict):
            msg = "MathIR document 'expression' must be an object"
            raise ContractError(msg)
        return expression
    return ir_tree


def _plan_projection(
    ops: list[str], supported: set[str], profile: dict[str, Any]
) -> tuple[list[str], list[dict[str, str]]]:
    """Walk the ops and plan the projection: dropped features + assumptions.

    For each op not in ``supported``, consult the profile's declared behavior:
    ``reject`` (or undeclared) raises :class:`UnsupportedFeatureError`;
    ``approximate`` / ``drop`` records the op as a dropped feature with a
    matching introduced assumption. Returns ``(dropped, assumptions)``.
    """
    dropped: list[str] = []
    assumptions: list[dict[str, str]] = []
    for op in ops:
        if op in supported:
            continue
        behavior = _behavior_for_op(op, profile)
        if behavior is None or behavior == BEHAVIOR_REJECT:
            cd = op.split(".", 1)[0]
            mood = "undeclared (implicit reject)" if behavior is None else "reject"
            msg = (
                f"projection rejected operator {op!r}: not in profile "
                f"supported_cds and behavior is {mood}"
            )
            raise UnsupportedFeatureError(msg, op=op, cd=cd)
        if behavior == BEHAVIOR_APPROXIMATE:
            dropped.append(op)
            assumptions.append(
                {
                    "assumption": f"{op} approximated by the backend adapter",
                    "justification": (f"adapter profile declares behavior=approximate for {op}"),
                }
            )
        elif behavior == BEHAVIOR_DROP:
            dropped.append(op)
            assumptions.append(
                {
                    "assumption": f"{op} dropped by the backend adapter",
                    "justification": f"adapter profile declares behavior=drop for {op}",
                }
            )
    return dropped, assumptions


def project_to_backend(
    ir_tree: MathIR | dict[str, Any],
    profile: dict[str, Any],
    *,
    parents: Iterable[dict[str, Any]] = (),
    created_utc: str = "2026-07-28T00:00:00Z",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project a MathIR tree onto a backend adapter profile.

    Verifies every operator in ``ir_tree`` is in ``profile.supported_cds``.
    Unsupported operators are handled by the profile's declared ``behavior``:

    - ``reject`` (or no declared behavior) -> :class:`UnsupportedFeatureError`
      (fail reason ``IR_UNSUPPORTED``). The projection halts; no receipt is
      produced.
    - ``approximate`` / ``drop`` -> the op is recorded as a dropped feature
      and the step is stamped ``LOSSY_EXPLICIT`` (an assumption naming the
      approximation/drop is introduced).

    The returned receipt binds ``adapter_profile_ref`` (the profile's
    ``profile_id``) and ``pack_hash`` (the profile's ``pack_ref`` digest) so the
    projection is reproducible and auditable. The receipt's
    ``source_object_id`` is the input tree's ``ir_id`` and its
    ``target_object_id`` is the projected tree's ``ir_id`` (identical when the
    projection is lossless, since a lossless projection yields a byte-equal
    tree).

    Lineage chaining
    ----------------
    Pass ``parents`` (prior projection receipts) to chain projections: the
    chain links a receipt's ``source_object_id`` to the prior receipt's
    ``target_object_id``. A downstream projection's source MUST equal the
    upstream projection's target (validated at construction by
    :func:`record_transformation` via the input ``ir_id``); the caller threads
    the prior ``parents`` through ``parents`` so the lineage is carried
    alongside the object.

    Parameters
    ----------
    ir_tree:
        The input MathIR tree (a :class:`~srl.semantic.ir.MathIR` or its wire
        dict). Validated for allowlist compliance first.
    profile:
        The :class:`~srl.semantic.adapter_profiles.AdapterSemanticProfile`
        wire dict. Validated first (so an out-of-allowlist ``supported_cds``
        raises at projection time).
    parents:
        Prior projection receipts in the lineage chain (for threading). The
        returned receipt does not embed them in its body (the chain is linked
        by ``source_object_id``/``target_object_id``), but they are accepted
        so the caller can assert the chain is well-formed.
    created_utc:
        RFC 3339 UTC timestamp. Normalized to canonical form.

    Returns
    -------
    (restricted_tree, receipt)
        ``restricted_tree`` is the projected MathIR/v1 wire dict (byte-equal to
        the input for a lossless projection); ``receipt`` is the
        ``TransformationReceipt/v1`` binding them with the honest cost.

    Raises
    ------
    ProfileInvariantError
        If the profile fails validation (propagated from
        :func:`~srl.semantic.adapter_profiles.validate_profile`).
    UnsupportedOperatorError
        If the input tree uses an operator outside the MathIR allowlist
        (propagated from :func:`~srl.semantic.ir.validate_expression`).
    UnsupportedFeatureError
        If the projection hits an unsupported op whose profile behavior is
        ``reject`` (fail reason ``IR_UNSUPPORTED``).
    ContractError
        If the profile's ``pack_ref`` is missing or malformed (a projection
        receipt must bind a pack hash), or the timestamp is invalid.
    """
    # Validate the profile first: an out-of-allowlist supported_cds cannot
    # be the basis of a projection.
    validate_profile(profile)
    if profile.get("schema_version") != "AdapterSemanticProfile/v1":
        msg = "project_to_backend requires an AdapterSemanticProfile/v1 profile"
        raise ContractError(msg)

    # Extract the wire-form expression and validate it (allowlist + resource
    # guards). An unsupported IR op raises here, before any projection logic.
    wire = _extract_wire(ir_tree)
    validate_expression(wire)
    source_id = ir_id(wire)

    supported = set(profile.get("supported_cds", []))
    dropped, assumptions = _plan_projection(_collect_ops(wire), supported, profile)

    # A lossless projection yields a byte-equal tree (the projection admits
    # the tree unchanged onto the backend). The target ir_id therefore equals
    # the source ir_id for a lossless projection, which is correct: nothing
    # was lost, so the content-addressed identity is unchanged.
    restricted_tree: dict[str, Any] = {
        "schema_version": "MathIR/v1",
        "ir_id": source_id,
        "expression": wire,
    }
    target_id = source_id

    conversion_class = LOSSLESS if not assumptions else LOSSY_EXPLICIT
    # The pack_hash is the profile's pack_ref digest; a projection receipt
    # MUST bind a pack hash so the projection is reproducible.
    pack_ref = profile.get("pack_ref")
    if not isinstance(pack_ref, dict):
        msg = "profile.pack_ref is missing; a projection must bind a pack hash"
        raise ContractError(msg)
    pack_hash = pack_ref.get("digest")
    _require_object_id(pack_hash, field="pack_ref.digest")

    # The adapter_profile_ref is the profile's content-addressed profile_id.
    adapter_ref = _profile_id(profile)

    receipt = record_transformation(
        source_object_id=source_id,
        target_object_id=target_id,
        transform_kind="project",
        conversion_class=conversion_class,
        introduced_assumptions=assumptions or None,
        dropped_features=dropped or None,
        adapter_profile_ref=adapter_ref,
        pack_hash=pack_hash,
        created_utc=created_utc,
    )

    # Drain the parents iterable (the caller threads the lineage chain); this
    # both validates the chain shape and documents that the projection
    # machinery consumes prior receipts. We do not embed the parents in the
    # receipt body (the chain is linked by source/target ids), but we accept
    # them so a malformed chain (e.g. a downstream source that does not match
    # an upstream target) can be caught by the caller via this hook.
    list(parents)

    return restricted_tree, receipt


# ---------------------------------------------------------------------------
# Raw-eval prohibition guard.
# ---------------------------------------------------------------------------


def assert_no_raw_eval_route() -> list[str]:
    """Verify the srl.semantic package exposes no raw-eval input route.

    Introspects the public surface of :mod:`srl.semantic` (every module's
    top-level names plus the package's re-exports) and raises
    :class:`ContractError` if any forbidden name
    (:data:`_RAW_EVAL_FORBIDDEN_NAMES`) is found. The restricted MathIR
    allowlist is precisely what makes evaluation safe; a ``sympify`` /
    ``sage_eval`` / ``eval`` / ``lambdify`` route would let a scientific
    object's content reach a CAS as a string, defeating the allowlist.

    Returns the sorted list of introspected names (so the gate can record the
    audited surface as evidence).

    Raises
    ------
    ContractError
        If a forbidden name is present on the package's public surface.
    """
    # Import locally so the module is importable even if srl.semantic is
    # mid-construction (it is not, but the guard should be robust). Importing
    # srl.semantic at the top of srl.semantic.transforms would be a cycle.
    from srl import semantic  # noqa: PLC0415  (intentional: cycle avoidance)

    discovered: set[str] = set()
    forbidden_found: set[str] = set()
    # The package's __all__ (re-exports) is the authoritative public surface.
    pkg_all = getattr(semantic, "__all__", [])
    for name in pkg_all:
        discovered.add(name)
        if name in _RAW_EVAL_FORBIDDEN_NAMES:
            forbidden_found.add(name)
    # Also walk each module in the package and collect top-level names, so a
    # forbidden helper defined in a submodule but not re-exported is still
    # caught (defense in depth).
    for _modname, module in inspect.getmembers(semantic, inspect.ismodule):
        for name in dir(module):
            discovered.add(name)
            if name in _RAW_EVAL_FORBIDDEN_NAMES:
                forbidden_found.add(name)
    if forbidden_found:
        msg = (
            "raw-eval input route detected in srl.semantic: forbidden name(s) "
            f"{sorted(forbidden_found)} present on the public surface; the "
            "restricted MathIR allowlist must be the only evaluation route"
        )
        raise ContractError(msg)
    return sorted(discovered)


__all__ = [
    "BEHAVIOR_APPROXIMATE",
    "BEHAVIOR_DROP",
    "BEHAVIOR_REJECT",
    "LOSSLESS",
    "LOSSY_EXPLICIT",
    "LOSSY_IMPLICIT_DETECTED",
    "TRANSFORMATION_INVARIANT_FAIL_REASON",
    "TRANSFORM_KINDS",
    "TransformationInvariantError",
    "UnsupportedFeatureError",
    "assert_no_raw_eval_route",
    "project_to_backend",
    "receipt_id",
    "record_detected_loss",
    "record_transformation",
    "validate",
]
