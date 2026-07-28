"""Hermetic canned payload loader for the WP-E44 source adapter gates."""

from __future__ import annotations

from pathlib import Path

__all__ = ["canned_payload"]


def canned_payload(name: str) -> bytes:
    """Return the raw bytes of a canned synthetic payload by file name.

    Parameters
    ----------
    name:
        File name under ``payloads/`` (e.g. ``"openalex_normal_1.json"``).

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
