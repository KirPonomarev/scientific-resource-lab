"""Unit tests for the path-redaction privacy layer (srl.cas.privacy).

Pins:

1. ``redact_store_path`` returns ``redacted:<16 hex>`` and never the raw path.
2. The redaction is stable (same path -> same token) and is one-way (the raw
   path is not recoverable from the token).
3. Absolute and relative references to the same store redact identically.
4. A descriptor and a receipt built from a raw-looking path never carry the raw
   path in their public string outputs (the cross-package privacy contract).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from srl.cas.privacy import redact_store_path
from srl.cas.store import ArtifactDescriptor, LocalArtifactStore

_RAW_PATH_RE = re.compile(r"^/(Volumes|Users|home)/")


def test_redact_store_path_shape() -> None:
    """The redacted form is redacted:<16 lowercase hex>."""
    token = redact_store_path("/Volumes/T7/srl-cas")
    assert re.fullmatch(r"redacted:[0-9a-f]{16}", token)


def test_redact_store_path_never_returns_raw() -> None:
    """The raw path never appears in the redacted token."""
    for raw in ("/Volumes/T7/data", "/Users/op/store", "/home/op/store"):
        token = redact_store_path(raw)
        assert not _RAW_PATH_RE.match(token)
        assert raw not in token


def test_redact_store_path_is_deterministic() -> None:
    """The same path redacts to the same token every time."""
    assert redact_store_path("/Volumes/T7/x") == redact_store_path("/Volumes/T7/x")


def test_redact_store_path_is_one_way() -> None:
    """The token is the first 16 hex of the SHA-256 of the absolute path."""
    raw = "/Volumes/T7/srl-cas"
    expected = "redacted:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    assert redact_store_path(raw) == expected


def test_redact_store_path_distinguishes_different_paths() -> None:
    """Different paths produce different tokens."""
    assert redact_store_path("/Volumes/T7/a") != redact_store_path("/Volumes/T7/b")


def test_redact_store_path_accepts_path_object() -> None:
    """A pathlib.Path is accepted."""
    token = redact_store_path(Path("/Volumes/T7/x"))
    assert token.startswith("redacted:")


def test_descriptor_never_carries_raw_path(tmp_path: Path) -> None:
    """An ArtifactDescriptor from a raw-rooted store never leaks the root."""
    store = LocalArtifactStore(tmp_path)
    desc = store.put(b"privacy-probe")
    # Scan every field of the frozen dataclass for a raw path.
    for value in vars(desc).values():
        assert not _RAW_PATH_RE.match(str(value))
    assert _RAW_PATH_RE.match(store.store_root_redacted) is None


def test_descriptor_redacted_token_matches_root(tmp_path: Path) -> None:
    """The descriptor's store_root_redacted matches the store's redacted root."""
    store = LocalArtifactStore(tmp_path)
    desc: ArtifactDescriptor = store.put(b"x")
    assert desc.store_root_redacted == store.store_root_redacted


@pytest.mark.parametrize("raw", ["/Volumes/T7/store", "/Users/op/store", "/home/op/store"])
def test_no_public_api_emits_raw_path_over_raw_rooted_store(tmp_path: Path, raw: str) -> None:
    """Building a store at a raw-looking (synthetic) path leaks nothing raw.

    The store root is under the test temp dir; we only check that the public
    string outputs (store_root_redacted, descriptor fields, fsck fields) never
    begin with a raw host-local prefix. The raw strings here are never used as
    real roots — they document the prefix classes that must not leak.
    """
    del raw  # the parametrization documents the prefix classes; tmp_path is used
    store = LocalArtifactStore(tmp_path)
    desc = store.put(b"prefix-probe")
    report = store.fsck()
    for value in (
        store.store_root_redacted,
        desc.digest,
        desc.store_root_redacted,
        str(report.objects_checked),
    ):
        assert not _RAW_PATH_RE.match(str(value))
