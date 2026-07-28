"""Hermetic tests for the Content-Length stdio framing layer (WP-F51)."""

from __future__ import annotations

import pytest

from srl.mcp.framing import (
    FRAME_MALFORMED_FAIL_REASON,
    FRAME_PARSE_FAIL_REASON,
    FRAME_TOO_LARGE_FAIL_REASON,
    MAX_FRAME_BYTES,
    FrameError,
    encode_frame,
    parse_content_length,
)


class TestEncodeFrame:
    """``encode_frame`` produces a valid Content-Length frame."""

    def test_round_trip_header_and_body(self) -> None:
        frame = encode_frame({"jsonrpc": "2.0", "id": 1, "result": {}})
        assert frame.startswith(b"Content-Length: ")
        assert b"\r\n\r\n" in frame
        # The body is the canonical JSON (sorted keys, compact).
        _, _, body = frame.partition(b"\r\n\r\n")
        assert body == b'{"id":1,"jsonrpc":"2.0","result":{}}'

    def test_body_is_canonical_sorted_keys(self) -> None:
        frame = encode_frame({"b": 1, "a": 2})
        _, _, body = frame.partition(b"\r\n\r\n")
        # Sorted keys: a before b.
        assert body == b'{"a":2,"b":1}'

    def test_non_serializable_body_raises_parse_error(self) -> None:
        with pytest.raises(FrameError) as exc_info:
            encode_frame({"bad": object()})
        assert exc_info.value.fail_reason == FRAME_PARSE_FAIL_REASON


class TestParseContentLength:
    """``parse_content_length`` reads the header defensively."""

    def test_simple_header(self) -> None:
        assert parse_content_length("Content-Length: 42\r\n\r\n") == 42

    def test_case_insensitive_header(self) -> None:
        assert parse_content_length("content-length: 7\r\n\r\n") == 7

    def test_missing_header_raises_malformed(self) -> None:
        with pytest.raises(FrameError) as exc_info:
            parse_content_length("Other: 1\r\n\r\n")
        assert exc_info.value.fail_reason == FRAME_MALFORMED_FAIL_REASON

    def test_non_integer_value_raises_malformed(self) -> None:
        with pytest.raises(FrameError) as exc_info:
            parse_content_length("Content-Length: abc\r\n\r\n")
        assert exc_info.value.fail_reason == FRAME_MALFORMED_FAIL_REASON

    def test_negative_value_raises_malformed(self) -> None:
        with pytest.raises(FrameError) as exc_info:
            parse_content_length("Content-Length: -1\r\n\r\n")
        assert exc_info.value.fail_reason == FRAME_MALFORMED_FAIL_REASON

    def test_duplicate_header_raises_malformed(self) -> None:
        with pytest.raises(FrameError) as exc_info:
            parse_content_length("Content-Length: 1\r\nContent-Length: 2\r\n\r\n")
        assert exc_info.value.fail_reason == FRAME_MALFORMED_FAIL_REASON

    def test_malformed_line_raises_malformed(self) -> None:
        with pytest.raises(FrameError) as exc_info:
            parse_content_length("no-colon-here\r\n\r\n")
        assert exc_info.value.fail_reason == FRAME_MALFORMED_FAIL_REASON


class TestFrameCap:
    """The 1 MiB frame cap is enforced on encode."""

    def test_cap_constant_is_one_mib(self) -> None:
        assert MAX_FRAME_BYTES == 1024 * 1024

    def test_oversized_body_raises_too_large(self) -> None:
        # A body just over the cap.
        big = {"x": "a" * (MAX_FRAME_BYTES + 1)}
        with pytest.raises(FrameError) as exc_info:
            encode_frame(big)
        assert exc_info.value.fail_reason == FRAME_TOO_LARGE_FAIL_REASON
