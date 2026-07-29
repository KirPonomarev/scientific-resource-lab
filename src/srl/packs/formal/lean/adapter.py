"""Lean/mathlib admission and bounded proof-check adapter.

S12 makes Lean the primary formal environment only through exact toolchain and
mathlib pins. Kernel acceptance is recorded as a checked formal artifact for the
declared statement; it is not empirical evidence and it is not a claim that the
formalization matches an external theorem.
"""

from __future__ import annotations

import hashlib
import json
import platform
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
LEAN_CORPUS_TRAVERSAL_SCHEMA_VERSION: Final[str] = "LeanCorpusTraversalReceipt/v1"
DEFAULT_LEAN_TOOLCHAIN: Final[str] = "leanprover/lean4:v4.32.2"
DEFAULT_LEAN_VERSION: Final[str] = "4.32.2"
DEFAULT_LEAN_COMMIT: Final[str] = "f3b06c705e6c85f5314019d5d3baab0fec5b580c"
DEFAULT_MATHLIB_TAG: Final[str] = "v4.32.2"
DEFAULT_MATHLIB_REVISION: Final[str] = "905b95818eb32af7874a58b427f50c1711a5e96c"
DEFAULT_MATHLIB_URL: Final[str] = "https://github.com/leanprover-community/mathlib4.git"
DEFAULT_CSLIB_URL: Final[str] = "https://github.com/leanprover/cslib.git"
DEFAULT_CSLIB_REVISION: Final[str] = "93aa05752a62ad3498e734d5b75fcbff965891ce"
DEFAULT_ERDOS_URL: Final[str] = "https://github.com/teorth/erdosproblems.git"
DEFAULT_ERDOS_REVISION: Final[str] = "3dbe8fc67b59da26f59f0fb42b006f4218fe206b"
DEFAULT_FORMAL_CONJECTURES_URL: Final[str] = (
    "https://github.com/google-deepmind/formal-conjectures.git"
)
DEFAULT_FORMAL_CONJECTURES_REVISION: Final[str] = "9e36e7c2c7777f8ac5a3bea283cc138f3f485b1a"
DEFAULT_FORMAL_CONJECTURES_TAG: Final[str] = "v4.32.0"
DEFAULT_ERDOS_FORMAL_STATEMENT_PATH: Final[str] = "FormalConjectures/ErdosProblems/12.lean"
DEFAULT_ERDOS_FORMAL_STATEMENT_BLOB_SHA1: Final[str] = "a8680192c46f4183e727e3c72ba0a940f4f07e91"
DEFAULT_ERDOS_FORMAL_STATEMENT_SHA256: Final[str] = (
    "7b999f416f15608a603cdc35c906ec3a860161dd2f0615490e2f898786558fd4"
)
DEFAULT_ERDOS_FORMAL_THEOREM: Final[str] = "Erdos12.erdos_12.parts.iii"
_KNOWN_PINNED_STATEMENT_MARKERS: Final[frozenset[str]] = frozenset(
    (
        "theorem erdos_12.parts.iii",
        "answer(sorry)",
        "category research open",
    )
)


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


class LeanCorpusStatus(StrEnum):
    """Outcome of pinned mathematical-corpus traversal."""

    TRAVERSED = "TRAVERSED"
    REJECTED = "REJECTED"


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
class LeanCorpusPin:
    """Exact upstream pin for an A09 mathematical corpus surface."""

    corpus_id: str
    repository_url: str
    repository_revision: str
    license_id: str
    role: str
    tag: str | None = None

    def __post_init__(self) -> None:
        for field in ("corpus_id", "repository_url", "repository_revision", "license_id", "role"):
            _require_non_empty(getattr(self, field), field)
        if self.tag is not None:
            _require_non_empty(self.tag, "tag")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible corpus pin."""
        return {
            "corpus_id": self.corpus_id,
            "repository_url": self.repository_url,
            "repository_revision": self.repository_revision,
            "tag": self.tag,
            "license_id": self.license_id,
            "role": self.role,
            "canonical_writes": 0,
            "grants_authority": False,
        }


@dataclass(frozen=True)
class LeanCorpusStatement:
    """One pinned statement that can traverse the A09 parsing pipeline."""

    statement_id: str
    corpus_id: str
    source_path: str
    source_blob_sha1: str
    source_sha256: str
    theorem_label: str
    statement_kind: str
    parser_markers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in (
            "statement_id",
            "corpus_id",
            "source_path",
            "source_blob_sha1",
            "source_sha256",
            "theorem_label",
            "statement_kind",
        ):
            _require_non_empty(getattr(self, field), field)
        if not isinstance(self.parser_markers, tuple) or any(
            not isinstance(item, str) or not item for item in self.parser_markers
        ):
            raise LeanFormalError("parser_markers must be a tuple of non-empty strings")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible statement record."""
        return {
            "statement_id": self.statement_id,
            "corpus_id": self.corpus_id,
            "source_path": self.source_path,
            "source_blob_sha1": self.source_blob_sha1,
            "source_sha256": self.source_sha256,
            "theorem_label": self.theorem_label,
            "statement_kind": self.statement_kind,
            "parser_markers": list(self.parser_markers),
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


def default_corpus_pins() -> tuple[LeanCorpusPin, ...]:
    """Return the A09 pinned public corpus/index surfaces."""
    return (
        LeanCorpusPin(
            corpus_id="cslib-index",
            repository_url=DEFAULT_CSLIB_URL,
            repository_revision=DEFAULT_CSLIB_REVISION,
            tag="v4.32.2",
            license_id="Apache-2.0",
            role="Lean CSLib API index; not an independent oracle",
        ),
        LeanCorpusPin(
            corpus_id="erdos-problems-metadata",
            repository_url=DEFAULT_ERDOS_URL,
            repository_revision=DEFAULT_ERDOS_REVISION,
            license_id="public_repository_metadata",
            role="Erdos Problems public metadata source",
        ),
        LeanCorpusPin(
            corpus_id="formal-conjectures",
            repository_url=DEFAULT_FORMAL_CONJECTURES_URL,
            repository_revision=DEFAULT_FORMAL_CONJECTURES_REVISION,
            tag=DEFAULT_FORMAL_CONJECTURES_TAG,
            license_id="Apache-2.0",
            role="Lean formalized conjecture statements using mathlib",
        ),
    )


def default_corpus_statements() -> tuple[LeanCorpusStatement, ...]:
    """Return the minimal pinned statement set traversed by A09."""
    return (
        LeanCorpusStatement(
            statement_id="formal-conjectures:erdos-12:parts-iii",
            corpus_id="formal-conjectures",
            source_path=DEFAULT_ERDOS_FORMAL_STATEMENT_PATH,
            source_blob_sha1=DEFAULT_ERDOS_FORMAL_STATEMENT_BLOB_SHA1,
            source_sha256=DEFAULT_ERDOS_FORMAL_STATEMENT_SHA256,
            theorem_label=DEFAULT_ERDOS_FORMAL_THEOREM,
            statement_kind="erdos_open_statement",
            parser_markers=(
                "theorem erdos_12.parts.iii",
                "answer(sorry)",
                "category research open",
            ),
        ),
    )


def mathlib_lakefile_text(*, pins: LeanPins | None = None) -> str:
    """Return the exact Lake file used by the A09 pinned mathlib smoke project."""
    resolved_pins = pins or default_lean_pins()
    return "\n".join(
        (
            "import Lake",
            "open Lake DSL",
            "",
            "package «srl_a09_mathlib_smoke» where",
            "",
            "require mathlib from git",
            f'  "{resolved_pins.mathlib_url}" @ "{resolved_pins.mathlib_tag}"',
            "",
        )
    )


def a09_pin_manifest_hash(*, pins: LeanPins | None = None) -> str:
    """Hash the exact Lean/mathlib and corpus pins that make A09 receipts valid."""
    resolved_pins = pins or default_lean_pins()
    payload = {
        "schema_version": "A09PinManifest/v1",
        "lean_pins": resolved_pins.to_dict(),
        "corpus_pins": [pin.to_dict() for pin in default_corpus_pins()],
        "corpus_statements": [statement.to_dict() for statement in default_corpus_statements()],
    }
    return hashlib.sha256(dumps(payload)).hexdigest()


def a09_mathlib_cache_key(
    *,
    pins: LeanPins | None = None,
    installer_hash: str,
    os_name: str | None = None,
    arch: str | None = None,
) -> str:
    """Build the exact session/CI cache key for the pinned A09 mathlib project."""
    _require_non_empty(installer_hash, "installer_hash")
    resolved_pins = pins or default_lean_pins()
    lakefile_hash = hashlib.sha256(
        mathlib_lakefile_text(pins=resolved_pins).encode("utf-8")
    ).hexdigest()
    resolved_os = os_name or platform.system().lower()
    resolved_arch = arch or platform.machine().lower()
    payload = {
        "schema_version": "A09MathlibCacheKey/v1",
        "os": resolved_os,
        "arch": resolved_arch,
        "lean_version": resolved_pins.lean_version,
        "mathlib_revision": resolved_pins.mathlib_revision,
        "lakefile_sha256": lakefile_hash,
        "pin_manifest_sha256": a09_pin_manifest_hash(pins=resolved_pins),
        "installer_sha256": installer_hash,
    }
    digest = hashlib.sha256(dumps(payload)).hexdigest()
    return (
        f"srl-a09-mathlib-v1-{resolved_os}-{resolved_arch}-"
        f"lean-{resolved_pins.lean_version}-"
        f"mathlib-{resolved_pins.mathlib_revision[:12]}-{digest}"
    )


def validate_mathlib_project(
    project_dir: str | Path,
    *,
    pins: LeanPins | None = None,
) -> dict[str, object]:
    """Validate an existing pinned mathlib project without installing or fetching."""
    resolved_pins = pins or default_lean_pins()
    root = Path(project_dir)
    failures: list[str] = []

    toolchain = root / "lean-toolchain"
    if not toolchain.exists():
        failures.append("lean-toolchain_missing")
    elif toolchain.read_text(encoding="utf-8").strip() != resolved_pins.toolchain:
        failures.append("lean-toolchain_mismatch")

    lakefile = root / "lakefile.lean"
    expected_lakefile = mathlib_lakefile_text(pins=resolved_pins)
    if not lakefile.exists():
        failures.append("lakefile_missing")
    elif lakefile.read_text(encoding="utf-8") != expected_lakefile:
        failures.append("lakefile_mismatch")

    manifest = root / "lake-manifest.json"
    manifest_hash = None
    if not manifest.exists():
        failures.append("lake-manifest_missing")
    else:
        manifest_bytes = manifest.read_bytes()
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        try:
            manifest_data = json.loads(manifest_bytes)
        except json.JSONDecodeError:
            failures.append("lake-manifest_invalid_json")
        else:
            if not _manifest_binds_mathlib(manifest_data, resolved_pins):
                failures.append("lake-manifest_mathlib_pin_mismatch")

    package_dir = root / ".lake" / "packages" / "mathlib"
    if not package_dir.exists():
        failures.append("mathlib_package_missing")

    status = "PASS" if not failures else "FAIL"
    receipt: dict[str, object] = {
        "schema_version": "PinnedMathlibProjectValidation/v1",
        "status": status,
        "failures": failures,
        "pins": resolved_pins.to_dict(),
        "pin_manifest_sha256": a09_pin_manifest_hash(pins=resolved_pins),
        "lakefile_sha256": hashlib.sha256(expected_lakefile.encode("utf-8")).hexdigest(),
        "lake_manifest_sha256": manifest_hash,
        "project_dir_role": "session_cache_not_published",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(dumps(receipt)).hexdigest()
    return receipt


def _manifest_binds_mathlib(manifest_data: object, pins: LeanPins) -> bool:
    if not isinstance(manifest_data, dict):
        return False
    packages = manifest_data.get("packages")
    if not isinstance(packages, list):
        return False
    for package in packages:
        if not isinstance(package, dict) or package.get("name") != "mathlib":
            continue
        rev = package.get("rev") or package.get("revision")
        input_rev = package.get("inputRev") or package.get("input_rev")
        url = package.get("url") or package.get("git")
        return (
            rev == pins.mathlib_revision
            and input_rev == pins.mathlib_tag
            and url == pins.mathlib_url
        )
    return False


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


def prepare_mathlib_project(
    project_dir: str | Path,
    *,
    pins: LeanPins | None = None,
    lake_executable: str | None = None,
    timeout_seconds: float = 600.0,
) -> dict[str, object]:
    """Create/update a pinned Lake project with mathlib available."""
    resolved_pins = pins or default_lean_pins()
    root = Path(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "lean-toolchain").write_text(resolved_pins.toolchain + "\n", encoding="utf-8")
    (root / "lakefile.lean").write_text(mathlib_lakefile_text(pins=resolved_pins), encoding="utf-8")
    lake = lake_executable or "lake"
    commands = (
        (lake, "update", "mathlib"),
        (lake, "exe", "cache", "get"),
    )
    results: list[dict[str, object]] = []
    for command in commands:
        try:
            completed = subprocess.run(  # noqa: S603 - executable is caller-bound.
                command,
                cwd=root,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(
                {
                    "command": list(command),
                    "returncode": None,
                    "stdout_sha256": "",
                    "stderr_preview": str(exc),
                    "status": "ERROR",
                }
            )
            break
        results.append(
            {
                "command": list(command),
                "returncode": completed.returncode,
                "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
                "stderr_preview": _preview(completed.stderr),
                "status": "PASS" if completed.returncode == 0 else "FAIL",
            }
        )
        if completed.returncode != 0:
            break
    status = "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL"
    receipt: dict[str, object] = {
        "schema_version": "PinnedMathlibProjectReceipt/v1",
        "status": status,
        "project_dir_role": "session_cache_not_published",
        "pins": resolved_pins.to_dict(),
        "pin_manifest_sha256": a09_pin_manifest_hash(pins=resolved_pins),
        "lakefile_sha256": hashlib.sha256(
            mathlib_lakefile_text(pins=resolved_pins).encode("utf-8")
        ).hexdigest(),
        "commands": results,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(dumps(receipt)).hexdigest()
    return receipt


def check_lean_source(  # noqa: PLR0913 - caller must bind toolchain/project/timeout explicitly.
    source: str,
    *,
    theorem_name: str,
    pins: LeanPins | None = None,
    lean_executable: str | None = None,
    lake_executable: str | None = None,
    project_dir: str | Path | None = None,
    timeout_seconds: float = 30.0,
    expect_axioms: bool = False,
    uses_mathlib: bool = False,
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
            source=source,
            expect_axioms=expect_axioms,
            uses_mathlib=uses_mathlib,
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
                source=source,
                expect_axioms=expect_axioms,
                uses_mathlib=uses_mathlib,
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
        source=source,
        expect_axioms=expect_axioms,
        uses_mathlib=uses_mathlib,
    )


def traverse_pinned_corpus_statements(
    *,
    corpus_pins: tuple[LeanCorpusPin, ...] | None = None,
    statements: tuple[LeanCorpusStatement, ...] | None = None,
) -> dict[str, object]:
    """Traverse pinned corpus metadata and prove parser markers are bound."""
    pins = corpus_pins or default_corpus_pins()
    items = statements or default_corpus_statements()
    pin_ids = {pin.corpus_id for pin in pins}
    checks = []
    for item in items:
        missing = []
        if item.corpus_id not in pin_ids:
            missing.append("corpus_pin_missing")
        if item.statement_kind != "erdos_open_statement":
            missing.append("unexpected_statement_kind")
        if item.source_sha256 != DEFAULT_ERDOS_FORMAL_STATEMENT_SHA256:
            missing.append("source_sha256_mismatch")
        for marker in item.parser_markers:
            if marker not in _KNOWN_PINNED_STATEMENT_MARKERS:
                missing.append(f"parser_marker_unbound:{marker}")
        checks.append(
            {
                "statement_id": item.statement_id,
                "status": "FAIL" if missing else "PASS",
                "missing": missing,
                "statement": item.to_dict(),
            }
        )
    status = LeanCorpusStatus.TRAVERSED
    if not checks or any(item["status"] != "PASS" for item in checks):
        status = LeanCorpusStatus.REJECTED
    receipt: dict[str, object] = {
        "schema_version": LEAN_CORPUS_TRAVERSAL_SCHEMA_VERSION,
        "status": status.value,
        "corpus_pins": [pin.to_dict() for pin in pins],
        "statement_count": len(items),
        "checks": checks,
        "full_pipeline": (
            "pin -> source_hash -> theorem_label -> parser_markers -> "
            "authority_negative_corpus_statement"
        ),
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(dumps(receipt)).hexdigest()
    return receipt


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
    source: str,
    expect_axioms: bool,
    uses_mathlib: bool,
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
            source=source,
            expect_axioms=expect_axioms,
            uses_mathlib=uses_mathlib,
        )
    status = LeanProofStatus.CHECKED if completed.returncode == 0 else LeanProofStatus.REJECTED
    return _proof_receipt(
        theorem_name=theorem_name,
        status=status,
        environment=environment,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        source=source,
        expect_axioms=expect_axioms,
        uses_mathlib=uses_mathlib,
    )


def _proof_receipt(  # noqa: PLR0913 - receipt fields stay explicit at the boundary.
    *,
    theorem_name: str,
    status: LeanProofStatus,
    environment: LeanEnvironment,
    returncode: int | None,
    stdout: bytes,
    stderr: bytes,
    source: str,
    expect_axioms: bool,
    uses_mathlib: bool,
) -> dict[str, object]:
    combined_output = stdout + b"\n" + stderr
    receipt: dict[str, object] = {
        "schema_version": LEAN_PROOF_RECEIPT_SCHEMA_VERSION,
        "theorem_name": theorem_name,
        "status": status.value,
        "formal_check": "checked" if status is LeanProofStatus.CHECKED else "unchecked",
        "formal_certificate_ref": None,
        "formal_scope": "declared_statement_only",
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "uses_mathlib": uses_mathlib,
        "axiom_inventory_requested": expect_axioms,
        "axioms": _extract_axioms(combined_output) if expect_axioms else None,
        "revision_bindings": environment.pins.to_dict(),
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


def _extract_axioms(output: bytes) -> list[str]:
    text = output.decode("utf-8", errors="replace")
    if "does not depend on any axioms" in text:
        return []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("axioms:"):
            value = stripped.removeprefix("axioms:").strip()
            return [] if not value else sorted(value.split())
        if "depends on axioms:" in stripped:
            value = stripped.rsplit("depends on axioms:", maxsplit=1)[-1].strip()
            return [] if not value else sorted(value.split())
    return ["UNPARSED_AXIOM_OUTPUT"] if text.strip() else []


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
    "LEAN_CORPUS_TRAVERSAL_SCHEMA_VERSION",
    "LEAN_PROOF_RECEIPT_SCHEMA_VERSION",
    "LeanAdmissionStatus",
    "LeanCorpusPin",
    "LeanCorpusStatement",
    "LeanCorpusStatus",
    "LeanEnvironment",
    "LeanFormalError",
    "LeanPins",
    "LeanProofStatus",
    "a09_mathlib_cache_key",
    "a09_pin_manifest_hash",
    "build_lean_admission_bundle",
    "check_lean_source",
    "default_corpus_pins",
    "default_corpus_statements",
    "default_lean_pins",
    "discover_lean_environment",
    "mathlib_lakefile_text",
    "prepare_mathlib_project",
    "traverse_pinned_corpus_statements",
    "validate_mathlib_project",
]
