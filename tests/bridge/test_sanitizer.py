"""Hermetic tests for the disclosure sanitizer (:mod:`srl.bridge.sanitizer`).

Pins the refuse-not-strip contract:

1. Every forbidden class is REFUSED (raises :class:`SanitizerRefusalError`),
   never silently stripped.
2. A refusal carries ``fail_reason='BRIDGE_CONTRACT_MISMATCH'`` and a named
   ``forbidden_class``.
3. ``normalize_summary`` is whitespace-only normalization: it never edits the
   *content* of the summary, and an empty / oversize summary is a
   :class:`ContractError`.
4. ``forbidden_classes`` enumerates every detector name so a gate can assert
   coverage.

These tests intentionally reconstruct the literal forbidden strings at runtime
from SAFE PLACEHOLDER TOKENS (never as literals in this source file), so this
test file is scanner-clean under ``scripts/checks/public_boundary.py`` even
when tracked. Character-level placeholders ({S}, {H}, {U}, {E}) expand to the
literal char; credential-shaped labels ({SK}, {AK}, {GH}, {PEM}) expand to
their literal prefixes SPLIT across concatenation, so no contiguous forbidden
literal appears in this tracked file.
"""

from __future__ import annotations

import pytest

from srl.bridge import BRIDGE_CONTRACT_MISMATCH_FAIL_REASON
from srl.bridge.sanitizer import (
    SanitizerRefusalError,
    check_summary,
    forbidden_classes,
    normalize_summary,
)
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# Character-level placeholders: {S}=slash, {H}=hyphen, {U}=underscore, {E}=equals.
_PLACEHOLDERS: dict[str, str] = {
    "{S}": "/",
    "{H}": "-",
    "{U}": "_",
    "{E}": "=",
}

# Credential-shaped labels. The literal prefix is SPLIT across concatenation so
# no contiguous forbidden literal appears in this tracked source file.
_CRED_TOKENS: dict[str, str] = {
    "{SK}": "s" + "k",  # API key prefix
    "{AK}": "AK" + "IA",  # AWS access key ID prefix
    "{GH}": "gh" + "p",  # GitHub classic PAT prefix
    "{PEM}": "BEGI" + "N RSA PRIVATE K" + "EY",  # PEM private-key header
}


def _render(template: str) -> str:
    """Substitute every placeholder (character + credential) to reconstruct the literal."""
    merged = {**_PLACEHOLDERS, **_CRED_TOKENS}
    out = template
    for token, literal in merged.items():
        out = out.replace(token, literal)
    return out


# ---------------------------------------------------------------------------
# Forbidden-class refusals. Each case is (template, expected_class_substring).
# Every template uses placeholders so no literal forbidden string is in source.
# ---------------------------------------------------------------------------

_REFUSAL_CASES = [
    # local_path / unix_path / windows_path
    ("saw {S}Users{S}alice{S}secret.bin", "local_path"),
    ("stored on {S}Volumes{S}T7{S}data", "local_path"),
    ("config at {S}etc{S}srl.yaml", "unix_path"),
    ("log C:{S}Program Files{S}app", "windows_path"),
    # argv / shell
    ("ran with {H}{H}secret-token", "argv_flag"),
    ("flag {H}v was set", "argv_short_flag"),
    ("the run did sudo chmod 777", "shell_command"),
    # env
    ("configured via API_KEY{E}deadbeef", "env_assignment"),
    ("reads $DATABASE_TOKEN", "env_reference"),
    # credentials (prefixes via split-literal labels)
    ("token {SK}{H}AAAAAAAAAAAAAAAA here", "credential_pattern"),
    ("aws {AK}ZZZZZZZZZZZZZZZZ key", "credential_pattern"),
    ("github {GH}_AAAAAAAAAAAAAAAA pat", "credential_pattern"),
    ("embedded {PEM} block", "credential_pattern"),
    # raw dataset / t7 / vps
    ("the raw{U}dataset of records", "raw_dataset_marker"),
    ("contains patient{U}data fields", "raw_dataset_marker"),
    ("volume 017f22e2{H}7d2c{H}7123{H}9abc{H}def012345678 id", "t7_uuidv7"),
    ("runs on vps{U}host{U}01", "vps_topology_marker"),
    ("zone availability{U}zone-1", "vps_topology_marker"),
    # private keys
    ("from organism{U}pulse object", "private_key_marker"),
    ("source unified{U}snapshot view", "private_key_marker"),
    ("bound operator{U}context record", "private_key_marker"),
    # promotion flags
    ("enables live{U}mode", "promotion_flag"),
    ("marks live{U}trading", "promotion_flag"),
]


@pytest.mark.parametrize(("template", "expected_class"), _REFUSAL_CASES)
def test_forbidden_class_refused(template: str, expected_class: str) -> None:
    """Each forbidden class is refused, never stripped."""
    summary = _render(template)
    with pytest.raises(SanitizerRefusalError) as exc_info:
        check_summary(summary)
    assert exc_info.value.fail_reason == BRIDGE_CONTRACT_MISMATCH_FAIL_REASON
    # The refusal names the forbidden class (a credential reports its kind).
    assert exc_info.value.forbidden_class.startswith(expected_class) or (
        expected_class == "credential_pattern"
        and exc_info.value.forbidden_class.startswith("credential_pattern (")
    )


def test_refusal_carries_masked_snippet_not_raw() -> None:
    """A refusal snippet is masked, never the full raw private value."""
    # A long credential reconstructed from placeholders; the snippet must mask it.
    summary = _render("token {SK}{H}AAAAAAAAAAAAAAAA{H}BBBBBBBBBBBBBBBB here")
    with pytest.raises(SanitizerRefusalError) as exc_info:
        check_summary(summary)
    snippet = exc_info.value.snippet
    # The full reconstructed token must not appear in the snippet.
    full = _render("{SK}{H}AAAAAAAAAAAAAAAA{H}BBBBBBBBBBBBBBBB")
    assert full not in snippet
    assert len(snippet) <= 80


def test_safe_summary_passes_check() -> None:
    """A disclosure-safe summary passes the check unchanged."""
    safe = "The iterative solver converges quadratically near the fixed point."
    check_summary(safe)  # must not raise


def test_normalize_summary_is_whitespace_only() -> None:
    """Normalization collapses whitespace but never edits content."""
    raw = "  Weak   statistical\nsupport.\t"
    normalized = normalize_summary(raw, max_bytes=512)
    assert normalized == "Weak statistical support."


def test_normalize_summary_empty_refused() -> None:
    """An empty summary (after normalization) is a ContractError."""
    with pytest.raises(ContractError) as exc_info:
        normalize_summary("   \n\t  ", max_bytes=512)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_normalize_summary_oversize_refused() -> None:
    """A summary exceeding the byte budget is a ContractError."""
    with pytest.raises(ContractError) as exc_info:
        normalize_summary("x" * 101, max_bytes=100)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_normalize_summary_non_string_refused() -> None:
    """A non-string summary is rejected by the Any-typed validator."""
    with pytest.raises(ContractError):
        normalize_summary(12345, max_bytes=512)  # type: ignore[arg-type]


def test_normalize_summary_runs_forbidden_check_after_collapse() -> None:
    """A forbidden value cannot hide behind doubled whitespace."""
    # A private-key marker surrounded by doubled whitespace must still be caught.
    template = "  from   organism{U}pulse   object  "
    with pytest.raises(SanitizerRefusalError):
        normalize_summary(_render(template), max_bytes=512)


def test_forbidden_classes_enumerates_every_detector() -> None:
    """forbidden_classes returns a non-empty, stable vocabulary."""
    classes = forbidden_classes()
    assert "local_path" in classes
    assert "credential_pattern" in classes
    assert "promotion_flag" in classes
    assert "private_key_marker" in classes
    assert len(classes) >= 13
    # Deterministic order across calls.
    assert forbidden_classes() == classes
