"""SRL semantic object fabric and the scientific intermediate representation.

This package sits one layer above :mod:`srl.contracts`: where the contracts
package provides the canonical encoding, content-addressed identity, and the
JSON Schema loader, the semantic package provides the *typed* scientific
object model — the mathematical IR, the scientific claim with its epistemic
invariants, the transformation receipts that carry honest lineage, and the
fabric that mints content-addressed envelopes around type-specific payloads.

Eight object types are introduced here, each with a JSON Schema under
``src/srl/contracts/schemas/v1/`` and (where it carries a non-trivial
invariant) a Python validator:

- :class:`~srl.semantic.ir.MathIR` — a mathematical IR expression tree over a
  restricted OpenMath-style allowlist (:data:`~srl.semantic.ir.MATH_IR_ALLOWLIST`).
- :class:`~srl.semantic.claims.ScientificClaim` — a typed statement with
  epistemic discipline (claim class/status/source and the established-law and
  candidate-hypothesis invariants).
- ``SymbolTable`` — a table of symbols (id/name/role/domain/unit).
- ``ConditionSet`` — a set of assumptions attached to a model.
- ``ConstantRef`` — a reference to a physical/mathematical constant.
- ``ModelInterface`` — a typed interface to a scientific model.
- ``AdapterSemanticProfile`` (WP-B12) — a typed semantic profile for a backend
  adapter (its supported operator subset of the IR allowlist, its
  unsupported-feature behavior, its determinism/network/license posture).
- ``TransformationReceipt`` (WP-B12) — a receipt binding source->target by a
  named transformation, carrying the honest cost (``LOSSLESS`` /
  ``LOSSY_EXPLICIT`` / ``LOSSY_IMPLICIT_DETECTED``) and the lineage chain.

Everything here is an *admission* contract. A green validation result means a
value satisfied the structural contract; it never means a scientific claim is
supported (see ``GOVERNANCE.md`` for the evidence rules).
"""

from __future__ import annotations

from srl.semantic.adapter_profiles import (
    PROFILE_INVARIANT_FAIL_REASON,
    ProfileInvariantError,
)
from srl.semantic.adapter_profiles import (
    profile_id as adapter_profile_id,
)
from srl.semantic.adapter_profiles import (
    validate_profile as validate_adapter_profile,
)
from srl.semantic.claims import (
    CLAIM_INVARIANT_FAIL_REASON,
    ClaimInvariantError,
)
from srl.semantic.claims import (
    claim_id as claim_object_id,
)
from srl.semantic.claims import (
    validate as validate_claim,
)
from srl.semantic.fabric import (
    SUPPORTED_OBJECT_TYPES,
    mint_object,
)
from srl.semantic.ir import (
    IR_RESOURCE_FAIL_REASON,
    IR_UNSUPPORTED_FAIL_REASON,
    MATH_IR_ALLOWLIST,
    MAX_DEPTH,
    MAX_NODES,
    Application,
    Const,
    Expr,
    IRResourceLimitError,
    MathIR,
    UnsupportedOperatorError,
    Var,
    validate_expression,
)
from srl.semantic.ir import (
    build as build_math_ir,
)
from srl.semantic.ir import (
    ir_id as math_ir_id,
)
from srl.semantic.ir import (
    validate as validate_math_ir,
)
from srl.semantic.transforms import (
    BEHAVIOR_APPROXIMATE,
    BEHAVIOR_DROP,
    BEHAVIOR_REJECT,
    LOSSLESS,
    LOSSY_EXPLICIT,
    LOSSY_IMPLICIT_DETECTED,
    TRANSFORM_KINDS,
    TRANSFORMATION_INVARIANT_FAIL_REASON,
    TransformationInvariantError,
    UnsupportedFeatureError,
    assert_no_raw_eval_route,
    project_to_backend,
    record_detected_loss,
    record_transformation,
)
from srl.semantic.transforms import (
    receipt_id as transformation_receipt_id,
)
from srl.semantic.transforms import (
    validate as validate_transformation,
)

__all__ = [
    "BEHAVIOR_APPROXIMATE",
    "BEHAVIOR_DROP",
    "BEHAVIOR_REJECT",
    "CLAIM_INVARIANT_FAIL_REASON",
    "IR_RESOURCE_FAIL_REASON",
    "IR_UNSUPPORTED_FAIL_REASON",
    "LOSSLESS",
    "LOSSY_EXPLICIT",
    "LOSSY_IMPLICIT_DETECTED",
    "MATH_IR_ALLOWLIST",
    "MAX_DEPTH",
    "MAX_NODES",
    "PROFILE_INVARIANT_FAIL_REASON",
    "SUPPORTED_OBJECT_TYPES",
    "TRANSFORMATION_INVARIANT_FAIL_REASON",
    "TRANSFORM_KINDS",
    "Application",
    "ClaimInvariantError",
    "Const",
    "Expr",
    "IRResourceLimitError",
    "MathIR",
    "ProfileInvariantError",
    "TransformationInvariantError",
    "UnsupportedFeatureError",
    "UnsupportedOperatorError",
    "Var",
    "adapter_profile_id",
    "assert_no_raw_eval_route",
    "build_math_ir",
    "claim_object_id",
    "math_ir_id",
    "mint_object",
    "project_to_backend",
    "record_detected_loss",
    "record_transformation",
    "transformation_receipt_id",
    "validate_adapter_profile",
    "validate_claim",
    "validate_expression",
    "validate_math_ir",
    "validate_transformation",
]
