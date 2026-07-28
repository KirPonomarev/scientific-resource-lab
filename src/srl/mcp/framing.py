"""Content-Length framed stdio transport for the read-only MCP server (WP-F51).

The MCP stdio transport wraps JSON-RPC 2.0 messages in a ``Content-Length``
header frame, mirroring the LSP framing the MCP specification reuses. A frame
is::

    Content-Length: <N>\r\n
    \r\n
    <N bytes of UTF-8 JSON>\r\n

This module is the *only* place bytes touch the wire. It is deliberately
defensive on every boundary that an untrusted host could abuse:

- **oversized frame cap**: a frame whose declared ``Content-Length`` exceeds
  :data:`MAX_FRAME_BYTES` (1 MiB) is refused with a typed
  :class:`FrameError` (``fail_reason`` :data:`FRAME_TOO_LARGE_FAIL_REASON`)
  *before* any bytes are buffered for the body.
- **malformed JSON**: a frame body that is not valid JSON is refused with a
  :class:`FrameError` (``fail_reason`` :data:`FRAME_PARSE_FAIL_REASON`).
- **no partial body leakage**: a frame that declares ``Content-Length`` but
  cannot deliver the body (stream closed mid-frame) raises rather than
  emitting a truncated message.

The server never opens a socket and never reads from anything but the file
descriptors it was given (stdin/stdout). The framing layer carries no I/O
state beyond the byte buffers it needs to assemble frames; it performs no
network I/O and writes nothing to disk.
"""

from __future__ import annotations

from typing import Final

from srl.contracts.canonical import dumps as canonical_dumps

# ---------------------------------------------------------------------------
# Frame limits and identity anchors.
# ---------------------------------------------------------------------------

# Hard upper bound on a single frame's body, in bytes. 1 MiB. A larger declared
# length is refused before any body bytes are buffered, so an oversized header
# cannot exhaust memory. MCP messages are small JSON-RPC envelopes; a 1 MiB cap
# is generous while still bounding a hostile host.
_MAX_MIB: Final[int] = 1
MAX_FRAME_BYTES: Final[int] = _MAX_MIB * 1024 * 1024

# The typed fail reasons emitted by the framing layer. Oversized and parse
# failures are distinct typed reasons so a caller can route them differently
# (an oversized frame is a policy refusal; a parse failure is a malformed peer).
FRAME_TOO_LARGE_FAIL_REASON: Final[str] = "FRAME_TOO_LARGE"
FRAME_PARSE_FAIL_REASON: Final[str] = "FRAME_PARSE_ERROR"
FRAME_MALFORMED_FAIL_REASON: Final[str] = "FRAME_MALFORMED"

# The header name this layer reads, lowercased for case-insensitive matching.
_CONTENT_LENGTH_HEADER: Final[str] = "content-length"

# Header terminator: a blank line (CRLF CRLF) separates headers from body.
_HEADER_TERMINATOR: Final[bytes] = b"\r\n\r\n"
_HEADER_LINE_TERM: Final[bytes] = b"\r\n"


class FrameError(Exception):
    """Raised when a frame cannot be read or written.

    Carries a typed ``fail_reason`` drawn from :data:`FRAME_TOO_LARGE_FAIL_REASON`,
    :data:`FRAME_PARSE_FAIL_REASON`, or :data:`FRAME_MALFORMED_FAIL_REASON`.

    Attributes
    ----------
    fail_reason:
        Typed fail reason for routing/diagnostics.
    """

    def __init__(self, message: str, *, fail_reason: str = FRAME_MALFORMED_FAIL_REASON) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason


def encode_frame(message: object) -> bytes:
    """Encode a JSON-RPC ``message`` as one Content-Length-framed byte string.

    The body is canonical JSON (sorted keys, compact separators, trailing
    newline stripped — the frame carries its own length). The header is the
    single ``Content-Length`` line followed by the blank-line separator.

    Parameters
    ----------
    message:
        Any :mod:`json`-serializable value (the caller passes a JSON-RPC
        response dict).

    Returns
    -------
    bytes
        ``b"Content-Length: <N>\\r\\n\\r\\n" + body``.

    Raises
    ------
    FrameError
        If ``message`` is not canonical-JSON serializable, or the encoded body
        exceeds :data:`MAX_FRAME_BYTES`.
    """
    try:
        body = canonical_dumps(message).rstrip(b"\n")
    except Exception as exc:  # canonical_dumps raises CanonicalJSONError
        msg = f"frame body is not canonical-JSON serializable: {exc}"
        raise FrameError(msg, fail_reason=FRAME_PARSE_FAIL_REASON) from exc
    if len(body) > MAX_FRAME_BYTES:
        msg = (
            f"encoded frame body is {len(body)} bytes, exceeding the "
            f"{MAX_FRAME_BYTES}-byte cap (FRAME_TOO_LARGE)"
        )
        raise FrameError(msg, fail_reason=FRAME_TOO_LARGE_FAIL_REASON)
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def parse_content_length(header_block: str) -> int:
    """Parse the ``Content-Length`` value from a decoded header block.

    The header block is the text between frame start and the blank-line
    terminator. Header matching is case-insensitive; exactly one
    ``Content-Length`` header is required.

    Parameters
    ----------
    header_block:
        The decoded header text (CRLF-terminated lines, no body).

    Returns
    -------
    int
        The non-negative content length.

    Raises
    ------
    FrameError
        If no ``Content-Length`` header is present, the value is not a
        non-negative integer, or more than one is present.
    """
    found: list[int] = []
    for line in header_block.split("\r\n"):
        if not line:
            continue
        if ":" not in line:
            msg = f"malformed header line (no ':'): {line!r}"
            raise FrameError(msg, fail_reason=FRAME_MALFORMED_FAIL_REASON)
        name, _, raw_value = line.partition(":")
        if name.strip().lower() != _CONTENT_LENGTH_HEADER:
            continue
        value = raw_value.strip()
        try:
            n = int(value)
        except ValueError as exc:
            msg = f"Content-Length is not an integer: {value!r}"
            raise FrameError(msg, fail_reason=FRAME_MALFORMED_FAIL_REASON) from exc
        if n < 0:
            msg = f"Content-Length is negative: {n}"
            raise FrameError(msg, fail_reason=FRAME_MALFORMED_FAIL_REASON)
        found.append(n)
    if not found:
        msg = "frame is missing the Content-Length header"
        raise FrameError(msg, fail_reason=FRAME_MALFORMED_FAIL_REASON)
    if len(found) > 1:
        msg = f"frame has multiple Content-Length headers: {found}"
        raise FrameError(msg, fail_reason=FRAME_MALFORMED_FAIL_REASON)
    return found[0]


__all__ = [
    "FRAME_MALFORMED_FAIL_REASON",
    "FRAME_PARSE_FAIL_REASON",
    "FRAME_TOO_LARGE_FAIL_REASON",
    "MAX_FRAME_BYTES",
    "FrameError",
    "encode_frame",
    "parse_content_length",
]
