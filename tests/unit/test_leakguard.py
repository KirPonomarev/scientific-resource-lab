"""Unit tests for the public-leak guard (``srl.autonomy.leakguard``).

The guard scans diff text for material that must never be public: absolute
POSIX home paths, mounted volume paths, and secret token shapes. These tests
pin:

1. Each pattern class is detected (home paths, volumes, the GitHub PAT
   variants, ``sk-``, AWS access key IDs, PEM private keys, long hex).
2. A clean diff passes with no findings.
3. False-positive guard: the word "secret" in prose is not flagged, and
   short hex (like a color or abbreviated sha) is not flagged.
4. The bytes entry point reports a typed scan failure for undecodable input.
"""

from __future__ import annotations

import pytest

from srl.autonomy.leakguard import (
    PUBLIC_LEAK_FAIL_REASON,
    LeakViolation,
    scan_bytes,
    scan_diff,
)

# --- Obviously fake fixture values. NEVER real credentials. -------------------
# The EXAMPLE prefix / placeholder bodies make these visibly synthetic while
# matching the pattern shapes the guard must detect.
_FAKE_GHP = "ghp_EXAMPLE0000000000000000000000000000"
_FAKE_GHO = "gho_EXAMPLE0000000000000000000000000000"
_FAKE_PAT = "github_pat_EXAMPLE0000000000000000000000000000"
_FAKE_SK = "sk-EXAMPLE000000000000000000000000"
_FAKE_AKIA = "AKIAIOSFODNN7EXAMPLE"
_FAKE_HEX = "a" * 64  # 64 hex chars, secret-shaped


def _scan(text: str) -> list[LeakViolation]:
    """Scan helper returning the findings list."""
    return scan_diff(text)


def test_users_home_path_detected() -> None:
    """A /Users/<name> absolute home path is flagged."""
    findings = _scan("path = '/Users/alice/code'\n")
    assert findings
    assert any(v.pattern_name == "absolute_users_home" for v in findings)
    assert all(v.fail_reason == PUBLIC_LEAK_FAIL_REASON for v in findings)


def test_linux_home_path_detected() -> None:
    """A /home/<name> absolute home path is flagged."""
    findings = _scan("home = '/home/bob/work'\n")
    assert findings
    assert any(v.pattern_name == "absolute_home" for v in findings)


def test_volumes_path_detected() -> None:
    """A /Volumes/<name> mounted volume path is flagged."""
    findings = _scan("disk = '/Volumes/MacHD/data'\n")
    assert findings
    assert any(v.pattern_name == "volumes_path" for v in findings)


def test_github_classic_pat_detected() -> None:
    """A ghp_ token shape is flagged."""
    findings = _scan(f"token = '{_FAKE_GHP}'\n")
    assert any(v.pattern_name == "github_pat_classic" for v in findings)


def test_github_oauth_token_detected() -> None:
    """A gho_ token shape is flagged."""
    findings = _scan(f"token = '{_FAKE_GHO}'\n")
    assert any(v.pattern_name == "github_oauth_token" for v in findings)


def test_github_fine_grained_pat_detected() -> None:
    """A github_pat_ fine-grained token shape is flagged."""
    findings = _scan(f"token = '{_FAKE_PAT}'\n")
    assert any(v.pattern_name == "github_fine_grained_pat" for v in findings)


def test_sk_api_key_detected() -> None:
    """An sk- API key shape is flagged."""
    findings = _scan(f"key = '{_FAKE_SK}'\n")
    assert any(v.pattern_name == "sk_api_key" for v in findings)


def test_aws_access_key_id_detected() -> None:
    """An AKIA... AWS access key ID shape is flagged."""
    findings = _scan(f"aws = '{_FAKE_AKIA}'\n")
    assert any(v.pattern_name == "aws_access_key_id" for v in findings)


def test_pem_private_key_detected() -> None:
    """A PEM private key header is flagged."""
    findings = _scan("-----BEGIN RSA PRIVATE KEY-----\n")
    assert any(v.pattern_name == "pem_private_key" for v in findings)


def test_pem_ec_private_key_detected() -> None:
    """A PEM EC private key header is flagged (any key type)."""
    findings = _scan("-----BEGIN EC PRIVATE KEY-----\n")
    assert any(v.pattern_name == "pem_private_key" for v in findings)


def test_long_hex_secret_detected() -> None:
    """A long hex run (>=40 hex) is flagged as a secret-shaped blob."""
    findings = _scan(f"digest = '{_FAKE_HEX}'\n")
    assert any(v.pattern_name == "long_hex_secret" for v in findings)


def test_clean_diff_passes() -> None:
    """A diff with no private content produces no findings."""
    clean = "diff --git a/src/srl/x.py b/src/srl/x.py\n+def add(a, b):\n+    return a + b\n"
    assert _scan(clean) == []


def test_word_secret_in_prose_is_not_flagged() -> None:
    """The word 'secret' in prose is not a violation (false-positive guard)."""
    prose = (
        "# This module documents the secret scanning policy.\n"
        "# Secrets must never be committed.\n"
        "The secret value is stored in the vault, not the repo.\n"
    )
    assert _scan(prose) == []


def test_short_hex_is_not_flagged() -> None:
    """Short hex (a color or abbreviated sha) is not a secret-shaped blob."""
    benign_text = "color = #ff0000\nsha = 1a2b3c4d5e6f\n"
    assert _scan(benign_text) == []


def test_multiple_findings_on_one_line_report_all() -> None:
    """Multiple matches on one line each produce a finding."""
    line = f"t1='{_FAKE_GHP}' t2='/Users/alice/x'\n"
    findings = _scan(line)
    names = {v.pattern_name for v in findings}
    assert "github_pat_classic" in names
    assert "absolute_users_home" in names


def test_findings_carry_line_numbers() -> None:
    """A finding reports the 1-based line number of its match."""
    text = "clean line\n" + f"token = '{_FAKE_GHP}'\n"
    findings = _scan(text)
    assert findings
    assert all(v.line == 2 for v in findings)


def test_empty_string_is_clean() -> None:
    """An empty input produces no findings."""
    assert _scan("") == []


def test_snippet_is_sanitized() -> None:
    """A finding snippet does not echo the full matched token."""
    findings = _scan(f"x '{_FAKE_GHP}'\n")
    assert findings
    snippet = findings[0].snippet
    # The full token must not appear verbatim in the sanitized snippet.
    assert _FAKE_GHP not in snippet


def test_scan_bytes_clean() -> None:
    """Decodable bytes scan like text."""
    assert scan_bytes(b"clean text here") == []


def test_scan_bytes_undecodable_reports_scan_failure() -> None:
    """Undecodable bytes yield a single SECRET_SCAN_FAILED finding."""
    findings = scan_bytes(b"\xff\xfe\x00not utf8")
    assert len(findings) == 1
    assert findings[0].fail_reason == "SECRET_SCAN_FAILED"


@pytest.mark.parametrize(
    "fixture",
    [
        f"/Users/alice/x {_FAKE_GHP}",
        f"/home/bob/y {_FAKE_GHO}",
        f"/Volumes/Mac {_FAKE_PAT}",
        f"sk- {_FAKE_SK}",
        f"aws {_FAKE_AKIA}",
        "BEGIN RSA PRIVATE KEY",
        f"hex {_FAKE_HEX}",
    ],
)
def test_each_pattern_class_parametrized(fixture: str) -> None:
    """Each pattern class is detected (parametrized over all classes)."""
    assert _scan(fixture), f"failed to detect a pattern in: {fixture}"
