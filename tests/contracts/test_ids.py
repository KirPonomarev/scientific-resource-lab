"""Unit tests for object identity and self-hash rejection (srl.contracts.ids).

Pins three properties of content-addressed identity:

1. **Determinism**: the same object yields the same id on every call, and two
   objects with the same content but different key order yield the same id.
2. **Self-hash rejection**: an object carrying its own ``object_id`` field
   raises :class:`SelfHashError` (fail reason ``CONTRACT_INVALID``).
3. **Shape**: every id is ``sha256:`` + 64 lowercase hex.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from srl.contracts.canonical import dumps
from srl.contracts.ids import (
    IDENTITY_FAIL_REASON,
    OBJECT_ID_FIELD,
    OBJECT_ID_PREFIX,
    IdentityError,
    SelfHashError,
    is_self_referential,
    object_id,
    validate_object_id,
)

# A canonical object id: "sha256:" + exactly 64 lowercase hex.
_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")


def test_object_id_is_sha256_prefix_plus_64_hex() -> None:
    """object_id returns 'sha256:' + 64 lowercase hex digits."""
    oid = object_id({"a": 1})
    assert oid.startswith(OBJECT_ID_PREFIX)
    assert _ID_RE.fullmatch(oid)


def test_object_id_matches_manual_sha256_of_canonical_bytes() -> None:
    """object_id is the sha256 of the canonical bytes (without the id field)."""
    obj = {"b": 2, "a": 1, "nested": {"y": [1, 2], "x": "z"}}
    expected = OBJECT_ID_PREFIX + hashlib.sha256(dumps(obj)).hexdigest()
    assert object_id(obj) == expected


def test_object_id_is_deterministic() -> None:
    """The same object yields the same id on every call."""
    obj = {"schema_version": "Demo/v1", "payload": {"x": 1}}
    assert object_id(obj) == object_id(obj)


def test_object_id_is_key_order_independent() -> None:
    """Two dicts with the same content but different key order yield the same id."""
    content = {"z": 26, "a": 1, "m": [3, 2, 1]}
    order_a = dict(sorted(content.items()))
    order_b = {k: content[k] for k in reversed(list(content))}
    assert object_id(order_a) == object_id(order_b)


def test_object_id_changes_when_content_changes() -> None:
    """A genuine content difference produces a different id."""
    base = {"a": 1}
    assert object_id(base) != object_id({"a": 2})
    assert object_id(base) != object_id({"a": 1, "b": 2})


def test_object_id_rejects_self_hash() -> None:
    """An object carrying its own object_id raises SelfHashError."""
    self_ref = {OBJECT_ID_FIELD: "sha256:abc", "x": 1}
    with pytest.raises(SelfHashError) as exc_info:
        object_id(self_ref)
    assert exc_info.value.fail_reason == IDENTITY_FAIL_REASON
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_object_id_allows_empty_object_id_value() -> None:
    """An empty object_id string is not treated as a self-hash (not a real id)."""
    # An empty value is not a populated id, so hashing proceeds normally.
    oid = object_id({OBJECT_ID_FIELD: "", "x": 1})
    assert _ID_RE.fullmatch(oid)


def test_is_self_referential_detects_populated_field() -> None:
    """is_self_referential is True iff object_id is a non-empty string."""
    assert is_self_referential({OBJECT_ID_FIELD: "sha256:abc"})
    assert not is_self_referential({OBJECT_ID_FIELD: ""})
    assert not is_self_referential({})
    assert not is_self_referential({OBJECT_ID_FIELD: None})
    assert not is_self_referential("not a dict")
    assert not is_self_referential({OBJECT_ID_FIELD: 123})


def test_validate_object_id_accepts_canonical_shape() -> None:
    """validate_object_id accepts 'sha256:' + 64 lowercase hex."""
    good = "sha256:" + "a" * 64
    assert validate_object_id(good) == good


def test_validate_object_id_rejects_uppercase_hex() -> None:
    """Uppercase hex is rejected (lowercase-only for byte stability)."""
    with pytest.raises(IdentityError):
        validate_object_id("sha256:" + "A" * 64)


def test_validate_object_id_rejects_wrong_length() -> None:
    """A too-short hex is rejected."""
    with pytest.raises(IdentityError):
        validate_object_id("sha256:abc")


def test_validate_object_id_rejects_wrong_prefix() -> None:
    """A non-sha256 prefix is rejected."""
    with pytest.raises(IdentityError):
        validate_object_id("md5:" + "a" * 64)


def test_validate_object_id_rejects_non_string() -> None:
    """A non-string is rejected."""
    with pytest.raises(IdentityError):
        validate_object_id(123)  # type: ignore[arg-type]
