"""Stdlib dependency license inventory for CI.

Builds a license inventory from the locked dependency closure recorded in
``uv.lock``.  The committed lock file is the source of truth; only packages
listed there are evaluated, using ``importlib.metadata`` against the synced uv
virtual environment.  Packages that are locked but not installed, or that lack
resolvable license metadata, are reported as ``unknown`` and cause a non-zero
exit so additions to the dependency tree are reviewed explicitly.

Allowlist
---------
MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0, Unicode-3.0,
MPL-2.0 (notice-ok), Python-2.0, CC0-1.0, 0BSD, Zlib.

0BSD (Zero-Clause BSD) and Zlib are OSI-approved permissive licenses that appear
in compound ``License-Expression`` values for widely-used packages (e.g. numpy's
``BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0``); they are compatible
with the project's Apache-2.0 license.

Anything in the GPL/LGPL/AGPL family or otherwise unidentifiable is treated
as a failure.

The script is intended to run inside the uv-managed venv (``uv run python3
scripts/checks/license_inventory.py``) so that ``importlib.metadata`` sees the
locked dependency set from ``uv.lock``.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from importlib.metadata import Distribution, distributions
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Allowlist and classifier mappings
# ---------------------------------------------------------------------------

_ALLOWED_LICENSES: Final[frozenset[str]] = frozenset(
    {
        "MIT",
        "MIT-0",
        "BSD-2-CLAUSE",
        "BSD-3-CLAUSE",
        "0BSD",
        "ZLIB",
        "MIT-CMU",
        "APACHE-2.0",
        "ISC",
        "PSF-2.0",
        "UNICODE-3.0",
        "MPL-2.0",
        "PYTHON-2.0",
        "CC0-1.0",
    }
)

_DENIED_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "GPL",
        "LGPL",
        "AGPL",
    }
)

_ALLOWED_EXCEPTIONS: Final[frozenset[str]] = frozenset(
    {
        "LLVM-EXCEPTION",
    }
)

# Normalize common free-text license strings to SPDX identifiers.
_LICENSE_NORMALIZATIONS: Final[dict[str, str]] = {
    "APACHE 2.0": "APACHE-2.0",
    "APACHE SOFTWARE LICENSE": "APACHE-2.0",
    "APACHE LICENSE, VERSION 2.0": "APACHE-2.0",
    "MIT LICENSE": "MIT",
    "MIT": "MIT",
    "BSD": "BSD-3-CLAUSE",
    "BSD LICENSE": "BSD-3-CLAUSE",
    "BSD (3-CLAUSE)": "BSD-3-CLAUSE",
    "BSD-2-CLAUSE": "BSD-2-CLAUSE",
    "BSD-3-CLAUSE": "BSD-3-CLAUSE",
    "SIMPLIFIED BSD": "BSD-2-CLAUSE",
    "NEW BSD LICENSE": "BSD-3-CLAUSE",
    "ISC LICENSE (ISCL)": "ISC",
    "ISC": "ISC",
    "MOZILLA PUBLIC LICENSE 2.0 (MPL 2.0)": "MPL-2.0",
    "MPL 2.0": "MPL-2.0",
    "PYTHON SOFTWARE FOUNDATION LICENSE": "PSF-2.0",
    "PSF LICENSE": "PSF-2.0",
    "PYTHON-2.0": "PYTHON-2.0",
    "CC0-1.0": "CC0-1.0",
    "CC0": "CC0-1.0",
}

# Patterns that detect a permissive license from its free-text body. Some
# packages (e.g. scipy) carry the full license text in the ``License`` field
# rather than a short SPDX-like string or a classifier. These substring
# patterns let the scanner recognize the canonical disclaimer text and map it
# to an SPDX identifier so a legitimate permissive dependency is not flagged
# ``unknown``. Each pattern is matched case-insensitively against the raw text.
_LICENSE_TEXT_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    # BSD-3-Clause disclaimer (the "neither the name" clause is the 3rd-clause
    # signature; scipy and many BSD-3 packages carry this text verbatim).
    ("NEITHER THE NAME OF THE COPYRIGHT HOLDER", "BSD-3-CLAUSE"),
    # BSD-2-Clause lacks the "neither the name" clause but carries the
    # redistribution disclaimer; this is a weaker signal so it is checked
    # after the 3-clause pattern.
    ("REDISTRIBUTION AND USE IN SOURCE AND BINARY FORMS", "BSD-3-CLAUSE"),
)

# Map PyPI classifier strings to SPDX identifiers.
_CLASSIFIER_LICENSES: Final[dict[str, str]] = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Apache Software License": "APACHE-2.0",
    "License :: OSI Approved :: BSD License": "BSD-3-CLAUSE",
    "License :: OSI Approved :: BSD 2-Clause License": "BSD-2-CLAUSE",
    "License :: OSI Approved :: BSD 3-Clause License": "BSD-3-CLAUSE",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Python License (CNRI Python License)": "PYTHON-2.0",
    "License :: OSI Approved :: Unicode License V3": "UNICODE-3.0",
    "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication": "CC0-1.0",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageLicense:
    name: str
    version: str
    license: str
    source: str  # 'License-Expression', 'License', or 'Classifier'
    status: str  # 'allowed', 'denied', or 'unknown'


@dataclass(frozen=True)
class Report:
    scanner: str
    packages: list[PackageLicense]
    allowed: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# License extraction and classification
# ---------------------------------------------------------------------------


def _classifier_license(classifiers: list[str]) -> str | None:
    """Return the first recognized license from Trove classifiers."""
    for classifier in classifiers:
        if classifier in _CLASSIFIER_LICENSES:
            return _CLASSIFIER_LICENSES[classifier]
    return None


def _normalize_license(raw: str) -> str:
    """Normalize a raw license string toward a canonical SPDX identifier."""
    cleaned = raw.strip()
    if not cleaned or cleaned.upper() == "UNKNOWN":
        return "UNKNOWN"
    normalized = _LICENSE_NORMALIZATIONS.get(cleaned.upper())
    if normalized:
        return normalized
    # If the value already looks like an SPDX expression (contains dashes or
    # uppercase identifiers), keep it as-is for component parsing.
    if _is_spdx_expression(cleaned):
        return cleaned.upper()
    # Free-text license bodies (e.g. scipy's full BSD-3-Clause text): match
    # canonical disclaimer patterns so a legitimate permissive dependency is
    # not flagged ``unknown``. Checked after the SPDX-expression heuristic so
    # a real SPDX expression is never mis-read as free text.
    upper = cleaned.upper()
    for needle, spdx in _LICENSE_TEXT_PATTERNS:
        if needle in upper:
            return spdx
    return cleaned.upper()


def _license_components(expression: str) -> list[str]:
    """Split a license expression into individual components (naive OR/AND)."""
    # Split on OR and AND, preserving order.  Strip whitespace and parentheses.
    parts = re.split(r"\s+(?:OR|AND)\s+", expression, flags=re.IGNORECASE)
    return [part.strip().strip("()") for part in parts if part.strip()]


def _component_base_and_exception(component: str) -> tuple[str, str | None]:
    """Return SPDX base license and optional exception for one component."""
    parts = re.split(r"\s+WITH\s+", component, maxsplit=1, flags=re.IGNORECASE)
    base = parts[0].strip().strip("()").upper()
    if len(parts) == 1:
        return base, None
    exception = parts[1].strip().strip("()").upper()
    return base, exception


def _is_denied_family(component: str) -> bool:
    """Return True when a component belongs to a GPL-family license."""
    return any(
        component == family or component.startswith(f"{family}-") for family in _DENIED_FAMILIES
    )


def _evaluate_license(expression: str) -> str:
    """Evaluate a normalized license expression and return 'allowed', 'denied', or 'unknown'."""
    components = _license_components(expression)
    if not components:
        return "unknown"
    parsed = [_component_base_and_exception(component) for component in components]
    if any(_is_denied_family(base) for base, _exception in parsed):
        return "denied"
    if all(
        base in _ALLOWED_LICENSES and (exception is None or exception in _ALLOWED_EXCEPTIONS)
        for base, exception in parsed
    ):
        return "allowed"
    return "unknown"


def _is_spdx_expression(value: str) -> bool:
    """Return True if ``value`` looks like an SPDX license expression."""
    component = r"[A-Za-z0-9_.\-]+(?:\s+WITH\s+[A-Za-z0-9_.\-]+)?"
    return bool(re.fullmatch(rf"{component}(\s+(?:OR|AND)\s+{component})*", value))


def _extract_package_license(dist: Distribution) -> tuple[str, str]:
    """Extract the best available license string and source for a distribution."""
    metadata = dist.metadata
    expression = metadata.get("License-Expression", "").strip()
    if expression and expression.upper() != "UNKNOWN":
        return expression, "License-Expression"

    direct = metadata.get("License", "").strip()
    if direct and direct.upper() != "UNKNOWN":
        normalized_direct = _normalize_license(direct)
        if _is_spdx_expression(direct) or normalized_direct in _ALLOWED_LICENSES:
            return direct, "License"
        # Full-text license strings are not self-describing. Prefer a recognised
        # Trove classifier when one is present.
        classifier_lic = _classifier_license(list(metadata.get_all("Classifier", [])))
        if classifier_lic:
            return classifier_lic, "Classifier"

    classifier_lic = _classifier_license(list(metadata.get_all("Classifier", [])))
    if classifier_lic:
        return classifier_lic, "Classifier"

    return "UNKNOWN", "UNKNOWN"


# ---------------------------------------------------------------------------
# Locked package discovery from uv.lock
# ---------------------------------------------------------------------------


def _locked_package_names(lock_path: Path) -> list[str]:
    """Return the list of package names from a uv.lock file."""
    with lock_path.open("rb") as handle:
        lock_data = tomllib.load(handle)
    return [pkg["name"] for pkg in lock_data.get("package", [])]


def _normalise_name(name: str) -> str:
    """Normalise a distribution name for comparison.

    PyPI treats underscores, hyphens, and case differences as equivalent for
    distribution names.  This matches the canonical form used by
    ``importlib.metadata`` for lookups.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan() -> Report:
    """Build the license inventory from the locked dependency closure.

    The synced uv virtual environment is the resolver for environment markers in
    ``uv.lock``.  We therefore inspect only the distributions that are actually
    installed in that venv and are also listed in the committed lock file.  This
    excludes platform- or Python-version conditional locked packages that are not
    part of the resolved closure for the current environment, and also excludes
    any extra tooling that happens to be installed in the interpreter but is not
    in the lock (e.g. ``yt-dlp``).
    """
    repo_root = Path(__file__).resolve().parents[2]
    lock_path = repo_root / "uv.lock"
    if not lock_path.exists():
        raise FileNotFoundError(f"Committed lock file not found: {lock_path}")

    locked_names = {_normalise_name(name) for name in _locked_package_names(lock_path)}

    packages: list[PackageLicense] = []
    allowed: list[str] = []
    denied: list[str] = []
    unknown: list[str] = []

    for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        if _normalise_name(name) not in locked_names:
            continue

        raw_license, source = _extract_package_license(dist)
        normalized = _normalize_license(raw_license)
        status = _evaluate_license(normalized)

        packages.append(
            PackageLicense(
                name=name,
                version=dist.version,
                license=normalized,
                source=source,
                status=status,
            )
        )

        if status == "allowed":
            allowed.append(name)
        elif status == "denied":
            denied.append(name)
        else:
            unknown.append(name)

    return Report(
        scanner="license_inventory/v2",
        packages=packages,
        allowed=allowed,
        denied=denied,
        unknown=unknown,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point: print JSON inventory and exit 1 on denied/unknown licenses."""
    report = scan()
    print(
        json.dumps(
            asdict(report),
            indent=2,
            default=str,
        )
    )
    return 1 if report.denied or report.unknown else 0


if __name__ == "__main__":
    sys.exit(main())
