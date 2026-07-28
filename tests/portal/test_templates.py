"""Tests for portal templates and HTML escaping."""

from __future__ import annotations

from srl.portal.build import escape_html


def test_escape_html_escapes_special_characters() -> None:
    """All HTML-significant characters are replaced by entities."""
    assert escape_html("&") == "&amp;"
    assert escape_html("<") == "&lt;"
    assert escape_html(">") == "&gt;"
    assert escape_html('"') == "&quot;"
    assert escape_html("'") == "&#39;"


def test_escape_html_script_payload() -> None:
    """A <script> injection payload is fully neutralized."""
    payload = "<script>alert('xss')</script>"
    escaped = escape_html(payload)
    assert escaped == "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;"
    assert "<script>" not in escaped


def test_escape_html_converts_non_strings() -> None:
    """Non-string values are coerced to strings before escaping."""
    assert escape_html(42) == "42"
    assert escape_html(None) == "None"
