"""Unit tests for the write-scope guard (``srl.autonomy.scopes``).

The scope guard is a pre-write check: it must accept writes inside the
declared owned set and refuse writes outside it, plus refuse any path that
tries to escape the repo root via ``..`` traversal, an absolute path, or a
non-portable backslash. These tests pin all three refusal classes and the
in-scope accept, and that every refusal carries the typed fail reason
``CONTRACT_INVALID``.
"""

from __future__ import annotations

import pytest

from srl.autonomy.scopes import SCOPE_VIOLATION_FAIL_REASON, ScopeViolation, check_write

# A representative owned set: one directory prefix and one exact file.
_OWNED_DIR = frozenset({"src/srl/autonomy/"})
_OWNED_FILE = frozenset({"pyproject.toml"})


def test_in_scope_file_under_owned_dir_is_accepted() -> None:
    """A file nested under an owned directory passes."""
    # Should not raise.
    check_write("src/srl/autonomy/policy.py", _OWNED_DIR)


def test_in_scope_exact_owned_file_is_accepted() -> None:
    """An exactly-owned file path passes."""
    # Should not raise.
    check_write("pyproject.toml", _OWNED_FILE)


def test_in_scope_deeply_nested_file_is_accepted() -> None:
    """A deeply nested file under an owned directory passes."""
    # Should not raise.
    check_write("src/srl/autonomy/sub/dir/deep.py", _OWNED_DIR)


def test_out_of_scope_file_is_rejected() -> None:
    """A file outside the owned set raises ScopeViolation pre-write."""
    with pytest.raises(ScopeViolation) as exc_info:
        check_write("README.md", _OWNED_DIR)
    assert exc_info.value.fail_reason == SCOPE_VIOLATION_FAIL_REASON
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"
    assert exc_info.value.path == "README.md"


def test_out_of_scope_sibling_dir_is_rejected() -> None:
    """A file in a sibling directory (not under the owned dir) is rejected."""
    # 'src/srl/cli.py' shares a prefix substring but is not under autonomy/.
    with pytest.raises(ScopeViolation):
        check_write("src/srl/cli.py", _OWNED_DIR)


def test_dotdot_traversal_is_rejected() -> None:
    """A path containing '..' is rejected as a traversal attempt."""
    with pytest.raises(ScopeViolation) as exc_info:
        check_write("src/srl/autonomy/../../escape.py", _OWNED_DIR)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_leading_dotdot_is_rejected() -> None:
    """A leading '..' is rejected even though a parent might contain it."""
    with pytest.raises(ScopeViolation):
        check_write("../escape.txt", _OWNED_DIR)


def test_absolute_path_is_rejected() -> None:
    """An absolute path is rejected as a repo-root escape."""
    with pytest.raises(ScopeViolation) as exc_info:
        check_write("/etc/passwd", _OWNED_DIR)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_backslash_path_is_rejected() -> None:
    """A backslash path is rejected as non-portable (Windows-style escape)."""
    with pytest.raises(ScopeViolation):
        check_write("src\\srl\\autonomy\\evil.py", _OWNED_DIR)


def test_empty_path_is_rejected() -> None:
    """An empty path is rejected."""
    with pytest.raises(ScopeViolation):
        check_write("", _OWNED_DIR)


def test_dot_segments_are_collapsed_for_comparison() -> None:
    """A path with redundant '.' segments is accepted when in scope."""
    # 'src/./srl/autonomy/x.py' collapses to an in-scope path.
    check_write("src/./srl/autonomy/x.py", _OWNED_DIR)


def test_owned_directory_prefix_does_not_match_partial_name() -> None:
    """An owned dir 'auto/' must not match a sibling 'autonomy2/' directory.

    Containment is by path segment, not substring, so a shared prefix does
    not widen scope.
    """
    owned = frozenset({"src/srl/auto/"})
    with pytest.raises(ScopeViolation):
        check_write("src/srl/autonomy/x.py", owned)
