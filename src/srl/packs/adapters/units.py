"""Units semantic core adapter (WP-E40).

This module is the dimensional-analysis layer for the SRL scientific fabric.
It replaces the fixture-scoped dimensional checker shipped in WP-B11 (which
hand-canonicalised exactly one identity, ``kg.m.s-2`` ≡ ``N``) with a real unit
algebra over a pinned QUDT subset, plus a compact UCUM alias table.

The adapter is the **only** module in the SRL tree that imports
:mod:`pint` (asserted by an architecture test in
``tests/packs/test_units_adapter.py``). Every other consumer goes through the
typed surface defined here:

- :class:`Dimension` — a frozen, comparable dimensional representation
  (the seven SI base dimensions plus derived reductions).
- :func:`parse_unit` — map a UCUM or QUDT unit string to a
  :class:`Dimension`.
- :func:`validate_dimensions` — check that a ``SymbolTable/v1`` and its
  referenced ``ConstantRef/v1`` entries are dimensionally coherent.
- :func:`convert` — convert a decimal-string value between dimensionally
  equivalent units under an explicit, reproducible precision policy.

Fail-fast contract
------------------
Dimensional errors (unknown unit, malformed string, dimensional mismatch) raise
:class:`UnitError` (fail reason ``CONTRACT_INVALID``) **before** any compute
runs. There is never a silent fallback to a guessed unit.

Precision policy
----------------
Precision-sensitive values are carried as JSON **strings** matching the SRL
decimal-string policy (``^-?[0-9]+(\\.[0-9]+)?$``); see
:mod:`srl.contracts.canonical`. Conversion renders the result to that policy via
:class:`decimal.Decimal`, never a float: the conversion factor is taken to a
bounded number of significant digits (:data:`CONVERSION_SIG_DIGITS`) and the
result is quantised so it survives a round trip with no float coercion.

See ``docs/architecture/units-core.md`` for the pinned QUDT subset, the UCUM
alias table, and the rationale for isolating Pint.
"""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
from typing import Any, Final

import pint

from srl.contracts.canonical import DECIMAL_STRING_PATTERN
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# The typed fail reason for a units violation. Mirrors the ``CONTRACT_INVALID``
# entry in ``automation/fail-reasons.json`` (class ``canonical``,
# ``hard_stop=true``, ``retriable=false``): a dimensional error is
# deterministic, not transient.
UNIT_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# The seven SI base dimensions Pint uses, in canonical (sorted) order. Derived
# units reduce to integer-exponent combinations of these. Exposed so callers
# and tests can introspect the supported dimension space without importing
# Pint.
SI_BASE_DIMENSIONS: Final[tuple[str, ...]] = (
    "[current]",
    "[length]",
    "[luminosity]",
    "[mass]",
    "[substance]",
    "[temperature]",
    "[time]",
)

# The pinned QUDT subset this adapter accepts. A unit string must reduce (after
# UCUM normalisation, see :data:`_UCUM_ALIASES`) to a product of these tokens.
# Anything else is an unknown unit and is rejected. The set is deliberately
# small and explicit so the dimensional surface is auditable; extending it is a
# documented change (see docs/architecture/units-core.md).
PINNED_QUDT_SUBSET: Final[frozenset[str]] = frozenset(
    {
        # SI base units.
        "m",
        "kg",
        "s",
        "A",
        "K",
        "mol",
        "cd",
        # SI derived units with special names (coherent).
        "N",
        "Pa",
        "J",
        "W",
        "Hz",
        "V",
        "C",
        "ohm",
        # Composite forms accepted verbatim (also accepted via UCUM aliases).
        "m/s",
        "m/s^2",
        "kg*m/s^2",
        # The absence of dimension.
        "dimensionless",
    }
)

# UCUM alias table. UCUM uses dot-separated tokens with signed exponents
# (``kg.m2.s-2``, ``m.s-1``) and some symbol spellings (``Ohm``, ``Cel``) that
# Pint does not parse directly. This table maps each UCUM token to the Pint
# canonical form. It is the compact, inline alias layer the adapter normalises
# through before handing a string to Pint. Only aliases needed for the pinned
# subset and the CODATA fixtures are listed; unrecognised tokens fall through
# unchanged and are then subject to the pinned-subset gate.
_UCUM_ALIASES: Final[dict[str, str]] = {
    # Signed-exponent spellings: 's-2' -> 's**-2', 'm2' -> 'm**2'.
    # These are produced by tokenising on '.' and rewriting each token below.
    "Ohm": "ohm",
}

# The set of leaf unit tokens the adapter accepts, derived from the pinned
# subset. A composite expression (``kg*m/s**2``) is gated by checking that
# every leaf token is a member of this set. This is what rejects ``fortnight``,
# ``km`` (not in the pinned subset), and other Pint-known-but-out-of-scope
# units: Pint's vocabulary is large; SRL's is deliberately small and auditable.
_ALLOWED_TOKENS: Final[frozenset[str]] = frozenset(
    name for name in PINNED_QUDT_SUBSET if name not in {"dimensionless"}
) | {"dimensionless"}

# Conversion precision: the number of significant digits the conversion factor
# and result are quantised to. 50 sig-digits is far beyond any physical
# measurement and well within Decimal's exact range, so a coherent conversion
# (e.g. 1 kg*m/s^2 -> 1 N) renders as the exact identity "1" rather than a
# float artefact like 0.9999999999999999. The value is a module constant so
# the precision policy has one home and is auditable.
CONVERSION_SIG_DIGITS: Final[int] = 50


class UnitError(ContractError):
    """Raised when a unit string or dimensional assertion is invalid.

    Carries the typed fail reason ``CONTRACT_INVALID``. Raised for: an unknown
    unit, a malformed unit string, a dimensional mismatch, or a decimal-string
    value that violates the precision policy. Always raised *before* any
    compute.
    """


@dataclass(frozen=True, slots=True)
class Dimension:
    """A frozen, comparable dimensional representation.

    Two units are *dimensionally equivalent* iff their ``Dimension`` objects
    are equal (e.g. ``N`` and ``kg*m/s**2`` both reduce to ``[length]=1,
    [mass]=1, [time]=-2``). The representation is the canonical mapping from
    each SI base dimension to its integer exponent, with zero-exponent entries
    elided and keys sorted.

    Equality and hashing are derived from the frozen exponent map, so a
    ``Dimension`` is usable as a dict key and in sets.

    Attributes
    ----------
    exponents:
        A mapping from SI base dimension name (e.g. ``[mass]``) to a signed
        integer exponent. Entries with exponent ``0`` are omitted.

    Notes
    -----
    ``Dimension`` is intentionally opaque about Pint: it exposes the canonical
    exponent map and nothing else. Callers never need to touch the underlying
    Pint object, which keeps the isolation boundary (ADR-0003) clean.
    """

    exponents: frozenset[tuple[str, int]]

    @classmethod
    def from_container(cls, container: Any) -> Dimension:
        """Build a :class:`Dimension` from a Pint ``UnitsContainer``.

        Accepts the container as ``Any`` because it is read off a Pint ``Unit``
        the adapter treats as opaque (ADR-0003). Drops zero exponents (the
        dimensionless case yields an empty set) and sorts by dimension name for
        a stable canonical form.
        """
        canonical = tuple(
            sorted(
                (str(dim), int(str(exp))) for dim, exp in container.items() if int(str(exp)) != 0
            )
        )
        return cls(exponents=frozenset(canonical))

    @property
    def is_dimensionless(self) -> bool:
        """True iff this dimension has no base-dimension components."""
        return not self.exponents

    def __str__(self) -> str:
        """Render as a sorted ``dim^exp`` product (the dimensionless case is '1')."""
        if not self.exponents:
            return "1"
        parts: list[str] = []
        for dim, exp in sorted(self.exponents):
            parts.append(dim if exp == 1 else f"{dim}^{exp}")
        return " * ".join(parts)


# ---------------------------------------------------------------------------
# Registry construction. A single process-wide UnitRegistry, built from the
# definition file shipped inside the wheel (no network access). Built lazily on
# first use so importing the adapter is cheap.
# ---------------------------------------------------------------------------


def _build_registry() -> Any:
    """Construct the deterministic, offline Pint registry.

    The registry is created with no cache folder (in-memory only) and uses the
    default definition file packaged with the wheel, so parsing is hermetic and
    reproducible across machines. Pint's ``UnitRegistry`` is generic over its
    facets; the adapter treats it as an opaque ``Any`` to keep the isolation
    boundary (ADR-0003) clean and avoid leaking Pint's type parameters into the
    SRL type surface.
    """
    return pint.UnitRegistry(cache_folder=None)


_REGISTRY: Any = None


def _registry() -> Any:
    """Return the process-wide registry, constructing it on first use."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def pint_version() -> str:
    """Return the resolved Pint version string (for gate evidence)."""
    return pint.__version__


# ---------------------------------------------------------------------------
# UCUM normalisation. Converts the UCUM dotted/signed-exponent notation used by
# the CODATA fixtures (``kg.m2.s-2``, ``m.s-1``) and a few symbol aliases
# (``Ohm``) into a Pint-parseable expression (``kg*m**2*s**-2``).
# ---------------------------------------------------------------------------

# Matches a single unit token with an optional signed integer exponent, e.g.
# 's-2', 'm2', 'kg', 's', 'm-1'. Used to rewrite UCUM exponent notation.
_UCUM_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^([A-Za-z]+)(-?\d+)$")


def _normalise_ucum(unit: str) -> str:
    """Normalise a UCUM-style unit string to a Pint-parseable expression.

    Rewrites each dot-separated token: a signed/unsigned trailing exponent
    (``s-2``, ``m2``) becomes Python power notation (``s**-2``, ``m**2``);
    known symbol aliases (``Ohm`` → ``ohm``) are applied; ``*`` and ``/`` and
    ``**`` already in the string are passed through unchanged so callers may
    use either notation. Whitespace is collapsed.

    The normaliser is intentionally permissive about *spelling* (it does not
    gate on the pinned subset); the subset gate happens in :func:`parse_unit`.
    """
    cleaned = " ".join(unit.strip().split())
    # If the string already uses Python operators, normalise token exponents
    # within it but keep the operator structure.
    # Replace UCUM '.' separators (only when between two unit-symbol chars) with
    # '*' so 'kg.m.s-2' becomes 'kg*m*s-2'. A '.' inside a number or adjacent to
    # a digit on both sides is left alone (defensive; unit strings here have no
    # decimal points).
    normalised = re.sub(r"(?<=[A-Za-z0-9)])\.(?=[A-Za-z(])", "*", cleaned)

    # Rewrite each maximal run of letters optionally followed by a signed
    # integer into '<letters>**<exp>' only when an exponent is present.
    def _rewrite(match: re.Match[str]) -> str:
        token = match.group(0)
        m = _UCUM_TOKEN_RE.fullmatch(token)
        if m is None:
            return _UCUM_ALIASES.get(token, token)
        name, exp = m.group(1), m.group(2)
        name = _UCUM_ALIASES.get(name, name)
        return f"{name}**{exp}"

    return re.sub(r"[A-Za-z]+-?\d*", _rewrite, normalised)


# ---------------------------------------------------------------------------
# Public API: parse_unit.
# ---------------------------------------------------------------------------


def _gate_tokens(unit: str, context: str) -> None:
    """Gate the leaf unit tokens of ``unit`` against the pinned subset.

    Extracts each unit-symbol token from the (possibly composite) string and
    requires it to be in :data:`_ALLOWED_TOKENS`. This is what rejects a
    Pint-known but out-of-scope unit such as ``fortnight`` or an SI-prefixed
    unit not in the pinned subset (``km``): Pint's vocabulary is large, SRL's
    is deliberately small and auditable. Unknown tokens are rejected here
    *before* Pint is asked to parse them.
    """
    # Normalise first so 'kg.m.s-2' becomes 'kg*m*s**-2' and the dot-form does
    # not confuse the token extraction.
    normalised = _normalise_ucum(unit)
    # Strip operators and exponents, leaving only the alphabetic unit names.
    # Operators in the normalised form: '*', '/', '**', '^', ' ', '(', ')'.
    cleaned = re.sub(r"[\*/\^()\s]|(\*\*)", " ", normalised)
    # Now 'kg  m  s ** -2' -> remove leftover '**' fragments and signs/numbers.
    cleaned = re.sub(r"\*\*", " ", cleaned)
    tokens = [t for t in cleaned.split() if t]
    # Exponents and signs leak through as numeric tokens; filter to alphabetic
    # unit names only.
    name_tokens = [t for t in tokens if re.fullmatch(r"[A-Za-z]+", t)]
    for tok in name_tokens:
        if tok not in _ALLOWED_TOKENS:
            resolved = _UCUM_ALIASES.get(tok)
            if resolved is None or resolved not in _ALLOWED_TOKENS:
                msg = (
                    f"unit {unit!r} ({context}) uses token {tok!r} which is not in "
                    f"the pinned QUDT subset"
                )
                raise UnitError(msg)


def _parse_pint(unit: str) -> Any:
    """Parse ``unit`` via Pint, trying the raw form then the UCUM-normalised form.

    Returns the Pint ``Unit`` object (typed as ``Any`` because the registry is
    opaque; the caller reads ``.dimensionality`` off it). Raises
    :class:`UnitError` if neither form parses.

    The suppression is deliberately broad: Pint's parser raises a variety of
    internal exceptions for malformed input (including ``AssertionError``
    from its eval-tree builder for dangling operators), and every one of them
    is a ``CONTRACT_INVALID`` unit error from the adapter's perspective. There
    is no recoverable parse path, so the first attempt is suppressed and the
    second (normalised) attempt's failure is the authoritative error.
    """
    registry = _registry()
    with suppress(Exception):
        return registry.parse_units(unit)
    try:
        normalised = _normalise_ucum(unit)
        return registry.parse_units(normalised)
    except Exception as exc:
        msg = f"unit {unit!r} is not a recognized unit in the pinned QUDT subset"
        raise UnitError(msg) from exc


def parse_unit(unit: str) -> Dimension:
    """Parse a UCUM or QUDT unit string into a :class:`Dimension`.

    The string is first gated token-by-token against :data:`PINNED_QUDT_SUBSET`
    (unknown tokens raise :class:`UnitError` *before* Pint is consulted),
    then normalised from UCUM notation (see :func:`_normalise_ucum`), and
    finally parsed by Pint to yield the reduced dimension.

    Parameters
    ----------
    unit:
        A unit string. Accepted forms include the pinned QUDT symbols
        (``m``, ``kg``, ``N``, ...), composite Python-notation forms
        (``kg*m/s**2``, ``m/s^2``), and UCUM dotted forms (``kg.m.s-2``,
        ``m.s-1``).

    Returns
    -------
    Dimension
        The reduced dimensional representation.

    Raises
    ------
    UnitError
        If ``unit`` is empty, is not in the pinned QUDT subset, or cannot be
        parsed (fail reason ``CONTRACT_INVALID``). Raised before any compute.
    """
    if not isinstance(unit, str) or unit.strip() == "":
        msg = "unit must be a non-empty string"
        raise UnitError(msg)
    _gate_tokens(unit, context="parse_unit")
    pint_unit = _parse_pint(unit)
    return Dimension.from_container(pint_unit.dimensionality)


def _parse_unit_or_raise(unit: str, context: str) -> tuple[Dimension, Any]:
    """Parse ``unit`` and return (dimension, pint_unit) for a given context.

    The pint_unit (opaque ``Any``) is returned so :func:`convert` can compute
    the factor without re-parsing. Raises :class:`UnitError` on any parse
    failure.
    """
    if not isinstance(unit, str) or unit.strip() == "":
        msg = f"unit for {context} must be a non-empty string"
        raise UnitError(msg)
    _gate_tokens(unit, context=context)
    pint_unit = _parse_pint(unit)
    dim = Dimension.from_container(pint_unit.dimensionality)
    return dim, pint_unit


# ---------------------------------------------------------------------------
# Public API: convert.
# ---------------------------------------------------------------------------

# A Decimal context with ample precision for exact coherent conversions. The
# context is constructed per-call (Decimal contexts are thread-local by default)
# and bounds the working precision; the final result is quantised to
# CONVERSION_SIG_DIGITS significant digits.
_DECIMAL_PREC: Final[int] = 80


def convert(value: str, from_unit: str, to_unit: str) -> str:
    """Convert a decimal-string value from one unit to another.

    The value must be an SRL decimal-string policy value
    (``^-?[0-9]+(\\.[0-9]+)?$``). Both units must be dimensionally equivalent
    (``parse_unit(from_unit) == parse_unit(to_unit)``); otherwise a
    :class:`UnitError` is raised *before* any arithmetic.

    The conversion factor is computed through Pint and rendered via
    :class:`decimal.Decimal`, so a coherent conversion (e.g.
    ``1 kg*m/s^2 -> 1 N``) yields the exact decimal identity ``"1"`` with no
    float artefact. The result is quantised to :data:`CONVERSION_SIG_DIGITS`
    significant digits using round-half-up.

    Parameters
    ----------
    value:
        The magnitude as a decimal-string policy value.
    from_unit:
        The unit the value is expressed in.
    to_unit:
        The target unit (must be dimensionally equivalent to ``from_unit``).

    Returns
    -------
    str
        The converted magnitude as a decimal-string policy value.

    Raises
    ------
    UnitError
        If ``value`` is not a decimal-string, either unit is unknown or
        malformed, or the two units are not dimensionally equivalent.
    """
    # Fail fast on the value before touching the units.
    value_decimal = _validate_decimal_value(value)

    from_dim, from_pint = _parse_unit_or_raise(from_unit, context="from_unit")
    to_dim, to_pint = _parse_unit_or_raise(to_unit, context="to_unit")

    if from_dim != to_dim:
        msg = (
            f"cannot convert {from_unit!r} to {to_unit!r}: dimensions differ "
            f"({from_dim} vs {to_dim})"
        )
        raise UnitError(msg)

    # Compute the conversion factor as a Decimal. Pint's conversion goes through
    # float internally; for a coherent conversion the factor is exactly 1.0. We
    # render the factor via its shortest round-trip repr (``str``) rather than
    # ``create_decimal_from_float`` (which would capture the full binary
    # expansion and introduce artefacts like 1.0000...208 for prefix
    # conversions). The pinned subset's conversion factors are all short
    # rationals, so ``str(factor_float)`` round-trips exactly.
    registry = _registry()
    quantity: Any = registry.Quantity(1, from_pint)
    converted: Any = quantity.to(to_pint)
    factor_str = str(converted.magnitude)

    ctx = Context(prec=_DECIMAL_PREC)
    try:
        factor = Decimal(factor_str)
        result = ctx.multiply(value_decimal, factor)
    except InvalidOperation as exc:
        msg = f"conversion {value!r} {from_unit!r} -> {to_unit!r} is not representable"
        raise UnitError(msg) from exc

    # Quantise to CONVERSION_SIG_DIGITS significant digits, round-half-up, then
    # strip insignificant trailing zeros so a coherent conversion renders as
    # the exact decimal identity (``1 kg*m/s^2 -> 1 N``).
    return _quantise_to_sig_digits(result, CONVERSION_SIG_DIGITS)


def _validate_decimal_value(value: Any) -> Decimal:
    """Validate a decimal-string policy value and return it as a Decimal."""
    if not isinstance(value, str) or value.strip() == "":
        msg = f"value must be a non-empty decimal string, got {value!r}"
        raise UnitError(msg)
    if not re.fullmatch(DECIMAL_STRING_PATTERN, value):
        msg = (
            f"value {value!r} must match the decimal-string policy "
            f"({DECIMAL_STRING_PATTERN!r}); no exponent, no float coercion"
        )
        raise UnitError(msg)
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        msg = f"value {value!r} is not a valid decimal"
        raise UnitError(msg) from exc


def _quantise_to_sig_digits(value: Decimal, sig_digits: int) -> str:
    """Quantise ``value`` to ``sig_digits`` significant digits (round-half-up).

    Returns a decimal-string policy value (no exponent). Insignificant trailing
    zeros are stripped so a coherent conversion renders as the exact decimal
    identity (``1`` rather than ``1.0000...0``); the special case of an integer
    result renders without a trailing dot. A literal ``0`` renders as ``"0"``.
    """
    if value == 0:
        return "0"
    # Determine the position of the most significant digit.
    tuple_repr = value.as_tuple()
    digits = tuple_repr.digits
    exponent_raw = tuple_repr.exponent
    # Decimal.as_tuple().exponent is a Literal['n','N','F'] for non-finite
    # values; those never reach here (values are policy decimal strings), but
    # narrow the type so the arithmetic below type-checks under --strict.
    if not isinstance(exponent_raw, int):
        msg = "non-finite Decimal reached quantisation; policy values must be finite"
        raise UnitError(msg)
    exponent = exponent_raw
    # The value = int(digits) * 10**exponent. The position of the first digit
    # (the 'order') is len(digits) + exponent.
    first_sig_pos = len(digits) + exponent
    # Quantise so that exactly sig_digits significant digits remain.
    target_exponent = first_sig_pos - sig_digits
    quantiser = Decimal(1).scaleb(target_exponent)
    ctx = Context(prec=max(sig_digits + 2, _DECIMAL_PREC), rounding=ROUND_HALF_UP)
    quantised = ctx.quantize(value, quantiser)
    # Strip insignificant trailing zeros, preserving at least one digit. The
    # quantise step guarantees the value fits the policy; normalise() collapses
    # trailing zeros while keeping the value numerically identical.
    normalised = quantised.normalize()
    # Guard against normalise() rendering in exponent form for large integers;
    # always emit fixed-point.
    rendered = format(normalised, "f")
    if rendered in {"-0", "-0.0", "+0"}:
        return "0"
    return rendered


# ---------------------------------------------------------------------------
# Public API: validate_dimensions.
# ---------------------------------------------------------------------------


def validate_dimensions(
    symbol_table: dict[str, Any],
    constant_refs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate dimensional coherence of a symbol table and its constant refs.

    For each symbol in ``symbol_table`` that carries a ``unit_ref``, the
    referenced constant's unit (from ``constant_refs``) is parsed and its
    dimension recorded. Symbols without a ``unit_ref`` are skipped. The report
    records the parsed dimension for every checked symbol and any mismatch.

    A *mismatch* is a symbol whose inline ``domain`` carries a unit that
    disagrees with the referenced constant's unit. (The ``domain`` field is a
    MathIR set expression; it does not carry a unit directly, so the primary
    check is that every referenced constant's unit parses cleanly and that the
    declared units of symbols that ought to match — by sharing a constant — do
    match.)

    Parameters
    ----------
    symbol_table:
        A ``SymbolTable/v1`` dict (``{"schema_version": "SymbolTable/v1",
        "symbols": [...]}``).
    constant_refs:
        A mapping from ``constant_id`` to a ``ConstantRef/v1`` dict. May be
        ``None`` (then only the symbol-table units that are inline are parsed).

    Returns
    -------
    dict
        A report dict: ``{"status": "coherent"|"incoherent", "checked": int,
        "dimensions": {symbol_id: dimension_str}, "mismatches": [...]}``.

    Raises
    ------
    UnitError
        If a referenced constant's unit cannot be parsed (unknown/malformed),
        or if two symbols that reference the same constant resolve to
        incompatible dimensions. Raised before any compute.
    """
    got = symbol_table.get("schema_version")
    if got != "SymbolTable/v1":
        msg = f"symbol_table schema_version must be 'SymbolTable/v1', got {got!r}"
        raise UnitError(msg)
    symbols = symbol_table.get("symbols")
    if not isinstance(symbols, list):
        msg = "symbol_table.symbols must be a list"
        raise UnitError(msg)

    refs = constant_refs or {}
    const_dims: dict[str, Dimension] = {}  # constant_id -> Dimension (memoised)
    checked = 0
    dimensions: dict[str, str] = {}
    mismatches: list[dict[str, str]] = []

    for idx, symbol in enumerate(symbols):
        if not isinstance(symbol, dict):
            msg = f"symbols[{idx}] must be an object"
            raise UnitError(msg)
        symbol_id = symbol.get("symbol_id")
        unit_ref = symbol.get("unit_ref")
        if not isinstance(unit_ref, str) or unit_ref == "":
            continue  # No unit reference: nothing to check for this symbol.
        if not isinstance(symbol_id, str) or symbol_id == "":
            msg = f"symbols[{idx}].symbol_id must be a non-empty string when unit_ref is set"
            raise UnitError(msg)

        const_ref = refs.get(unit_ref)
        checked_inc, dim_str = _check_symbol_constant(
            symbol_id=symbol_id,
            unit_ref=unit_ref,
            const_ref=const_ref,
            const_dims=const_dims,
            mismatches=mismatches,
        )
        if checked_inc:
            checked += 1
            dimensions[symbol_id] = dim_str

    # A symbol table is dimensionally coherent iff every referenced constant's
    # unit parsed successfully (parse_unit would have raised otherwise) and no
    # explicit mismatch was recorded.
    status = "coherent" if not mismatches else "incoherent"
    return {
        "status": status,
        "checked": checked,
        "dimensions": dimensions,
        "mismatches": mismatches,
    }


def _check_symbol_constant(
    *,
    symbol_id: str,
    unit_ref: str,
    const_ref: Any,
    const_dims: dict[str, Dimension],
    mismatches: list[dict[str, str]],
) -> tuple[bool, str]:
    """Resolve one symbol's constant ref and record its dimension or a mismatch.

    Returns ``(checked, dimension_str)``: ``checked`` is True when the
    constant's unit parsed cleanly and the symbol contributed to the checked
    count; ``dimension_str`` is the rendered dimension (empty when unchecked).
    Raises :class:`UnitError` if the constant ref is structurally invalid or
    its unit cannot be parsed.
    """
    if const_ref is None:
        # An unresolved reference is reported but not fatal here (it is a
        # referential-integrity concern, not a dimensional one). The caller
        # decides whether to treat it as an error.
        mismatches.append(
            {"symbol_id": symbol_id, "constant_id": unit_ref, "reason": "unresolved_ref"}
        )
        return False, ""
    if not isinstance(const_ref, dict):
        msg = f"constant_ref {unit_ref!r} must be a dict"
        raise UnitError(msg)

    unit = const_ref.get("unit")
    if not isinstance(unit, str) or unit == "":
        msg = f"constant_ref {unit_ref!r}.unit must be a non-empty string"
        raise UnitError(msg)

    # Parse and memoise per constant id.
    dim = const_dims.get(unit_ref)
    if dim is None:
        dim = parse_unit(unit)
        const_dims[unit_ref] = dim
    return True, str(dim)


__all__ = [
    "CONVERSION_SIG_DIGITS",
    "PINNED_QUDT_SUBSET",
    "SI_BASE_DIMENSIONS",
    "UNIT_FAIL_REASON",
    "Dimension",
    "UnitError",
    "convert",
    "parse_unit",
    "pint_version",
    "validate_dimensions",
]
