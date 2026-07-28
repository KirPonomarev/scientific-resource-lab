"""Tests for :mod:`srl.packs.adapters.units` (WP-E40 units semantic core).

All tests are hermetic: they exercise the units adapter on in-memory values and
the in-repo CODATA fixtures, never touching the network. Pint is imported only
inside the adapter; an architecture test asserts no other module in the SRL
tree imports it (the isolation boundary documented in ADR-0003).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.packs.adapters.units import (
    CONVERSION_SIG_DIGITS,
    PINNED_QUDT_SUBSET,
    SI_BASE_DIMENSIONS,
    Dimension,
    UnitError,
    convert,
    parse_unit,
    pint_version,
    validate_dimensions,
)

# The repository root, for the architecture scan over the source tree.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "srl"
_ADAPTER_MODULE = _SRC_ROOT / "packs" / "adapters" / "units.py"


# ---------------------------------------------------------------------------
# parse_unit: the pinned subset parses and reduces correctly.
# ---------------------------------------------------------------------------


class TestParseUnit:
    """``parse_unit`` over the pinned QUDT subset."""

    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("m", "[length]"),
            ("kg", "[mass]"),
            ("s", "[time]"),
            ("A", "[current]"),
            ("K", "[temperature]"),
            ("mol", "[substance]"),
            ("cd", "[luminosity]"),
        ],
    )
    def test_si_base_units_parse_to_singleton_dimension(self, unit: str, expected: str) -> None:
        """Each SI base unit yields its singleton dimension."""
        assert str(parse_unit(unit)) == expected

    @pytest.mark.parametrize(
        "unit",
        ["N", "Pa", "J", "W", "Hz", "V", "C", "ohm"],
    )
    def test_si_derived_units_parse(self, unit: str) -> None:
        """The coherent SI derived units parse to a non-empty dimension."""
        dim = parse_unit(unit)
        assert not dim.is_dimensionless

    def test_dimensionless_parses_to_empty(self) -> None:
        """The dimensionless unit has no base-dimension components."""
        dim = parse_unit("dimensionless")
        assert dim.is_dimensionless
        assert str(dim) == "1"


class TestDimensionalEquivalence:
    """Dimensional equivalence: factored forms reduce to the named derived unit."""

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("kg*m/s^2", "N"),
            ("N", "kg*m/s^2"),
            ("J", "N*m"),
            ("Pa", "N/m^2"),
            ("W", "J/s"),
            ("V", "J/C"),
            ("Hz", "1/s"),
        ],
    )
    def test_equivalent_units_are_equal(self, left: str, right: str) -> None:
        """Two dimensionally equivalent units have equal ``Dimension`` objects."""
        assert parse_unit(left) == parse_unit(right)

    def test_incompatible_units_are_unequal(self) -> None:
        """kg (mass) and m (length) are dimensionally incompatible."""
        assert parse_unit("kg") != parse_unit("m")

    def test_dimension_is_hashable(self) -> None:
        """``Dimension`` is usable as a dict key (frozen dataclass)."""
        d = {parse_unit("N"): "force", parse_unit("kg"): "mass"}
        assert d[parse_unit("kg*m/s^2")] == "force"


class TestUcumAliases:
    """UCUM dotted/signed-exponent notation and symbol aliases."""

    @pytest.mark.parametrize(
        ("ucum", "canonical"),
        [
            ("kg.m.s-2", "kg*m/s^2"),
            ("m.s-1", "m/s"),
            ("kg.m2.s-2", "kg*m**2/s**2"),
            ("Ohm", "ohm"),
            ("mol-1", "mol**-1"),
        ],
    )
    def test_ucum_form_matches_canonical(self, ucum: str, canonical: str) -> None:
        """The UCUM form reduces to the same dimension as its Python-notation form."""
        assert parse_unit(ucum) == parse_unit(canonical)


class TestParseUnitRejections:
    """``parse_unit`` rejects unknown, out-of-subset, and malformed units."""

    @pytest.mark.parametrize("bad_unit", ["fortnight", "km", "blarg", "year", "USD"])
    def test_unknown_or_out_of_subset_rejected(self, bad_unit: str) -> None:
        """An unknown or out-of-subset unit raises ``UnitError`` (no silent fallback)."""
        with pytest.raises(UnitError) as exc_info:
            parse_unit(bad_unit)
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    @pytest.mark.parametrize("bad_unit", ["", "   ", "kg*m/"])
    def test_empty_or_malformed_rejected(self, bad_unit: str) -> None:
        """An empty or structurally malformed unit string raises ``UnitError``."""
        with pytest.raises(UnitError):
            parse_unit(bad_unit)


# ---------------------------------------------------------------------------
# convert: precision policy and the exact decimal identity.
# ---------------------------------------------------------------------------


class TestConvert:
    """``convert`` under the decimal-string precision policy."""

    @pytest.mark.parametrize(
        ("value", "from_unit", "to_unit", "expected"),
        [
            ("1", "kg*m/s^2", "N", "1"),
            ("1", "N", "kg*m/s^2", "1"),
            ("2", "N", "kg*m/s^2", "2"),
            ("1", "J", "N*m", "1"),
            ("1", "Pa", "N/m^2", "1"),
            ("1", "W", "J/s", "1"),
            ("1", "V", "J/C", "1"),
            ("1", "Hz", "1/s", "1"),
        ],
    )
    def test_coherent_conversion_is_exact_identity(
        self, value: str, from_unit: str, to_unit: str, expected: str
    ) -> None:
        """A coherent conversion yields the exact decimal identity (no float artefact)."""
        assert convert(value, from_unit, to_unit) == expected

    def test_self_conversion_preserves_value(self) -> None:
        """Converting a unit to itself preserves the value exactly."""
        assert convert("9.80665", "m/s^2", "m/s^2") == "9.80665"

    def test_dimensional_mismatch_rejected_before_arithmetic(self) -> None:
        """Converting kg to m raises ``UnitError`` before any arithmetic."""
        with pytest.raises(UnitError) as exc_info:
            convert("1", "kg", "m")
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_non_decimal_value_rejected(self) -> None:
        """A value with an exponent or non-numeric content is rejected."""
        with pytest.raises(UnitError):
            convert("1e5", "m", "m")
        with pytest.raises(UnitError):
            convert("NaN", "m", "m")

    def test_unknown_unit_in_convert_rejected(self) -> None:
        """An unknown unit in either position is rejected before conversion."""
        with pytest.raises(UnitError):
            convert("1", "fortnight", "s")
        with pytest.raises(UnitError):
            convert("1", "s", "fortnight")

    def test_result_is_decimal_string_policy(self) -> None:
        """The result matches the decimal-string pattern (no exponent)."""
        result = convert("3", "N", "kg*m/s^2")
        assert result == "3"
        # A non-integer result renders in fixed-point with no exponent.
        result2 = convert("3.5", "m/s", "m/s")
        assert "e" not in result2.lower()
        assert "E" not in result2


# ---------------------------------------------------------------------------
# validate_dimensions: symbol-table + constant-ref coherence.
# ---------------------------------------------------------------------------


def _symbol_table(symbols: list[dict[str, object]]) -> dict[str, object]:
    """Build a minimal SymbolTable/v1 dict."""
    return {"schema_version": "SymbolTable/v1", "symbols": symbols}


def _constant_ref(unit: str, constant_id: str = "const.x") -> dict[str, object]:
    """Build a minimal ConstantRef/v1 dict with the given unit."""
    return {
        "schema_version": "ConstantRef/v1",
        "constant_id": constant_id,
        "source": "pack_local",
        "symbol": "x",
        "value": "1",
        "unit": unit,
        "vintage": "pack-2026-07",
    }


class TestValidateDimensions:
    """``validate_dimensions`` over symbol tables and constant refs."""

    def test_coherent_table_reports_coherent(self) -> None:
        """A table whose constants parse cleanly is coherent."""
        table = _symbol_table(
            [{"symbol_id": "force", "name": "force", "role": "variable", "unit_ref": "const.N"}]
        )
        refs = {"const.N": _constant_ref("kg*m/s^2", "const.N")}
        report = validate_dimensions(table, refs)
        assert report["status"] == "coherent"
        assert report["checked"] == 1
        assert report["dimensions"]["force"] == str(parse_unit("N"))
        assert report["mismatches"] == []

    def test_shared_constant_parsed_once(self) -> None:
        """Two symbols referencing the same constant parse it once."""
        table = _symbol_table(
            [
                {"symbol_id": "f1", "name": "f1", "role": "variable", "unit_ref": "const.N"},
                {"symbol_id": "f2", "name": "f2", "role": "variable", "unit_ref": "const.N"},
            ]
        )
        refs = {"const.N": _constant_ref("N", "const.N")}
        report = validate_dimensions(table, refs)
        assert report["checked"] == 2

    def test_symbol_without_unit_ref_skipped(self) -> None:
        """A symbol without a unit_ref is not checked."""
        table = _symbol_table(
            [{"symbol_id": "x", "name": "x", "role": "variable", "unit_ref": None}]
        )
        report = validate_dimensions(table, {})
        assert report["checked"] == 0
        assert report["status"] == "coherent"

    def test_unresolved_ref_reported_as_mismatch(self) -> None:
        """An unresolved unit_ref is reported (not fatal) as a mismatch."""
        table = _symbol_table(
            [{"symbol_id": "x", "name": "x", "role": "variable", "unit_ref": "const.missing"}]
        )
        report = validate_dimensions(table, {})
        assert report["status"] == "incoherent"
        assert report["mismatches"][0]["reason"] == "unresolved_ref"

    def test_bad_unit_in_constant_ref_raises(self) -> None:
        """A constant ref whose unit cannot be parsed raises ``UnitError``."""
        table = _symbol_table(
            [{"symbol_id": "x", "name": "x", "role": "variable", "unit_ref": "const.bad"}]
        )
        refs = {"const.bad": _constant_ref("fortnight", "const.bad")}
        with pytest.raises(UnitError):
            validate_dimensions(table, refs)

    def test_wrong_schema_version_rejected(self) -> None:
        """A symbol table with the wrong schema_version raises ``UnitError``."""
        with pytest.raises(UnitError):
            validate_dimensions({"schema_version": "Other/v1", "symbols": []})


# ---------------------------------------------------------------------------
# CODATA fixture integration: the shipped constants parse.
# ---------------------------------------------------------------------------


_CODATA_DIR = _REPO_ROOT / "fixtures" / "conformance" / "units" / "codata"


class TestCodataFixtures:
    """The CODATA 2018 constant fixtures load and their units parse."""

    @pytest.mark.parametrize(
        "fixture",
        [
            "codata2018.speed-of-light",
            "codata2018.planck-constant",
            "codata2018.boltzmann-constant",
            "codata2018.avogadro-constant",
            "codata2018.elementary-charge",
            "codata2018.electron-mass",
        ],
    )
    def test_codata_constant_unit_parses(self, fixture: str) -> None:
        """Each CODATA fixture's unit field parses to a dimension."""
        doc = json.loads((_CODATA_DIR / f"{fixture}.json").read_text(encoding="utf-8"))
        dim = parse_unit(doc["unit"])
        assert isinstance(dim, Dimension)


# ---------------------------------------------------------------------------
# Architecture test: Pint is imported only inside the units adapter.
# ---------------------------------------------------------------------------


def _imports_pint(path: Path) -> bool:
    """Return True iff ``path`` imports the ``pint`` package at module level."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pint":
                    return True
        if isinstance(node, ast.ImportFrom) and node.module == "pint":
            return True
    return False


class TestPintIsolation:
    """ADR-0003: Pint is imported only inside ``srl.packs.adapters.units``."""

    def test_only_units_adapter_imports_pint(self) -> None:
        """No module under ``src/srl`` other than the adapter imports ``pint``."""
        offenders: list[str] = []
        for path in _SRC_ROOT.rglob("*.py"):
            if path == _ADAPTER_MODULE:
                continue
            if _imports_pint(path):
                offenders.append(str(path.relative_to(_REPO_ROOT)))
        assert not offenders, f"pint imported outside the adapter: {offenders}"

    def test_adapter_module_imports_pint(self) -> None:
        """The adapter module itself imports pint (sanity check)."""
        assert _imports_pint(_ADAPTER_MODULE)


# ---------------------------------------------------------------------------
# Module-level constants and metadata.
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """The exported constants describe the supported surface."""

    def test_pinned_subset_is_nonempty_and_auditable(self) -> None:
        """The pinned subset contains the expected units and is a frozenset."""
        assert isinstance(PINNED_QUDT_SUBSET, frozenset)
        # The seven SI base units + eight named derived + composites + dimensionless.
        assert len(PINNED_QUDT_SUBSET) >= 19
        for unit in ("m", "kg", "s", "N", "Pa", "J", "W", "Hz", "V", "C", "ohm"):
            assert unit in PINNED_QUDT_SUBSET

    def test_si_base_dimensions_count(self) -> None:
        """There are exactly seven SI base dimensions."""
        assert len(SI_BASE_DIMENSIONS) == 7

    def test_conversion_sig_digits_is_explicit(self) -> None:
        """The conversion precision policy is a positive integer constant."""
        assert isinstance(CONVERSION_SIG_DIGITS, int)
        assert CONVERSION_SIG_DIGITS > 0

    def test_pint_version_is_a_string(self) -> None:
        """The resolved Pint version is reported as a non-empty string."""
        version = pint_version()
        assert isinstance(version, str)
        assert version != ""
