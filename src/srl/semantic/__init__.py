"""SRL semantic object fabric and the scientific intermediate representation.

This package sits one layer above :mod:`srl.contracts`: where the contracts
package provides the canonical encoding, content-addressed identity, and the
JSON Schema loader, the semantic package provides the *typed* scientific
object model — the mathematical IR, the scientific claim with its epistemic
invariants, and the fabric that mints content-addressed envelopes around
type-specific payloads.

Six object types are introduced here, each with a JSON Schema under
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

Everything here is an *admission* contract. A green validation result means a
value satisfied the structural contract; it never means a scientific claim is
supported (see ``GOVERNANCE.md`` for the evidence rules).
"""

from __future__ import annotations

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

__all__ = [
    "CLAIM_INVARIANT_FAIL_REASON",
    "IR_RESOURCE_FAIL_REASON",
    "IR_UNSUPPORTED_FAIL_REASON",
    "MATH_IR_ALLOWLIST",
    "MAX_DEPTH",
    "MAX_NODES",
    "SUPPORTED_OBJECT_TYPES",
    "Application",
    "ClaimInvariantError",
    "Const",
    "Expr",
    "IRResourceLimitError",
    "MathIR",
    "UnsupportedOperatorError",
    "Var",
    "build_math_ir",
    "claim_object_id",
    "math_ir_id",
    "mint_object",
    "validate_claim",
    "validate_expression",
    "validate_math_ir",
]
