"""Hermetic fake transport and canned payloads for WP-D33 knowledge gates.

This module provides a deterministic, no-network :class:`FakeTransport` that
implements the :class:`~srl.knowledge.retriever.Transport` protocol. It is used
by the WP-D33 gate script and the hermetic knowledge tests so CI never makes a
live HTTP request.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

from srl.knowledge.retriever import TransportResponse

__all__ = ["FakeTransport", "canned_payload"]


def canned_payload(name: str) -> bytes:
    """Return the raw bytes of a canned synthetic payload by file name.

    Parameters
    ----------
    name:
        File name under ``payloads/`` (e.g. ``"openalex_works.json"``).

    Returns
    -------
    bytes
        The payload bytes.

    Raises
    ------
    FileNotFoundError
        If the named payload does not exist.
    """
    here = Path(__file__).resolve().parent
    return (here / "payloads" / name).read_bytes()


class FakeTransport:
    """A deterministic, no-network transport for testing the retriever.

    The transport records every call so tests can assert that cache hits do not
    re-invoke the network layer. The final URL scheme and host are configurable
    so tests can simulate both clean HTTPS responses and policy-violating
    redirects.
    """

    def __init__(
        self,
        payload: bytes = b"",
        *,
        scheme: str = "https",
        final_host: str | None = None,
        status: int = 200,
    ) -> None:
        self.payload = payload
        self.scheme = scheme
        self.final_host = final_host
        self.status = status
        self.calls: list[tuple[str, int]] = []

    def fetch(self, url: str, *, timeout_seconds: int) -> TransportResponse:
        """Return the configured response without any network I/O."""
        self.calls.append((url, timeout_seconds))
        parsed = urllib.parse.urlsplit(url)
        host = self.final_host if self.final_host is not None else parsed.netloc
        return TransportResponse(
            payload=self.payload,
            final_scheme=self.scheme,
            final_host=host,
            status=self.status,
        )


class SequenceTransport:
    """A fake transport that returns a sequence of responses across calls.

    Used to exercise the retry path: a 429 or 5xx response can be followed by
    a 200 response.
    """

    def __init__(self, responses: list[TransportResponse]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, int]] = []

    def fetch(self, url: str, *, timeout_seconds: int) -> TransportResponse:
        """Return the next response in the sequence."""
        self.calls.append((url, timeout_seconds))
        if self._index >= len(self._responses):
            raise RuntimeError("SequenceTransport exhausted")
        response = self._responses[self._index]
        self._index += 1
        return response
