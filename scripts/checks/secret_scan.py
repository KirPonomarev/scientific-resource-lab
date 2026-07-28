"""Stdlib secret scanner for tracked files in CI.

The scanner walks every file returned by ``git ls-files``, decodes it as UTF-8
(with replacement so binary files do not crash the scan), and applies a small
set of deterministic regex patterns that match concrete secret shapes rather
than the English word "secret".

Patterns
--------
- GitHub classic PATs, OAuth tokens, and fine-grained PATs.
- ``sk-`` API keys (OpenAI-style and similar).
- AWS access key IDs (``AKIA...``).
- Slack bot tokens (``xoxb-...``).
- PEM private key blocks.
- JWT-shaped blobs (``eyJ...eyJ...``).
- High-entropy hex runs of 64 or more characters.

Allowlist
---------
Long-hex matches are compared against an allowlist of SHA-256 digests of known
benign strings (fixture hashes, manifest digests, etc.).  The allowlist file
is ``scripts/checks/secret-scan-allowlist.json`` and is never scanned itself.
Likewise, ``uv.lock`` is excluded from the long-hex pattern because its sole
purpose is to record PyPI package hashes.

The report is deterministic JSON written to stdout.  A non-zero exit code means
at least one finding was not allowlisted.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Pattern table: (name, regex, kind).  Each regex is anchored to concrete token
# shapes so prose about secrets does not trigger false positives.
# ---------------------------------------------------------------------------

_PATTERN_SPECS: Final[tuple[tuple[str, str, str], ...]] = (
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

_PATTERNS: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = tuple(
    (name, re.compile(pattern), kind) for (name, pattern, kind) in _PATTERN_SPECS
)

_LONG_HEX_MIN_LEN: Final[int] = 64
_LONG_HEX_ENTROPY_THRESHOLD: Final[float] = 3.0  # bits per hex character

# Files that are known to contain benign long-hex strings by design.
_LONG_HEX_SKIP_FILES: Final[frozenset[str]] = frozenset({"uv.lock"})

# Path prefixes of files whose long-hex content is a content-hash manifest
# rather than a secret (e.g. public synthetic fixture manifests).
_LONG_HEX_SKIP_PREFIXES: Final[tuple[str, ...]] = (
    "fixtures/public/",
)

# Snippet sanitization constants.
_SNIPPET_CONTEXT_CHARS: Final[int] = 12
_SNIPPET_KEEP_CHARS: Final[int] = 4
_SNIPPET_MAX_CHARS: Final[int] = 80


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    """A single secret-scan finding."""

    pattern: str
    kind: str
    file: str
    line: int
    snippet: str


@dataclass(frozen=True)
class Report:
    """Top-level report object."""

    scanner: str
    files_scanned: int
    files_with_errors: list[str]
    findings: list[Finding]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shannon_entropy(value: str) -> float:
    """Return the Shannon entropy of *value* in bits per character."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def _sha256_digest(value: str) -> str:
    """Return the lowercase hex SHA-256 digest of *value*."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sanitize_snippet(line: str, start: int, end: int) -> str:
    """Return a short, sanitized excerpt of ``line`` around [start:end]."""
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


_GIT_EXECUTABLE: Final[str] = shutil.which("git") or "git"


def _tracked_files() -> list[str]:
    """Return tracked file paths relative to the repository root."""
    result = subprocess.run(  # noqa: S603
        [_GIT_EXECUTABLE, "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _load_allowlist(path: Path) -> set[str]:
    """Load the set of allowed SHA-256 digests from *path*.

    The allowlist is strictly digest-only: each entry records the SHA-256 of a
    benign string and a reason, never the literal string itself.  If an entry
    contains a ``sample`` field, the allowlist has been reverted to the unsafe
    literal-token format and the scanner fails closed.
    """
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    entries = data.get("entries", {})
    for digest, meta in entries.items():
        if "sample" in meta:
            raise ValueError(
                f"Allowlist entry {digest} contains a literal 'sample' field; "
                "store only SHA-256 digests and reasons."
            )
    return set(entries.keys())


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _scan_credential_patterns(
    line: str,
    line_idx: int,
    file_path: str,
    allowed_digests: set[str],
) -> list[Finding]:
    """Return credential-pattern findings for a single line."""
    findings: list[Finding] = []
    for name, pattern, kind in _PATTERNS:
        for match in pattern.finditer(line):
            matched = match.group(0)
            if _sha256_digest(matched) in allowed_digests:
                continue
            findings.append(
                Finding(
                    pattern=name,
                    kind=kind,
                    file=file_path,
                    line=line_idx,
                    snippet=_sanitize_snippet(line, match.start(), match.end()),
                )
            )
    return findings


def _scan_long_hex(
    line: str,
    line_idx: int,
    file_path: str,
    allowed_digests: set[str],
) -> list[Finding]:
    """Return long-hex findings for a single line, skipped for known hash files."""
    if file_path in _LONG_HEX_SKIP_FILES:
        return []
    if any(file_path.startswith(prefix) for prefix in _LONG_HEX_SKIP_PREFIXES):
        return []
    findings: list[Finding] = []
    for match in re.finditer(r"\b[0-9a-fA-F]{64,}\b", line):
        matched = match.group(0)
        if len(matched) < _LONG_HEX_MIN_LEN:
            continue
        if _shannon_entropy(matched) < _LONG_HEX_ENTROPY_THRESHOLD:
            continue
        if _sha256_digest(matched) in allowed_digests:
            continue
        findings.append(
            Finding(
                pattern="long_hex_secret",
                kind="high-entropy long hex secret",
                file=file_path,
                line=line_idx,
                snippet=_sanitize_snippet(line, match.start(), match.end()),
            )
        )
    return findings


def _scan_file(
    file_path: str,
    repo_root: Path,
    allowed_digests: set[str],
) -> tuple[list[Finding], bool]:
    """Scan a single tracked file and return its findings plus a decode-error flag."""
    full_path = repo_root / file_path
    findings: list[Finding] = []
    decode_error = False

    try:
        raw = full_path.read_bytes()
    except OSError:
        return [], True

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        decode_error = True

    for line_idx, line in enumerate(text.splitlines(), start=1):
        findings.extend(_scan_credential_patterns(line, line_idx, file_path, allowed_digests))
        findings.extend(_scan_long_hex(line, line_idx, file_path, allowed_digests))

    return findings, decode_error


def scan(repo_root: Path | None = None) -> Report:
    """Scan the entire tracked worktree and return a report."""
    if repo_root is None:
        repo_root = Path(
            subprocess.run(  # noqa: S603
                [_GIT_EXECUTABLE, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )

    allowlist_path = repo_root / "scripts" / "checks" / "secret-scan-allowlist.json"
    allowed_digests = _load_allowlist(allowlist_path)

    files_with_errors: list[str] = []
    all_findings: list[Finding] = []
    files_scanned = 0

    for file_path in _tracked_files():
        # The allowlist itself contains long hex digests; do not scan it.
        if file_path == str(Path("scripts/checks/secret-scan-allowlist.json")):
            continue
        files_scanned += 1
        findings, decode_error = _scan_file(file_path, repo_root, allowed_digests)
        if decode_error:
            files_with_errors.append(file_path)
        all_findings.extend(findings)

    return Report(
        scanner="secret_scan/v1",
        files_scanned=files_scanned,
        files_with_errors=files_with_errors,
        findings=all_findings,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """Entry point: scan, print JSON, exit 1 if findings exist."""
    report = scan()
    print(
        json.dumps(
            asdict(report),
            indent=2,
            default=str,
        )
    )
    return 1 if report.findings else 0


if __name__ == "__main__":
    sys.exit(main())
