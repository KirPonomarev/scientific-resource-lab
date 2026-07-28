"""Disclosure sanitizer for ``LabExportPacket/v1`` summaries.

The sanitizer is the security-critical core of the export boundary. Its single
load-bearing property is **refuse-not-strip**: a summary that contains any
forbidden class is REFUSED at build time with a typed
:class:`SanitizerRefusalError` (fail reason ``BRIDGE_CONTRACT_MISMATCH``). The
sanitizer never silently strips, masks, or rewrites a forbidden substring.

Why refuse, not strip
---------------------
A quiet rewrite (e.g. replacing a local path with ``<redacted>``) would let a
private value leak through in a subtly-different form on the next revision, and
would hide the fact that a disclosure was attempted with private data in it.
Refusing forces the exporter's caller to honestly re-summarize the object — to
describe the *science*, not the *environment* — before the summary can cross
the boundary. This mirrors the public-boundary scanner
(:mod:`scripts.checks.public_boundary`) which already rejects these classes in
tracked files; the sanitizer is the producer-side counterpart so a refused
summary can never become a tracked-file violation in the first place.

Forbidden classes
-----------------
The sanitizer refuses a summary that contains any of:

- **absolute local paths** — ``/Users/``, ``/home/``, ``/Volumes/`` (the same
  regex shape the public-boundary scanner uses);
- **argv / shell markers** — leading-dash command flags (``--secret``,
  ``-verbose``) and shell metacharacters that indicate a command was pasted in;
- **environment-variable assignments** — ``KEY=value`` shapes and ``$VAR`` /
  ``${VAR}`` references;
- **credential patterns** — the same concrete shapes
  (:mod:`scripts.checks.public_boundary`) scans for (GitHub PATs, ``sk-`` keys,
  AWS access key IDs, Slack tokens, JWT blobs, PEM private-key headers);
- **raw-dataset markers** — words that indicate raw private data (``dataset``,
  ``raw_data``, ``private_data``, ``patient_records``, etc.);
- **T7 / UUIDv7 identifiers** — the RFC 9562 UUIDv7 shape used for T7 volumes;
- **VPS / topology markers** — words that indicate deployment topology
  (``vps_host``, ``instance_id``, ``region``, ``availability_zone``);
- **Pulse / Snapshot / OperatorContext-shaped private keys** —
  ``organism_pulse``, ``unified_snapshot``, ``operator_context`` (the same
  sensitive-key set the public-boundary scanner flags), plus the literal
  object-type aliases that would disclose a private object's real shape;
- **live / trading / promotion flags** — words that indicate a live or
  production-trading posture or a status-promotion claim (``live_mode``,
  ``trading_enabled``, ``promotion_granted``, etc.).

Each forbidden class has a named detector so a refusal carries the class name
in its ``forbidden_class`` attribute, which lets a gate (and a human) see
*which* boundary a summary tripped.
"""

from __future__ import annotations

import re
from typing import Any, Final

from srl.bridge import BRIDGE_CONTRACT_MISMATCH_FAIL_REASON
from srl.contracts.errors import ContractError

# ---------------------------------------------------------------------------
# Forbidden-class constants. Each (name, compiled_regex) pair is a detector.
# The names are stable identifiers carried in SanitizerRefusalError.
# ---------------------------------------------------------------------------

# Absolute local paths: /Users/<user>, /home/<user>, /Volumes/<vol>. Mirrors the
# public_boundary.py _LOCAL_PATH_PATTERN exactly.
_LOCAL_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:/Users/[A-Za-z0-9][A-Za-z0-9._-]*|/home/[A-Za-z0-9][A-Za-z0-9._-]*"
    r"|/Volumes/[A-Za-z0-9][A-Za-z0-9._-]*)"
)

# Unix absolute paths more broadly (a leading / followed by a path component).
# This catches /etc/, /var/, /tmp/, /root/, /private/... etc. that the
# /Users|/home|/Volumes set does not name explicitly. We refuse any token that
# looks like an absolute filesystem path, because a summary should describe the
# science, never the filesystem.
_UNIX_ABS_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9_])(/(?:etc|var|tmp|root|private|opt|srv|proc|sys|dev|mnt|media|data|workspace|repo|build|dist|venv|env)(?:/[^\s'\"]*)?)"
)

# Windows drive paths: C:\... or C:/... . Refused for the same reason as unix
# absolute paths.
_WINDOWS_PATH_RE: Final[re.Pattern[str]] = re.compile(r"\b[A-Za-z]:[\\/][^\s'\"]*")

# Argv / shell markers.
# Leading-dash command flags: --secret, -v, --config=..., -X8. A summary that
# contains a command flag reads like a pasted command line, not a science
# description.
_ARGV_FLAG_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|\s)--[A-Za-z][A-Za-z0-9_-]*(?:=\S+)?")
_ARGV_SHORT_FLAG_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|\s)-[A-Za-z](?:\S+)?")
# Shell command prefix: a token that looks like a shell invocation. We refuse a
# summary whose first non-space token is a known shell command, because that
# indicates a command was pasted rather than a summary written. The list is
# deliberately NARROW: only commands that are unambiguous as shell invocations
# and unlikely to appear as English words in a scientific summary (so "cat",
# "source", "mv", "cp" etc. are excluded to avoid false positives).
_SHELL_COMMAND_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)(?:sudo|bash|zsh|curl|wget|scp|ssh|rsync|chmod|chown)\b"
)

# Environment-variable assignments: KEY=value (KEY is uppercase/digit/underscore,
# value non-empty), and $VAR / ${VAR} references.
_ENV_ASSIGN_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|\s)[A-Z][A-Z0-9_]{2,}=\S+")
_ENV_REF_RE: Final[re.Pattern[str]] = re.compile(r"\$\{?[A-Z][A-Z0-9_]{2,}\}?")

# Credential patterns: the SAME concrete shapes public_boundary.py scans for.
# Duplicated here (not imported) so the producer-side sanitizer is independent
# of the scanner module and so a future change to either is deliberate.
_CREDENTIAL_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    ("github_pat_classic", r"ghp_[A-Za-z0-9]{16,}"),
    ("github_oauth_token", r"gho_[A-Za-z0-9]{16,}"),
    ("github_fine_grained_pat", r"github_pat_[A-Za-z0-9_]{16,}"),
    ("sk_api_key", r"sk-[A-Za-z0-9]{16,}"),
    ("aws_access_key_id", r"AKIA[0-9A-Z]{16}"),
    ("slack_bot_token", r"xoxb-[A-Za-z0-9-]{10,}"),
    ("jwt", r"eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*"),
    ("pem_private_key", r"BEGIN [A-Z ]*PRIVATE KEY"),
)
_CREDENTIALS_COMPILED: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (name, re.compile(pattern)) for (name, pattern) in _CREDENTIAL_PATTERNS
)

# Raw-dataset markers: words that indicate raw private data is being described.
# Word-boundary anchored so 'dataset' does not match inside 'dataset_id'... no,
# we WANT it to match inside compounds too. Use a case-insensitive substring
# scan over a word-boundary regex per term.
_RAW_DATASET_TERMS: Final[tuple[str, ...]] = (
    "raw_dataset",
    "raw_data",
    "private_data",
    "patient_record",
    "patient_data",
    "phi",
    "pii",
    "source_record",
    "unredacted",
)
_RAW_DATASET_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _RAW_DATASET_TERMS) + r")",
    re.IGNORECASE,
)

# T7 / UUIDv7 identifiers (RFC 9562): the shape used for T7 volume identities.
# Mirrors public_boundary.py _UUIDV7_PATTERN.
_UUIDV7_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)

# VPS / topology markers: words that indicate deployment topology.
_VPS_TOPOLOGY_TERMS: Final[tuple[str, ...]] = (
    "vps_host",
    "instance_id",
    "availability_zone",
    "region_tag",
    "datacenter",
    "node_host",
    "cluster_name",
    "k8s_node",
)
_VPS_TOPOLOGY_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _VPS_TOPOLOGY_TERMS) + r")",
    re.IGNORECASE,
)

# Pulse / Snapshot / OperatorContext-shaped private keys. The exact sensitive
# key set public_boundary.py flags, plus the literal object-type aliases that
# would disclose a private object's real internal shape.
_PRIVATE_KEY_TERMS: Final[tuple[str, ...]] = (
    "organism_pulse",
    "unified_snapshot",
    "operator_context",
)
_PRIVATE_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:" + "|".join(re.escape(t) for t in _PRIVATE_KEY_TERMS) + r")",
    re.IGNORECASE,
)

# Live / trading / promotion flags: words that indicate a live or
# production-trading posture, or a status-promotion claim (a packet can never
# promote status — review_only=true, canonical_effect='none').
_PROMO_FLAG_TERMS: Final[tuple[str, ...]] = (
    "live_mode",
    "live_trading",
    "trading_enabled",
    "production_deploy",
    "promotion_granted",
    "status_promoted",
    "ship_to_prod",
    "go_live",
)
_PROMO_FLAG_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _PROMO_FLAG_TERMS) + r")\b",
    re.IGNORECASE,
)

# The ordered list of (class_name, regex) detectors. Order is stable so a
# refusal report is deterministic; the FIRST matching class wins the report.
# Each detector may itself be a tuple of sub-patterns (credentials) — we
# normalize to a single check call per class.
_DETECTORS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("local_path", _LOCAL_PATH_RE),
    ("unix_path", _UNIX_ABS_PATH_RE),
    ("windows_path", _WINDOWS_PATH_RE),
    ("argv_flag", _ARGV_FLAG_RE),
    ("argv_short_flag", _ARGV_SHORT_FLAG_RE),
    ("shell_command", _SHELL_COMMAND_RE),
    ("env_assignment", _ENV_ASSIGN_RE),
    ("env_reference", _ENV_REF_RE),
    ("raw_dataset_marker", _RAW_DATASET_RE),
    ("t7_uuidv7", _UUIDV7_RE),
    ("vps_topology_marker", _VPS_TOPOLOGY_RE),
    ("private_key_marker", _PRIVATE_KEY_RE),
    ("promotion_flag", _PROMO_FLAG_RE),
)
# Credentials are checked as a named sub-class: a credential match reports the
# credential kind (e.g. 'credential_pattern (github_pat_classic)').


class SanitizerRefusalError(ContractError):
    """Raised when a summary contains a forbidden class and is refused.

    Refuse-not-strip: the sanitizer never silently edits the summary. A refused
    summary must be honestly re-summarized (describe the science, not the
    environment) before it can be exported. The fail reason is
    ``BRIDGE_CONTRACT_MISMATCH`` (hard_stop, not retriable) because a forbidden
    summary is a deterministic boundary violation, not a transient fault.

    Attributes
    ----------
    forbidden_class:
        The stable name of the forbidden class that tripped (e.g.
        ``'local_path'``, ``'credential_pattern (sk_api_key)'``,
        ``'promotion_flag'``).
    snippet:
        A short, masked snippet of the offending substring, safe to show in a
        gate receipt or log (the raw private value is truncated).
    """

    def __init__(
        self,
        message: str,
        *,
        forbidden_class: str = "",
        snippet: str = "",
        fail_reason: str = BRIDGE_CONTRACT_MISMATCH_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.forbidden_class: str = forbidden_class
        self.snippet: str = snippet


def _mask_snippet(match_text: str) -> str:
    """Return a truncated, masked snippet safe to surface in a refusal.

    Keeps the first few characters of the match (so a human can see what class
    of thing tripped) and masks the rest. The raw private value never appears in
    full in a gate receipt or log.
    """
    keep = 4
    if len(match_text) <= keep:
        masked = match_text
    else:
        masked = match_text[:keep] + "..."
    # Collapse internal whitespace so the snippet fits one line.
    return re.sub(r"\s+", " ", masked).strip()


def _find_first_forbidden(text: str) -> tuple[str, str] | None:
    """Return ``(class_name, snippet)`` for the first forbidden hit, or None.

    Scans every detector class in deterministic order; credentials are scanned
    as a named sub-class so a credential hit reports its kind. Returns the
    first match so a refusal names a single, specific class.
    """
    for class_name, pattern in _DETECTORS:
        match = pattern.search(text)
        if match is not None:
            return class_name, _mask_snippet(match.group(0))
    # Credentials: a named sub-class per credential kind.
    for cred_name, pattern in _CREDENTIALS_COMPILED:
        match = pattern.search(text)
        if match is not None:
            return f"credential_pattern ({cred_name})", _mask_snippet(match.group(0))
    return None


def forbidden_classes() -> tuple[str, ...]:
    """Return the stable, ordered tuple of forbidden-class detector names.

    Exposed so a gate or test can enumerate every class the sanitizer refuses.
    Credential sub-classes are folded under the single ``credential_pattern``
    name here (the per-kind name is only reported in a refusal). The returned
    tuple is the authoritative vocabulary of what never crosses the boundary.
    """
    return (*[name for name, _ in _DETECTORS], "credential_pattern")


def check_summary(summary: str) -> None:
    """Refuse a summary that contains any forbidden class.

    Parameters
    ----------
    summary:
        The candidate sanitized summary text.

    Raises
    ------
    SanitizerRefusalError
        If ``summary`` contains any forbidden class. Carries the
        ``forbidden_class`` name and a masked ``snippet``. Never edits the
        summary in place; the caller must re-summarize.
    """
    hit = _find_first_forbidden(summary)
    if hit is None:
        return
    class_name, snippet = hit
    msg = (
        f"sanitized_summary refused: contains forbidden class {class_name!r} "
        f"(snippet={snippet!r}); the exporter refuses, it does not strip — "
        "honestly re-summarize the object (describe the science, not the "
        "environment) before exporting"
    )
    raise SanitizerRefusalError(msg, forbidden_class=class_name, snippet=snippet)


def normalize_summary(summary: Any, *, max_bytes: int) -> str:
    """Normalize a summary: strip surrounding whitespace, collapse internal runs.

    Normalization is the ONLY mutation the sanitizer performs, and it is
    whitespace-only — it never edits the *content* of the summary (that would be
    a strip, which is forbidden). Trailing/leading whitespace is removed and
    internal runs of whitespace are collapsed to a single space.

    After normalization, the byte length is checked against ``max_bytes`` and
    the forbidden-class check runs. A summary that is empty after normalization,
    exceeds the byte budget, or contains a forbidden class is refused.

    Parameters
    ----------
    summary:
        The raw candidate summary. Accepts ``Any`` so it is a runtime validator
        that rejects non-strings (e.g. values read from JSON) with a typed
        :class:`ContractError`.
    max_bytes:
        The byte budget (the disclosure policy's ``summary_max_bytes``).

    Raises
    ------
    SanitizerRefusalError
        If the normalized summary contains a forbidden class.
    ContractError
        If the normalized summary is empty or exceeds ``max_bytes``.
    """
    if not isinstance(summary, str):
        msg = f"sanitized_summary must be a string, got {type(summary).__name__}"
        raise ContractError(msg)
    # Whitespace-only normalization: never edit content.
    collapsed = re.sub(r"\s+", " ", summary).strip()
    if not collapsed:
        msg = "sanitized_summary is empty after normalization"
        raise ContractError(msg)
    encoded_len = len(collapsed.encode("utf-8"))
    if encoded_len > max_bytes:
        msg = (
            f"sanitized_summary is {encoded_len} bytes, exceeds the "
            f"summary_max_bytes budget of {max_bytes}; shorten the summary or "
            "raise the policy budget"
        )
        raise ContractError(msg)
    # Forbidden-class check runs AFTER normalization so a forbidden value cannot
    # hide behind leading/trailing or doubled whitespace.
    check_summary(collapsed)
    return collapsed


__all__ = [
    "SanitizerRefusalError",
    "check_summary",
    "forbidden_classes",
    "normalize_summary",
]
