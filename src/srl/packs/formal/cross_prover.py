"""Cross-prover formal contours without automatic theorem equivalence."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

CROSS_PROVER_ADMISSION_BUNDLE_SCHEMA_VERSION: Final[str] = "CrossProverAdmissionBundle/v1"
THEOREM_TRANSLATION_MANIFEST_SCHEMA_VERSION: Final[str] = "TheoremTranslationManifest/v1"
INDEPENDENT_PROVER_PINS_SCHEMA_VERSION: Final[str] = "IndependentProverPins/v1"
SHARED_A10_CLAIM_ID: Final[str] = "nat-zero-add-right"
SHARED_A10_THEOREM_LABEL: Final[str] = "srl_a10_zero_add"
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
_A10_PINS_PATH: Final[Path] = (
    _REPO_ROOT / "configs" / "packs" / "formal" / "independent-prover-pins.json"
)


class CrossProverError(ContractError):
    """Raised when a cross-prover contour or translation manifest is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class FormalContourStatus(StrEnum):
    """Admission state of one formal contour."""

    ACTIVE = "ACTIVE"
    WAIT_TOOLCHAIN = "WAIT_TOOLCHAIN"


@dataclass(frozen=True)
class FormalContour:
    """One theorem-prover contour with exact logic and assumption boundaries."""

    contour_id: str
    prover_name: str
    logic: str
    status: FormalContourStatus
    executable_candidates: tuple[str, ...]
    version_output: str | None
    semantic_scope: str
    assumptions: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        for field in (
            "contour_id",
            "prover_name",
            "logic",
            "semantic_scope",
            "reason",
        ):
            _require_non_empty(getattr(self, field), field)
        for field in ("executable_candidates", "assumptions"):
            values = getattr(self, field)
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not item for item in values
            ):
                raise CrossProverError(f"{field} must be a tuple of non-empty strings")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible contour card."""
        return {
            "contour_id": self.contour_id,
            "prover_name": self.prover_name,
            "logic": self.logic,
            "status": self.status.value,
            "executable_candidates": list(self.executable_candidates),
            "version_output": self.version_output,
            "semantic_scope": self.semantic_scope,
            "assumptions": list(self.assumptions),
            "reason": self.reason,
            "canonical_writes": 0,
            "grants_authority": False,
        }


def discover_cross_prover_contours(
    *,
    executable_resolver: Callable[[str], str | None] | None = None,
    lean_primary_active: bool = True,
    timeout_seconds: float = 10.0,
) -> tuple[FormalContour, ...]:
    """Discover cross-prover contours without installing or building toolchains."""
    resolver = executable_resolver or shutil.which
    return (
        _lean_contour(lean_primary_active),
        _discover_external_contour(
            contour_id="rocq.primary",
            prover_name="Rocq/Coq",
            logic="calculus_of_inductive_constructions",
            executable_candidates=("rocq", "rocqtop", "coqc"),
            semantic_scope="constructive_type_theory_with_universe_constraints",
            assumptions=("kernel_acceptance_is_per_statement",),
            resolver=resolver,
            timeout_seconds=timeout_seconds,
        ),
        _discover_external_contour(
            contour_id="isabelle.hol",
            prover_name="Isabelle/HOL",
            logic="classical_higher_order_logic",
            executable_candidates=("isabelle",),
            semantic_scope="object_logic_hol_inside_isabelle_framework",
            assumptions=("session_image_and_theory_imports_are_part_of_the_statement",),
            resolver=resolver,
            timeout_seconds=timeout_seconds,
        ),
        _discover_external_contour(
            contour_id="hol4.primary",
            prover_name="HOL4",
            logic="classical_higher_order_logic",
            executable_candidates=("Holmake",),
            semantic_scope="hol4_kernel_theory_graph",
            assumptions=("theory_load_order_is_part_of_the_statement",),
            resolver=resolver,
            timeout_seconds=timeout_seconds,
        ),
    )


def build_translation_manifest(  # noqa: PLR0913 - manifest boundary fields stay explicit.
    *,
    theorem_label: str,
    source_contour_id: str,
    target_contour_id: str,
    source_logic: str,
    target_logic: str,
    source_assumptions: tuple[str, ...],
    target_assumptions: tuple[str, ...],
    translation_notes: tuple[str, ...],
    equivalence_claimed: bool = False,
) -> dict[str, object]:
    """Build a manifest for one theorem translation attempt.

    The manifest can compare assumptions and logics, but it never asserts that
    two prover statements are semantically equivalent.
    """
    for field, value in (
        ("theorem_label", theorem_label),
        ("source_contour_id", source_contour_id),
        ("target_contour_id", target_contour_id),
        ("source_logic", source_logic),
        ("target_logic", target_logic),
    ):
        _require_non_empty(value, field)
    if equivalence_claimed:
        raise CrossProverError("automatic theorem equivalence claims are forbidden")
    _require_tuple(source_assumptions, "source_assumptions")
    _require_tuple(target_assumptions, "target_assumptions")
    _require_tuple(translation_notes, "translation_notes")
    assumption_delta = sorted(set(source_assumptions).symmetric_difference(target_assumptions))
    logic_delta = source_logic != target_logic
    manifest: dict[str, object] = {
        "schema_version": THEOREM_TRANSLATION_MANIFEST_SCHEMA_VERSION,
        "theorem_label": theorem_label,
        "source_contour_id": source_contour_id,
        "target_contour_id": target_contour_id,
        "source_logic": source_logic,
        "target_logic": target_logic,
        "source_assumptions": list(source_assumptions),
        "target_assumptions": list(target_assumptions),
        "translation_notes": list(translation_notes),
        "semantic_gap": {
            "logic_delta": logic_delta,
            "assumption_delta": assumption_delta,
        },
        "equivalence_claimed": False,
        "requires_independent_review": True,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    manifest["manifest_id"] = "sha256:" + hashlib.sha256(dumps(manifest)).hexdigest()
    return manifest


def build_cross_prover_admission_bundle(
    *,
    contours: tuple[FormalContour, ...] | None = None,
    translation_manifests: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    """Build a deterministic cross-prover admission bundle."""
    resolved = contours or discover_cross_prover_contours()
    if len({contour.contour_id for contour in resolved}) != len(resolved):
        raise CrossProverError("contour_id values must be unique")
    for manifest in translation_manifests:
        if manifest.get("equivalence_claimed") is not False:
            raise CrossProverError("translation manifests must not claim equivalence")
    body: dict[str, object] = {
        "schema_version": CROSS_PROVER_ADMISSION_BUNDLE_SCHEMA_VERSION,
        "contours": [contour.to_dict() for contour in resolved],
        "active_contour_ids": [
            contour.contour_id
            for contour in resolved
            if contour.status is FormalContourStatus.ACTIVE
        ],
        "wait_contour_ids": [
            contour.contour_id
            for contour in resolved
            if contour.status is FormalContourStatus.WAIT_TOOLCHAIN
        ],
        "translation_manifests": list(translation_manifests),
        "automatic_equivalence_claims": 0,
        "semantic_policy": "compare_logics_and_assumptions_never_assert_equivalence",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["bundle_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def load_independent_prover_pins(path: Path | None = None) -> dict[str, object]:
    """Load the A10 prover pin manifest with authority-negative safety consts."""
    source = path or _A10_PINS_PATH
    pins = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(pins, dict):
        raise CrossProverError("independent prover pins must be a JSON object")
    if pins.get("schema_version") != INDEPENDENT_PROVER_PINS_SCHEMA_VERSION:
        raise CrossProverError("independent prover pins schema mismatch")
    if pins.get("automatic_equivalence_claims") != 0:
        raise CrossProverError("independent prover pins must not claim equivalence")
    if pins.get("canonical_writes") != 0 or pins.get("grants_authority") is not False:
        raise CrossProverError("independent prover pins must be authority-negative")
    shared_claim = pins.get("shared_claim")
    if not isinstance(shared_claim, dict) or shared_claim.get("claim_id") != SHARED_A10_CLAIM_ID:
        raise CrossProverError("independent prover pins shared claim mismatch")
    for key in ("rocq", "isabelle", "hol4"):
        if not isinstance(pins.get(key), dict):
            raise CrossProverError(f"independent prover pins missing {key}")
    return pins


def independent_prover_pin_manifest_hash(path: Path | None = None) -> str:
    """Return the canonical SHA-256 of the A10 independent-prover pin manifest."""
    return hashlib.sha256(dumps(load_independent_prover_pins(path))).hexdigest()


def build_a10_translation_manifests(
    *,
    contours: tuple[FormalContour, ...],
    theorem_label: str = SHARED_A10_THEOREM_LABEL,
) -> tuple[dict[str, object], ...]:
    """Build one semantic-gap manifest from Lean primary to each A10 contour."""
    by_id = {contour.contour_id: contour for contour in contours}
    source = by_id.get("lean.primary")
    if source is None:
        raise CrossProverError("lean.primary contour is required")
    manifests: list[dict[str, object]] = []
    for target_id in ("rocq.primary", "isabelle.hol", "hol4.primary"):
        target = by_id.get(target_id)
        if target is None:
            raise CrossProverError(f"{target_id} contour is required")
        manifests.append(
            build_translation_manifest(
                theorem_label=theorem_label,
                source_contour_id=source.contour_id,
                target_contour_id=target.contour_id,
                source_logic=source.logic,
                target_logic=target.logic,
                source_assumptions=source.assumptions,
                target_assumptions=target.assumptions,
                translation_notes=(
                    "same informal natural-number claim represented in target syntax",
                    "logic and library semantics remain explicit per contour",
                    "manifest forbids automatic theorem equivalence claims",
                ),
            )
        )
    return tuple(manifests)


def _lean_contour(active: bool) -> FormalContour:
    return FormalContour(
        contour_id="lean.primary",
        prover_name="Lean/mathlib",
        logic="dependent_type_theory_calculus_of_inductive_constructions_family",
        status=FormalContourStatus.ACTIVE if active else FormalContourStatus.WAIT_TOOLCHAIN,
        executable_candidates=("lean", "lake"),
        version_output="A09 LeanAdmissionReceipt/v1",
        semantic_scope="declared_statement_only",
        assumptions=("formalization_correctness_not_implied",),
        reason="A09_lean_primary_proven" if active else "A09_lean_primary_not_active",
    )


def _discover_external_contour(  # noqa: PLR0913 - contour descriptors stay explicit.
    *,
    contour_id: str,
    prover_name: str,
    logic: str,
    executable_candidates: tuple[str, ...],
    semantic_scope: str,
    assumptions: tuple[str, ...],
    resolver: Callable[[str], str | None],
    timeout_seconds: float,
) -> FormalContour:
    for executable in executable_candidates:
        resolved = resolver(executable)
        if resolved:
            version = _probe_version(resolved, executable, timeout_seconds)
            return FormalContour(
                contour_id=contour_id,
                prover_name=prover_name,
                logic=logic,
                status=FormalContourStatus.ACTIVE,
                executable_candidates=executable_candidates,
                version_output=version,
                semantic_scope=semantic_scope,
                assumptions=assumptions,
                reason=f"{executable}_available",
            )
    return FormalContour(
        contour_id=contour_id,
        prover_name=prover_name,
        logic=logic,
        status=FormalContourStatus.WAIT_TOOLCHAIN,
        executable_candidates=executable_candidates,
        version_output=None,
        semantic_scope=semantic_scope,
        assumptions=assumptions,
        reason="toolchain_executable_missing",
    )


def _probe_version(path: str, executable_name: str, timeout_seconds: float) -> str | None:
    command = (path, "version") if executable_name == "isabelle" else (path, "--version")
    try:
        completed = subprocess.run(  # noqa: S603 - executable is resolved locally, never shell=True.
            command,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout or completed.stderr
    return output.decode("utf-8", errors="replace").strip()[:1000]


def _require_tuple(values: object, field: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, str) or not item for item in values
    ):
        raise CrossProverError(f"{field} must be a tuple of non-empty strings")


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise CrossProverError(f"{field} must be a non-empty string")


__all__ = [
    "CROSS_PROVER_ADMISSION_BUNDLE_SCHEMA_VERSION",
    "INDEPENDENT_PROVER_PINS_SCHEMA_VERSION",
    "SHARED_A10_CLAIM_ID",
    "SHARED_A10_THEOREM_LABEL",
    "THEOREM_TRANSLATION_MANIFEST_SCHEMA_VERSION",
    "CrossProverError",
    "FormalContour",
    "FormalContourStatus",
    "build_a10_translation_manifests",
    "build_cross_prover_admission_bundle",
    "build_translation_manifest",
    "discover_cross_prover_contours",
    "independent_prover_pin_manifest_hash",
    "load_independent_prover_pins",
]
