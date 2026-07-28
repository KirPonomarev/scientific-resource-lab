"""Retrospective pilot specification and private overlay machinery (WP-G60).

This package implements the *public parts* of the private overlay: the
machine-checkable contract for a **retrospective** pilot and the generic
machinery that resolves an operator's private overlay at runtime.

The two load-bearing honesty properties of this package are:

1. **A spec is hashes-only.** A ``PilotSpec/v1`` carries ``sha256:`` digests of
   source artifacts, never paths. The public repository only ever sees the
   generic machinery and the digests; the private overlay config file is NEVER
   committed and NEVER appears in any public artifact (see
   :mod:`srl.pilot.overlay`).
2. **A pilot is honest by construction.** ``status_promotion_allowed``,
   ``prospective_holdout_materialization_allowed``, and ``grants_authority``
   are pinned ``false`` as ``const`` (see
   ``src/srl/contracts/schemas/v1/pilot-spec.json``). A null or inconclusive
   outcome is a VALID pilot outcome; execution conformance is NOT statistical
   power (see ``docs/operations/private-overlay.md``).

See :mod:`srl.pilot.spec` for the spec loader/freezer and the const-false /
holdout guards, and :mod:`srl.pilot.overlay` for the private overlay resolver.
"""

from __future__ import annotations

from srl.pilot.overlay import (
    ARTIFACT_STORE_ENV,
    OVERLAY_FAIL_REASON,
    PRIVATE_CONFIG_ENV,
    OverlayConfig,
    OverlayError,
    resolve_overlay,
)
from srl.pilot.spec import (
    PILOT_FAIL_REASON,
    PilotSpecError,
    freeze_spec,
    load_pilot_spec,
    pilot_id,
    validate_holdout_free,
)

__all__ = [
    "ARTIFACT_STORE_ENV",
    "OVERLAY_FAIL_REASON",
    "PILOT_FAIL_REASON",
    "PRIVATE_CONFIG_ENV",
    "OverlayConfig",
    "OverlayError",
    "PilotSpecError",
    "freeze_spec",
    "load_pilot_spec",
    "pilot_id",
    "resolve_overlay",
    "validate_holdout_free",
]
