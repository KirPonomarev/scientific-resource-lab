"""Lean/mathlib admission and bounded proof-check adapter.

S12 makes Lean the primary formal environment only through exact toolchain and
mathlib pins. Kernel acceptance is recorded as a checked formal artifact for the
declared statement; it is not empirical evidence and it is not a claim that the
formalization matches an external theorem.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

LEAN_ADMISSION_BUNDLE_SCHEMA_VERSION: Final[str] = "LeanAdmissionBundle/v1"
LEAN_PROOF_RECEIPT_SCHEMA_VERSION: Final[str] = "LeanProofReceipt/v1"
DEFAULT_LEAN_TOOLCHAIN: Final[str] = "leanprover/lean4:v4.32.2"
DEFAULT_LEAN_VERSION: Final[str] = "4.32.2"
DEFAULT_LEAN_COMMIT: Final[str] = "f3b06c705e6c85f5314019d5d3baab0fec5b580c"
DEFAULT_MATHLIB_TAG: Final[str] = "v4.32.2"
DEFAULT_MATHLIB_REVISION: Final[str] = "905b95818eb32af7874a58b427f50c1711a5e96c"
DEFAULT_MATHLIB_URL: Final[str] = "https://github.com/leanprover-community/mathlib4.git"


class LeanFormalError(ContractError):
    """Raised when Lean formal-pack input is structurally invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class LeanAdmissionStatus(StrEnum):
    """Lean formal-pack admission status."""

    ACTIVE = "ACTIVE"
    WAIT_TOOLCHAIN = "WAIT_TOOLCHAIN"
    WAIT_MATHLIB = "WAIT_MATHLIB"


class LeanProofStatus(StrEnum):
    """Outcome of one bounded Lean proof-check attempt."""

    CHECKED = "CHECKED"
    REJECTED = "REJECTED"
    WAIT_TOOLCHAIN = "WAIT_TOOLCHAIN"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass(frozen=True)
class LeanPins:
    """Exact Lean/mathlib pin set."""

    toolchain: str
    lean_version: str
    lean_commit: str
    mathlib_url: str
    mathlib_tag: str
    mathlib_revision: str

    def __post_init__(self) -> None:
        for field in (
            "toolchain",
            "lean_version",
            "lean_commit",
            "mathlib_url",
            "mathlib_tag",
            "mathlib_revision",
        ):
            _require_non_empty(getattr(self, field), field)

    def to_dict(self) -> dict[str, str]:
        """Return a stable JSON-compatible pin record."""
        return {
            "toolchain": self.toolchain,
            "lean_version": self.lean_version,
            "lean_commit": self.lean_commit,
            "mathlib_url": self.mathlib_url,
            "mathlib_tag": self.mathlib_tag,
            "mathlib_revision": self.mathlib_revision,
        }


@dataclass(frozen=True)
class LeanEnvironment:
    """Observed local Lean/Lake environment."""

    status: LeanAdmissionStatus
    reason: str
    lean_version_output: str | None
    lake_version_output: str | None
    pins: LeanPins

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible environment record."""
        return {
            "status": self.status.value,
            "reason": self.reason,
            "lean_version_output": self.lean_version_output,
            "lake_version_output": self.lake_version_output,
            "pins": self.pins.to_dict(),
            "canonical_writes": 0,
            "grants_authority": False,
        }


def default_lean_pins() -> LeanPins:
    """Return the S12 stable Lean/mathlib pin set."""
    return LeanPins(
        toolchain=DEFAULT_LEAN_TOOLCHAIN,
        lean_version=DEFAULT_LEAN_VERSION,
        lean_commit=DEFAULT_LEAN_COMMIT,
        mathlib_url=DEFAULT_MATHLIB_URL,
        mathlib_tag=DEFAULT_MATHLIB_TAG,
        mathlib_revision=DEFAULT_MATHLIB_REVISION,
    )


def discover_lean_environment(
    *,
    pins: LeanPins | None = None,
    lean_executable: str | None = None,
    lake_executable: str | None = None,
    timeout_seconds: float = 10.0,
) -> LeanEnvironment:
    """Inspect local Lean/Lake without installing, updating or building anything."""
    resolved_pins = pins or default_lean_pins()
    lean_path = lean_executable or shutil.which("lean")
    lake_path = lake_executable or shutil.which("lake")
    if not lean_path or not lake_path:
        return LeanEnvironment(
            status=LeanAdmissionStatus.WAIT_TOOLCHAIN,
            reason="lean_or_lake_executable_missing",
            lean_version_output=None,
            lake_version_output=None,
            pins=resolved_pins,
        )
    lean_version = _run_version((lean_path, "--version"), timeout_seconds)
    lake_version = _run_version((lake_path, "--version"), timeout_seconds)
    if lean_version is None or lake_version is None:
        return LeanEnvironment(
            status=LeanAdmissionStatus.WAIT_TOOLCHAIN,
            reason="lean_or_lake_version_probe_failed",
            lean_version_output=lean_version,
            lake_version_output=lake_version,
            pins=resolved_pins,
        )
    if f"version {resolved_pins.lean_version}" not in lean_version:
        return LeanEnvironment(
            status=LeanAdmissionStatus.WAIT_TOOLCHAIN,
            reason="lean_version_mismatch",
            lean_version_output=lean_version,
            lake_version_output=lake_version,
            pins=resolved_pins,
        )
    if resolved_pins.lean_commit not in lean_version:
        return LeanEnvironment(
            status=LeanAdmissionStatus.WAIT_TOOLCHAIN,
            reason="lean_commit_mismatch",
            lean_version_output=lean_version,
            lake_version_output=lake_version,
            pins=resolved_pins,
        )
    return LeanEnvironment(
        status=LeanAdmissionStatus.ACTIVE,
        reason="lean_and_lake_match_pins",
        lean_version_output=lean_version,
        lake_version_output=lake_version,
        pins=resolved_pins,
    )


def check_lean_source(  # noqa: PLR0913 - caller must bind toolchain/project/timeout explicitly.
    source: str,
    *,
    theorem_name: str,
    pins: LeanPins | None = None,
    lean_executable: str | None = None,
    lake_executable: str | None = None,
    project_dir: str | Path | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    """Run a bounded Lean check and return an authority-negative receipt.

    If ``project_dir`` is supplied, the source is checked through
    ``lake env lean`` inside that project so imports such as Mathlib resolve
    against the caller's pinned Lake manifest. Otherwise Lean is invoked
    directly in an isolated temporary directory.
    """
    _require_non_empty(source, "source")
    _require_non_empty(theorem_name, "theorem_name")
    environment = discover_lean_environment(
        pins=pins,
        lean_executable=lean_executable,
        lake_executable=lake_executable,
        timeout_seconds=min(timeout_seconds, 10.0),
    )
    if environment.status is not LeanAdmissionStatus.ACTIVE:
        return _proof_receipt(
            theorem_name=theorem_name,
            status=LeanProofStatus.WAIT_TOOLCHAIN,
            environment=environment,
            returncode=None,
            stdout=b"",
            stderr=environment.reason.encode(),
        )

    if project_dir is None:
        with tempfile.TemporaryDirectory(prefix="srl-lean-") as tmp:
            path = Path(tmp) / "Proof.lean"
            path.write_text(source, encoding="utf-8")
            return _run_lean_file(
                path=path,
                project_dir=None,
                theorem_name=theorem_name,
                environment=environment,
                lean_executable=lean_executable or "lean",
                lake_executable=lake_executable or "lake",
                timeout_seconds=timeout_seconds,
            )

    root = Path(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "SrlProofCheck.lean"
    path.write_text(source, encoding="utf-8")
    return _run_lean_file(
        path=path,
        project_dir=root,
        theorem_name=theorem_name,
        environment=environment,
        lean_executable=lean_executable or "lean",
        lake_executable=lake_executable or "lake",
        timeout_seconds=timeout_seconds,
    )


def build_lean_admission_bundle(
    *,
    pins: LeanPins | None = None,
    environment: LeanEnvironment | None = None,
    mathlib_smoke_receipt: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a deterministic Lean admission bundle."""
    resolved_pins = pins or default_lean_pins()
    env = environment or discover_lean_environment(pins=resolved_pins)
    smoke_status = (
        None
        if mathlib_smoke_receipt is None
        else str(mathlib_smoke_receipt.get("status", "UNKNOWN"))
    )
    if env.status is not LeanAdmissionStatus.ACTIVE:
        status: LeanAdmissionStatus = env.status
        reason = env.reason
    elif smoke_status == LeanProofStatus.CHECKED.value:
        status = LeanAdmissionStatus.ACTIVE
        reason = "lean_kernel_and_pinned_mathlib_smoke_checked"
    else:
        status = LeanAdmissionStatus.WAIT_MATHLIB
        reason = "mathlib_smoke_receipt_missing_or_not_checked"
    body: dict[str, object] = {
        "schema_version": LEAN_ADMISSION_BUNDLE_SCHEMA_VERSION,
        "status": status.value,
        "reason": reason,
        "pins": resolved_pins.to_dict(),
        "environment": env.to_dict(),
        "mathlib_smoke_receipt_id": (
            None if mathlib_smoke_receipt is None else mathlib_smoke_receipt.get("receipt_id")
        ),
        "formal_scope": "declared_statement_only",
        "formalization_warning": (
            "Lean kernel acceptance checks the submitted formal statement; it does "
            "not prove that the statement faithfully formalizes an external theorem."
        ),
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["bundle_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def _run_lean_file(  # noqa: PLR0913 - private subprocess adapter keeps call context explicit.
    *,
    path: Path,
    project_dir: Path | None,
    theorem_name: str,
    environment: LeanEnvironment,
    lean_executable: str,
    lake_executable: str,
    timeout_seconds: float,
) -> dict[str, object]:
    if project_dir is None:
        command: tuple[str, ...] = (lean_executable, path.name)
        cwd = path.parent
    else:
        command = (lake_executable, "env", "lean", path.name)
        cwd = project_dir
    try:
        completed = subprocess.run(  # noqa: S603 - executable is caller-bound and never shell=True.
            command,
            cwd=cwd,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return _proof_receipt(
            theorem_name=theorem_name,
            status=LeanProofStatus.TIMEOUT,
            environment=environment,
            returncode=None,
            stdout=exc.stdout or b"",
            stderr=exc.stderr or b"timeout",
        )
    status = LeanProofStatus.CHECKED if completed.returncode == 0 else LeanProofStatus.REJECTED
    return _proof_receipt(
        theorem_name=theorem_name,
        status=status,
        environment=environment,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _proof_receipt(  # noqa: PLR0913 - receipt fields stay explicit at the boundary.
    *,
    theorem_name: str,
    status: LeanProofStatus,
    environment: LeanEnvironment,
    returncode: int | None,
    stdout: bytes,
    stderr: bytes,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": LEAN_PROOF_RECEIPT_SCHEMA_VERSION,
        "theorem_name": theorem_name,
        "status": status.value,
        "formal_check": "checked" if status is LeanProofStatus.CHECKED else "unchecked",
        "formal_certificate_ref": None,
        "formal_scope": "declared_statement_only",
        "returncode": returncode,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stderr_preview": _preview(stderr),
        "environment": environment.to_dict(),
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(dumps(receipt)).hexdigest()
    return receipt


def _run_version(command: tuple[str, ...], timeout_seconds: float) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603 - version probe runs a caller-bound executable.
            command,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace").strip()


def _preview(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    return text[:1000]


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise LeanFormalError(f"{field} must be a non-empty string")


__all__ = [
    "LEAN_ADMISSION_BUNDLE_SCHEMA_VERSION",
    "LEAN_PROOF_RECEIPT_SCHEMA_VERSION",
    "LeanAdmissionStatus",
    "LeanEnvironment",
    "LeanFormalError",
    "LeanPins",
    "LeanProofStatus",
    "build_lean_admission_bundle",
    "check_lean_source",
    "default_lean_pins",
    "discover_lean_environment",
]
