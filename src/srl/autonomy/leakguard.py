"""Pre-commit public-leak guard for autonomous work.

Before any commit lands on the public repository, the staged diff content is
scanned for material that must never be public: absolute local paths that
identify an operator or machine (``/Users/<name>``, ``/home/<name>``,
``/Volumes/...``), and secret tokens (GitHub PATs, ``sk-`` API keys, AWS
access key IDs, PEM private key blocks, long hex secrets).

The guard is a pure function over text. It performs no filesystem mutation
and no network access. A caller invokes :func:`scan_diff` with the diff
content and receives a list of typed :class:`LeakViolation` records. A
non-empty list means the commit must be refused pre-commit.

Failure routing
---------------
Each violation carries a typed ``fail_reason``:

- ``PUBLIC_LEAK_DETECTED`` — a private path or a recognizable secret token was
  found in the diff. This is a hard stop under ``AutonomyPolicy/v1``.
- ``SECRET_SCAN_FAILED`` — reserved for the case where the scanner itself
  could not complete deterministically (for example, input it cannot decode).
  In the pure-text model the scanner always completes, so this reason is
  emitted only by the explicit ``decode failure`` path; the v1 scanner does
  not guess.

False-positive guard
--------------------
The word "secret" appearing in prose is *not* a violation. The patterns match
concrete token shapes (``ghp_...``, ``AKIA...``, ``BEGIN ... PRIVATE KEY``)
and absolute paths, not the English noun. This keeps documentation that
discusses secrets (like this module) clean.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

# Fail reasons emitted by this guard. Mirror the fail-reason registry. The
# scan-failure constant is named without the "SECRET" substring so the
# hardcoded-password linter (S105) does not misfire on the fail-reason token.
PUBLIC_LEAK_FAIL_REASON: Final[str] = "PUBLIC_LEAK_DETECTED"
SCAN_FAILURE_FAIL_REASON: Final[str] = "SECRET_SCAN_FAILED"

# A "long hex secret" is a run of hex digits long enough to be plausibly
# secret. The threshold is 64 hex digits, which covers a SHA-256 digest or a
# 32-byte key. 64 is chosen over 40 (a Git SHA-1) deliberately: 40-hex runs
# appear legitimately in this repository as action-SHA pins
# (``actions/checkout@<sha>``) and abbreviated commit ids, and would produce
# false positives under any threshold <= 40. Real symmetric keys and modern
# digests are 64 hex or longer, so 64 keeps secret-detection value while
# excluding the action-pin noise.
_HEX_SECRET_MIN_LEN: Final[int] = 64

# Snippet sanitization bounds. Extracted as constants so the masking policy is
# declared in one place and free of magic-value lint.
_SNIPPET_CONTEXT_CHARS: Final[int] = 12  # chars of context on each side of a match
_SNIPPET_KEEP_CHARS: Final[int] = 4  # chars of a matched token kept visible
_SNIPPET_MAX_CHARS: Final[int] = 80  # hard cap on a diagnostic snippet length

# Pattern table. Each entry is (name, compiled regex, kind, fail_reason).
# ``kind`` is a short human label; ``fail_reason`` routes the violation.
# Notes on each pattern:
# - home paths: /Users/<name> and /home/<name>. <name> is at least one
#   path segment so we do not match the bare "/home/" string in prose about
#   home directories.
# - /Volumes/<name>: macOS mounted volume root; identifies a machine.
# - ghp_/gho_/github_pat_: GitHub token prefixes (classic and fine-grained).
# - sk-: common API key prefix (OpenAI-style and others).
# - AKIA[0-9A-Z]{16}: AWS access key ID shape.
# - BEGIN ... PRIVATE KEY: PEM private key header (any key type).
# - long hex run: >=40 hex digits, a secret-shaped blob.
_PATTERN_SPECS: Final[tuple[tuple[str, str, str, str], ...]] = (
    (
        "absolute_users_home",
        r"/Users/[A-Za-z0-9._-]+",
        "absolute POSIX home path (/Users/<name>)",
        PUBLIC_LEAK_FAIL_REASON,
    ),
    (
        "absolute_home",
        r"/home/[A-Za-z0-9._-]+",
        "absolute POSIX home path (/home/<name>)",
        PUBLIC_LEAK_FAIL_REASON,
    ),
    (
        "volumes_path",
        r"/Volumes/[A-Za-z0-9._-]+",
        "mounted volume path (/Volumes/<name>)",
        PUBLIC_LEAK_FAIL_REASON,
    ),
    (
        "github_pat_classic",
        r"ghp_[A-Za-z0-9]{16,}",
        "GitHub classic PAT token (ghp_)",
        PUBLIC_LEAK_FAIL_REASON,
    ),
    (
        "github_oauth_token",
        r"gho_[A-Za-z0-9]{16,}",
        "GitHub OAuth token (gho_)",
        PUBLIC_LEAK_FAIL_REASON,
    ),
    (
        "github_fine_grained_pat",
        r"github_pat_[A-Za-z0-9_]{16,}",
        "GitHub fine-grained PAT (github_pat_)",
        PUBLIC_LEAK_FAIL_REASON,
    ),
    (
        "sk_api_key",
        r"sk-[A-Za-z0-9]{16,}",
        "API key (sk-)",
        PUBLIC_LEAK_FAIL_REASON,
    ),
    (
        "aws_access_key_id",
        r"AKIA[0-9A-Z]{16}",
        "AWS access key ID (AKIA...)",
        PUBLIC_LEAK_FAIL_REASON,
    ),
    (
        "pem_private_key",
        r"BEGIN [A-Z ]*PRIVATE KEY",
        "PEM private key block",
        PUBLIC_LEAK_FAIL_REASON,
    ),
    (
        "long_hex_secret",
        rf"\b[0-9a-fA-F]{{{_HEX_SECRET_MIN_LEN},}}\b",
        f"long hex secret (>={_HEX_SECRET_MIN_LEN} hex digits)",
        PUBLIC_LEAK_FAIL_REASON,
    ),
)

# Pre-compile for speed and to fail fast on a malformed pattern at import.
_PATTERNS: Final[tuple[tuple[str, re.Pattern[str], str, str], ...]] = tuple(
    (name, re.compile(pat), kind, fail_reason) for (name, pat, kind, fail_reason) in _PATTERN_SPECS
)


@dataclass(frozen=True)
class LeakViolation:
    """A single leak-guard finding.

    Attributes
    ----------
    pattern_name:
        Stable identifier for the pattern that matched (e.g. ``github_pat_classic``).
    kind:
        Human-readable description of what was matched.
    line:
        The 1-based line number in the scanned text where the match begins.
    snippet:
        A short, sanitized excerpt around the match for diagnostics. The
        snippet is truncated and never contains the full secret token.
    fail_reason:
        Typed fail reason (``PUBLIC_LEAK_DETECTED`` or ``SECRET_SCAN_FAILED``)
        for routing through the resume/fail-reason machinery.
    """

    pattern_name: str
    kind: str
    line: int
    snippet: str
    fail_reason: str


def _sanitize_snippet(line: str, start: int, end: int) -> str:
    """Return a short, sanitized excerpt of ``line`` around [start:end].

    The excerpt is bounded in width and replaces the matched token's interior
    with ``...`` so a diagnostic never echoes a full secret back. Keeping a
    few characters of prefix/suffix lets a human confirm the pattern class
    without recovering the credential.
    """
    lo = max(0, start - _SNIPPET_CONTEXT_CHARS)
    hi = min(len(line), end + _SNIPPET_CONTEXT_CHARS)
    prefix = line[lo:start]
    matched = line[start:end]
    suffix = line[end:hi]
    # Show a few chars of the matched token, then mask the rest.
    keep = matched[:_SNIPPET_KEEP_CHARS]
    masked = keep + "..." if len(matched) > _SNIPPET_KEEP_CHARS else keep
    snippet = (
        f"...{prefix}{masked}{suffix}..."
        if (lo > 0 or hi < len(line))
        else (f"{prefix}{masked}{suffix}")
    )
    # Hard cap the snippet length so a pathological line cannot flood logs.
    if len(snippet) > _SNIPPET_MAX_CHARS:
        snippet = snippet[: _SNIPPET_MAX_CHARS - 3] + "..."
    return snippet


def scan_diff(diff_text: str) -> list[LeakViolation]:
    """Scan diff text for private paths and secret tokens.

    Parameters
    ----------
    diff_text:
        The text content to scan. Typically the staged diff (added lines),
        but any text is accepted. Only *added* lines should be passed by a
        caller doing pre-commit checks; this function scans whatever it is
        given.

    Returns
    -------
    list[LeakViolation]
        Findings in line order. An empty list means the text is clean under
        the v1 patterns. The list is never ``None``.

    Raises
    ------
    LeakViolation
        Never raised for content findings. A scan failure (undecodable bytes)
        is reported by :func:`scan_bytes`, not here; this str entry point
        always completes.

    Notes
    -----
    This function is pure: same input yields same output, with no I/O. The
    word "secret" in prose is not flagged; only concrete token shapes and
    absolute paths are.
    """
    if diff_text == "":
        return []

    violations: list[LeakViolation] = []
    # Split keeping line breaks out of the content we index. We scan each line
    # independently so a finding reports a usable 1-based line number.
    lines = diff_text.splitlines()
    for idx, line in enumerate(lines, start=1):
        for name, pattern, kind, fail_reason in _PATTERNS:
            for match in pattern.finditer(line):
                violations.append(
                    LeakViolation(
                        pattern_name=name,
                        kind=kind,
                        line=idx,
                        snippet=_sanitize_snippet(line, match.start(), match.end()),
                        fail_reason=fail_reason,
                    )
                )
    # Stable order: by line, then by the order patterns were declared so
    # diagnostics are deterministic across runs and platforms.
    return violations


def scan_bytes(diff_bytes: bytes) -> list[LeakViolation]:
    """Scan raw bytes, decoding as UTF-8 and reporting a scan failure otherwise.

    This is the bytes-entry counterpart to :func:`scan_diff`. It decodes the
    input strictly as UTF-8; if the input is not valid UTF-8 the scanner
    cannot complete deterministically and a single
    ``fail_reason='SECRET_SCAN_FAILED'`` finding is returned (not raised), so
    a caller routing findings through the resume/fail-reason registry sees
    the typed reason rather than a :class:`UnicodeDecodeError`.
    """
    try:
        text = diff_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return [
            LeakViolation(
                pattern_name="undecodable_input",
                kind="scanner received bytes that are not valid UTF-8",
                line=0,
                snippet="<undecodable>",
                fail_reason=SCAN_FAILURE_FAIL_REASON,
            )
        ]
    return scan_diff(text)


def any_leak(violations: Iterable[LeakViolation]) -> bool:
    """Convenience: True iff ``violations`` contains at least one finding.

    A separate helper so callers can write ``if any_leak(scan_diff(text))``
    without an extra materialized list test, and so the "is this a leak"
    predicate has one named home.
    """
    for _ in violations:
        return True
    return False
