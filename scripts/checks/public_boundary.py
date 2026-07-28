"""Stdlib public-boundary scanner for tracked files in CI.

The scanner walks every file returned by ``git ls-files`` and checks for
content that must never cross the public repository boundary:

- oversized files (> 5 MiB)
- binary extensions (.zip, .tar, .gz, .whl, .so, .dylib, .pkl, .pt, .onnx,
  .h5, .parquet, .duckdb, .sqlite, ...)
- absolute local paths (``/Users/``, ``/home/``, ``/Volumes/``) in text files
- recognizable credential patterns (same regex set as ``secret_scan.py``)
- T7 / UUIDv7-shaped identifiers
- sensitive JSON keys (``organism_pulse``, ``unified_snapshot``,
  ``operator_context``) anywhere in a JSON object

Documentation under ``docs/`` is treated conservatively: absolute paths are
allowed only when they appear inside inline code spans or fenced code blocks.
A small file allowlist covers the project's own leak-guard test fixtures,
which intentionally contain fake paths and tokens.

The report is deterministic JSON written to stdout.  A non-zero exit code means
at least one boundary violation was found.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SIZE_LIMIT_BYTES: Final[int] = 5 * 1024 * 1024

_BINARY_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".zip",
        ".tar",
        ".gz",
        ".whl",
        ".so",
        ".dylib",
        ".pkl",
        ".pt",
        ".onnx",
        ".h5",
        ".parquet",
        ".duckdb",
        ".sqlite",
        ".db",
        ".bin",
        ".exe",
        ".dll",
    }
)

# Conservative file allowlist: files that deliberately contain fake local paths
# and synthetic tokens as part of the project's own leak-guard tests or
# automation metadata.
_PATH_ALLOWLIST_FILES: Final[frozenset[str]] = frozenset(
    {
        "automation/checks.json",
        "tests/unit/test_leakguard.py",
        "scripts/checks/wp03-gate.py",
        "fixtures/conformance/corpus/task-29-redaction-local-path-refused/task.json",
        "scripts/checks/wp20-gate.py",
        "tests/cas/test_identity.py",
        "tests/cas/test_privacy.py",
    }
)

# Same concrete credential shapes used by secret_scan.py.
_CREDENTIAL_PATTERNS: Final[tuple[tuple[str, str, str], ...]] = (
    ("github_pat_classic", r"ghp_[A-Za-z0-9]{16,}", "GitHub classic PAT"),
    ("github_oauth_token", r"gho_[A-Za-z0-9]{16,}", "GitHub OAuth token"),
    (
        "github_fine_grained_pat",
        r"github_pat_[A-Za-z0-9_]{16,}",
        "GitHub fine-grained PAT",
    ),
    ("sk_api_key", r"sk-[A-Za-z0-9]{16,}", "API key (sk-)"),
    ("aws_access_key_id", r"AKIA[0-9A-Z]{16}", "AWS access key ID"),
    ("slack_bot_token", r"xoxb-[A-Za-z0-9-]{10,}", "Slack bot token"),
    (
        "jwt",
        r"eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*",
        "JWT-shaped blob",
    ),
    (
        "pem_private_key",
        r"BEGIN [A-Z ]*PRIVATE KEY",
        "PEM private key header",
    ),
)

_CREDENTIALS_COMPILED: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = tuple(
    (name, re.compile(pattern), kind) for (name, pattern, kind) in _CREDENTIAL_PATTERNS
)

_LOCAL_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:/Users/[A-Za-z0-9][A-Za-z0-9._-]*|/home/[A-Za-z0-9][A-Za-z0-9._-]*|/Volumes/[A-Za-z0-9][A-Za-z0-9._-]*)"
)

# UUIDv7 (RFC 9562): xxxxxxxx-xxxx-7xxx-[89ab]xxx-xxxxxxxxxxxx
_UUIDV7_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)

_SENSITIVE_JSON_KEYS: Final[frozenset[str]] = frozenset(
    {"organism_pulse", "unified_snapshot", "operator_context"}
)

# Snippet sanitization constants.
_SNIPPET_CONTEXT_CHARS: Final[int] = 12
_SNIPPET_KEEP_CHARS: Final[int] = 4
_SNIPPET_MAX_CHARS: Final[int] = 80

_GIT_EXECUTABLE: Final[str] = shutil.which("git") or "git"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Violation:
    """A single public-boundary violation."""

    kind: str
    file: str
    line: int
    snippet: str


@dataclass(frozen=True)
class Report:
    """Top-level report object."""

    scanner: str
    files_scanned: int
    violations: list[Violation]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tracked_files() -> list[str]:
    """Return tracked file paths relative to the repository root."""
    result = subprocess.run(  # noqa: S603
        [_GIT_EXECUTABLE, "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _repo_root() -> Path:
    """Return the repository root as a Path."""
    return Path(
        subprocess.run(  # noqa: S603
            [_GIT_EXECUTABLE, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def _sanitize_snippet(line: str, start: int, end: int) -> str:
    """Return a truncated excerpt around ``line[start:end]``."""
    lo = max(0, start - _SNIPPET_CONTEXT_CHARS)
    hi = min(len(line), end + _SNIPPET_CONTEXT_CHARS)
    prefix = line[lo:start]
    matched = line[start:end]
    suffix = line[end:hi]
    keep = matched[:_SNIPPET_KEEP_CHARS]
    masked = keep + "..." if len(matched) > _SNIPPET_KEEP_CHARS else keep
    if lo > 0 or hi < len(line):
        snippet = f"...{prefix}{masked}{suffix}..."
    else:
        snippet = f"{prefix}{masked}{suffix}"
    if len(snippet) > _SNIPPET_MAX_CHARS:
        snippet = snippet[: _SNIPPET_MAX_CHARS - 3] + "..."
    return snippet


def _strip_docs_code(text: str) -> str:
    """Replace fenced and inline code spans in Markdown with spaces.

    Absolute paths are allowed in documentation only when they are inside a
    code span or fenced block; this function produces a version of the text
    that can be safely scanned for the disallowed cases.
    """
    lines = text.splitlines()
    output_lines: list[str] = []
    in_fence = False
    for line in lines:
        fence_match = re.match(r"^(\s*)```", line)
        if fence_match:
            in_fence = not in_fence
            # Keep the line number but blank the content to preserve offsets.
            output_lines.append(" " * len(line))
            continue
        if in_fence:
            output_lines.append(" " * len(line))
            continue
        # Inline code spans: `...`
        line = re.sub(r"`[^`]*`", lambda m: " " * (m.end() - m.start()), line)
        output_lines.append(line)
    return "\n".join(output_lines)


def _collect_sensitive_json_keys(obj: object, path: str = "") -> list[str]:
    """Recursively collect sensitive JSON keys present in *obj*."""
    findings: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _SENSITIVE_JSON_KEYS:
                findings.append(f"{path}.{key}" if path else key)
            findings.extend(_collect_sensitive_json_keys(value, f"{path}.{key}" if path else key))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            findings.extend(_collect_sensitive_json_keys(item, f"{path}[{index}]"))
    return findings


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _scan_text_patterns(
    line: str,
    line_idx: int,
    file_path: str,
) -> list[Violation]:
    """Return local-path, credential and UUIDv7 violations for a single line."""
    violations: list[Violation] = []
    for match in _LOCAL_PATH_PATTERN.finditer(line):
        violations.append(
            Violation(
                kind="absolute_local_path",
                file=file_path,
                line=line_idx,
                snippet=_sanitize_snippet(line, match.start(), match.end()),
            )
        )
    for name, pattern, _kind in _CREDENTIALS_COMPILED:
        for match in pattern.finditer(line):
            violations.append(
                Violation(
                    kind=f"credential_pattern ({name})",
                    file=file_path,
                    line=line_idx,
                    snippet=_sanitize_snippet(line, match.start(), match.end()),
                )
            )
    for match in _UUIDV7_PATTERN.finditer(line):
        violations.append(
            Violation(
                kind="t7_uuidv7",
                file=file_path,
                line=line_idx,
                snippet=_sanitize_snippet(line, match.start(), match.end()),
            )
        )
    return violations


def _scan_json_keys(text: str, file_path: str) -> list[Violation]:
    """Return violations for sensitive JSON keys present in *text*."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    violations: list[Violation] = []
    for key_path in _collect_sensitive_json_keys(data):
        violations.append(
            Violation(
                kind=f"sensitive_json_key ({key_path})",
                file=file_path,
                line=0,
                snippet=key_path,
            )
        )
    return violations


def _scan_file(file_path: str, repo_root: Path) -> list[Violation]:
    """Scan a single tracked file and return its violations."""
    full_path = repo_root / file_path
    violations: list[Violation] = []

    try:
        size = full_path.stat().st_size
    except OSError as exc:
        return [Violation(kind="file_stat_error", file=file_path, line=0, snippet=str(exc))]

    if size > _SIZE_LIMIT_BYTES:
        violations.append(
            Violation(
                kind=f"oversize_file ({size / (1024 * 1024):.2f} MiB > 5 MiB)",
                file=file_path,
                line=0,
                snippet="",
            )
        )

    ext = Path(file_path).suffix.lower()
    if ext in _BINARY_EXTENSIONS:
        violations.append(
            Violation(
                kind=f"binary_extension ({ext})",
                file=file_path,
                line=0,
                snippet="",
            )
        )
        return violations

    try:
        text = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [Violation(kind="file_read_error", file=file_path, line=0, snippet=str(exc))]

    # For documentation, strip code spans before scanning for local paths or
    # credential patterns; backticked examples in docs are allowed as policy
    # illustrations.
    scan_text = _strip_docs_code(text) if file_path.startswith("docs/") else text

    for line_idx, line in enumerate(scan_text.splitlines(), start=1):
        violations.extend(_scan_text_patterns(line, line_idx, file_path))

    if ext in {".json", ".jsonc"} or file_path.endswith(".json"):
        violations.extend(_scan_json_keys(text, file_path))

    return violations


def _apply_file_allowlist(violations: list[Violation]) -> list[Violation]:
    """Drop violations from files known to contain synthetic fixtures."""
    allowed = set(_PATH_ALLOWLIST_FILES)
    return [v for v in violations if v.file not in allowed]


def scan() -> Report:
    """Scan the tracked worktree and return a boundary report."""
    repo_root = _repo_root()
    all_violations: list[Violation] = []
    files_scanned = 0

    for file_path in _tracked_files():
        files_scanned += 1
        all_violations.extend(_scan_file(file_path, repo_root))

    all_violations = _apply_file_allowlist(all_violations)

    return Report(
        scanner="public_boundary/v1",
        files_scanned=files_scanned,
        violations=all_violations,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """Entry point: scan, print JSON, exit 1 if violations exist."""
    report = scan()
    print(
        json.dumps(
            asdict(report),
            indent=2,
            default=str,
        )
    )
    return 1 if report.violations else 0


if __name__ == "__main__":
    sys.exit(main())
