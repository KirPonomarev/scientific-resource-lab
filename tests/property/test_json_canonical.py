"""Property-based tests for canonical JSON encoding.

Uses Hypothesis to assert the stability and round-trip properties of
:func:`srl.canonical.canonical_json`:

1. Round-trip: decoding canonical output reproduces the input value.
2. Stability: encoding the same value twice yields identical bytes.
3. Equivalence-with-equal-values: equal inputs produce equal canonical bytes.
4. Ordering: object keys appear in sorted order in the output.
5. Compactness: no insignificant whitespace is emitted.

The strategy restricts floats to avoid NaN/Infinity (which JSON cannot
represent portably) and keeps container depth modest so Hypothesis runs are
fast while still exercising nested structures.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from srl.canonical import CanonicalJSONError, canonical_json, canonical_json_line

# JSON scalars. Floats without NaN/Inf so json.dumps stays valid and reversible.
_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),  # safe JSON integer range
    st.floats(
        allow_nan=False,
        allow_infinity=False,
        # Keep magnitudes modest to avoid exponential formatting edge cases.
        min_value=-1e6,
        max_value=1e6,
    ),
    st.text(max_size=10),
)


# Recursive JSON value strategy. ``max_leaves`` bounds size for speed.
_json_values = st.recursive(
    _json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=5), children, max_size=5),
    ),
    max_leaves=10,
)


def _resort_dict_keys(value: Any) -> Any:
    """Return a copy of ``value`` with dict keys sorted recursively.

    Used to assert that canonical output matches a known-sorted structure.
    """
    if isinstance(value, Mapping):
        return {k: _resort_dict_keys(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_resort_dict_keys(v) for v in value]
    return value


@given(_json_values)
@settings(max_examples=200)
def test_canonical_json_round_trips(value: Any) -> None:
    """Decoding canonical output reproduces the input value."""
    encoded = canonical_json(value)
    decoded = json.loads(encoded)
    assert decoded == _resort_dict_keys(value)


@given(_json_values)
@settings(max_examples=200)
def test_canonical_json_is_stable(value: Any) -> None:
    """Encoding the same value twice yields identical bytes."""
    assert canonical_json(value) == canonical_json(value)


@given(st.dictionaries(st.text(min_size=1, max_size=5), _json_scalars, max_size=8))
@settings(max_examples=200)
def test_canonical_json_is_key_order_independent(value: dict[str, Any]) -> None:
    """Two dicts with the same content but different insertion order encode alike.

    This is the defining invariant of canonical JSON: byte-stable output that is
    insensitive to how the dict was constructed. A genuine content difference
    would still produce different bytes; only ordering is normalized away.
    """
    # Re-insert keys in reversed order to simulate an independent construction.
    reordered = {k: value[k] for k in reversed(list(value))}
    assert canonical_json(value) == canonical_json(reordered)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # Python treats these as equal (False == 0, True == 1, 1 == 1.0), but
        # JSON distinguishes them by type. Canonical encoding must preserve the
        # distinction, never collapse it. (Surfaced by Hypothesis during WP-A02.)
        (False, 0),
        (True, 1),
        (1, 1.0),
    ],
)
def test_canonical_json_distinguishes_json_types(left: Any, right: Any) -> None:
    """JSON-distinct values that Python considers equal encode differently."""
    assert left == right  # Python equality holds...
    assert canonical_json(left) != canonical_json(right)  # ...but bytes differ.


@given(st.dictionaries(st.text(min_size=1, max_size=5), _json_scalars, max_size=8))
@settings(max_examples=200)
def test_canonical_json_keys_are_sorted(value: dict[str, Any]) -> None:
    """Object keys appear in sorted order in the canonical output."""
    encoded = canonical_json(value)
    decoded = json.loads(encoded)
    # decoded is an insertion-ordered dict; its keys must be sorted.
    assert list(decoded.keys()) == sorted(value.keys())


@given(_json_values)
@settings(max_examples=200)
def test_canonical_json_is_compact(value: Any) -> None:
    """Canonical output contains no insignificant whitespace."""
    encoded = canonical_json(value)
    assert ", " not in encoded
    assert ": " not in encoded


@given(_json_values)
@settings(max_examples=100)
def test_canonical_json_line_has_single_trailing_newline(value: Any) -> None:
    """``canonical_json_line`` adds exactly one trailing newline."""
    line = canonical_json_line(value)
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert line[:-1] == canonical_json(value)


def test_unserializable_value_raises() -> None:
    """A non-JSON value raises :class:`CanonicalJSONError`."""
    with pytest.raises(CanonicalJSONError):
        canonical_json(object())  # type: ignore[arg-type]
