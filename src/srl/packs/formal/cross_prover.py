"""Cross-prover formal contours without automatic theorem equivalence."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

CROSS_PROVER_ADMISSION_BUNDLE_SCHEMA_VERSION: Final[str] = "CrossProverAdmissionBundle/v1"
THEOREM_TRANSLATION_MANIFEST_SCHEMA_VERSION: Final[str] = "TheoremTranslationManifest/v1"


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
    "THEOREM_TRANSLATION_MANIFEST_SCHEMA_VERSION",
    "CrossProverError",
    "FormalContour",
    "FormalContourStatus",
    "build_cross_prover_admission_bundle",
    "build_translation_manifest",
    "discover_cross_prover_contours",
]
