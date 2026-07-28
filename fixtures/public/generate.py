#!/usr/bin/env python3
"""Deterministic, stdlib-only generator for the public synthetic fixture corpus.

Subcommands
-----------
all       Generate every fixture, the MANIFEST, and the README.
series    Generate the three synthetic univariate time series.
cloud     Generate the three synthetic point clouds.
spd       Generate the synthetic SPD matrices.
claims    Generate the six synthetic ScientificClaim-shaped objects.

All output is canonical JSON (sorted keys, compact separators, UTF-8, no
NaN/Infinity) and includes explicit provenance: seed, generator_version, and a
CC0-1.0 license note. The generator is intentionally self-contained and uses
only the Python standard library so it can be audited and run without
installing dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Provenance constants
# ---------------------------------------------------------------------------
GENERATOR_VERSION: Final[str] = "wp-a05-1.0.0"
SEED: Final[int] = 20260728
LICENSE: Final[str] = "CC0-1.0"
CREATED_UTC: Final[str] = "2026-07-28T00:00:00Z"

# ---------------------------------------------------------------------------
# Path layout
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent

_SERIES_VARIANTS: Final[tuple[str, ...]] = ("trend-plus-noise", "regime-shift", "pure-noise")
_SERIES_POINTS: Final[int] = 512

_CLOUD_VARIANTS: Final[tuple[str, ...]] = ("circle", "two-cluster", "uniform-square")
_CLOUD_SIZES: Final[dict[str, int]] = {
    "circle": 100,
    "two-cluster": 128,
    "uniform-square": 128,
}

_SPD_SIZES: Final[tuple[int, ...]] = (3, 5)

_CLAIM_COUNT: Final[int] = 6


def _canonical_json(obj: Any) -> str:
    """Return canonical JSON: sorted keys, compact separators, ASCII, no NaN."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _write_json(path: Path, obj: Any) -> None:
    """Write canonical JSON plus a trailing newline."""
    path.write_text(_canonical_json(obj) + "\n", encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of a byte string."""
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's contents."""
    return _sha256_bytes(path.read_bytes())


def _seeded_random(variant: str) -> random.Random:
    """Return a deterministic Random seeded from the global seed + variant."""
    rng = random.Random(f"{GENERATOR_VERSION}:{SEED}:{variant}")  # noqa: S311
    return rng


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------
def _generate_series(variant: str, rng: random.Random) -> list[float]:
    """Generate one 512-point univariate series."""
    values: list[float] = []
    if variant == "trend-plus-noise":
        for i in range(_SERIES_POINTS):
            values.append(0.01 * i + rng.gauss(0.0, 0.5))
    elif variant == "regime-shift":
        for i in range(_SERIES_POINTS):
            mean = 2.0 if i < (_SERIES_POINTS // 2) else -1.0
            values.append(mean + rng.gauss(0.0, 1.0))
    elif variant == "pure-noise":
        for _ in range(_SERIES_POINTS):
            values.append(rng.gauss(0.0, 1.0))
    else:
        raise ValueError(f"unknown series variant: {variant}")
    return values


def generate_series(output_dir: Path) -> list[Path]:
    """Generate the three time-series fixtures."""
    written: list[Path] = []
    for variant in _SERIES_VARIANTS:
        rng = _seeded_random(f"series:{variant}")
        document = {
            "generator_version": GENERATOR_VERSION,
            "license": LICENSE,
            "points": _SERIES_POINTS,
            "seed": SEED,
            "synthetic": True,
            "type": "SyntheticUnivariateSeries/v1",
            "variant": variant,
            "values": _generate_series(variant, rng),
        }
        path = output_dir / f"series-{variant}.json"
        _write_json(path, document)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Point clouds
# ---------------------------------------------------------------------------
def _format_decimal(value: float, decimals: int = 6) -> str:
    """Format a float as a fixed-width decimal string for canonical round-trip."""
    return format(value, f".{decimals}f")


def _generate_cloud(variant: str, rng: random.Random) -> list[list[str]]:
    """Generate a 2-D point cloud with coordinates as decimal strings."""
    points: list[list[str]] = []
    n = _CLOUD_SIZES[variant]
    if variant == "circle":
        radius = 1.0
        for _ in range(n):
            theta = rng.uniform(0.0, 2.0 * math.pi)
            noise = rng.gauss(0.0, 0.03)
            x = (radius + noise) * math.cos(theta)
            y = (radius + noise) * math.sin(theta)
            points.append([_format_decimal(x), _format_decimal(y)])
    elif variant == "two-cluster":
        centers = [(-1.0, 0.0), (1.0, 0.0)]
        for i in range(n):
            cx, cy = centers[i % 2]
            x = cx + rng.gauss(0.0, 0.25)
            y = cy + rng.gauss(0.0, 0.25)
            points.append([_format_decimal(x), _format_decimal(y)])
    elif variant == "uniform-square":
        for _ in range(n):
            x = rng.uniform(-1.0, 1.0)
            y = rng.uniform(-1.0, 1.0)
            points.append([_format_decimal(x), _format_decimal(y)])
    else:
        raise ValueError(f"unknown cloud variant: {variant}")
    return points


def generate_clouds(output_dir: Path) -> list[Path]:
    """Generate the three point-cloud fixtures."""
    written: list[Path] = []
    for variant in _CLOUD_VARIANTS:
        rng = _seeded_random(f"cloud:{variant}")
        document = {
            "generator_version": GENERATOR_VERSION,
            "license": LICENSE,
            "points": _generate_cloud(variant, rng),
            "point_count": _CLOUD_SIZES[variant],
            "seed": SEED,
            "synthetic": True,
            "type": "SyntheticPointCloud/v1",
            "variant": variant,
        }
        path = output_dir / f"cloud-{variant}.json"
        _write_json(path, document)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# SPD matrices
# ---------------------------------------------------------------------------
def _make_lower_triangular(size: int, rng: random.Random) -> list[list[int]]:
    """Create a lower-triangular integer matrix with positive diagonal."""
    matrix: list[list[int]] = []
    for row in range(size):
        row_values: list[int] = []
        for col in range(size):
            if col < row:
                row_values.append(rng.randint(-3, 3))
            elif col == row:
                row_values.append(rng.randint(2, 5))
            else:
                row_values.append(0)
        matrix.append(row_values)
    return matrix


def _matrix_multiply_lt(a: list[list[int]]) -> list[list[int]]:
    """Compute A = L * L^T for a square lower-triangular integer L."""
    size = len(a)
    result: list[list[int]] = [[0 for _ in range(size)] for _ in range(size)]
    for i in range(size):
        for j in range(size):
            total = 0
            for k in range(size):
                total += a[i][k] * a[j][k]
            result[i][j] = total
    return result


def generate_spd(output_dir: Path) -> list[Path]:
    """Generate SPD matrices by constructing A = L * L^T."""
    written: list[Path] = []
    for size in _SPD_SIZES:
        rng = _seeded_random(f"spd:{size}")
        lower = _make_lower_triangular(size, rng)
        matrix = _matrix_multiply_lt(lower)
        document = {
            "constructed_as": "A = L * L^T",
            "generator_version": GENERATOR_VERSION,
            "license": LICENSE,
            "matrix": matrix,
            "lower_triangular_l": lower,
            "seed": SEED,
            "size": size,
            "synthetic": True,
            "type": "SyntheticSPDMatrix/v1",
        }
        path = output_dir / f"spd-{size}x{size}.json"
        _write_json(path, document)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Synthetic claims
# ---------------------------------------------------------------------------
def _synthetic_sha256_ref(label: str) -> str:
    """Return a deterministic synthetic object_id reference."""
    digest = _sha256_bytes(f"synthetic:{label}".encode())
    return f"sha256:{digest}"


def _claim_id(statement: dict[str, Any]) -> str:
    """Compute a content-addressed claim_id matching the SRL canonical form."""
    text = json.dumps(
        statement,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    digest = _sha256_bytes((text + "\n").encode("utf-8"))
    return f"sha256:{digest}"


def _claim_statement(index: int) -> dict[str, Any]:
    """Return the i-th synthetic claim statement (without claim_id)."""
    statements = [
        {
            "schema_version": "ScientificClaim/v1",
            "statement": {
                "subject": "synthetic-noise-series",
                "predicate": "has-zero-mean",
                "object": "under-null-model",
            },
            "claim_class": "candidate_hypothesis",
            "claim_status": "proposed",
            "epistemic_source": "operator",
            "support_refs": [],
            "created_utc": CREATED_UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        {
            "schema_version": "ScientificClaim/v1",
            "statement": {
                "subject": "synthetic-trend-series",
                "predicate": "slope",
                "object": "positive",
            },
            "claim_class": "empirical_observation",
            "claim_status": "supported",
            "epistemic_source": "experiment",
            "support_refs": [_synthetic_sha256_ref("support-trend")],
            "created_utc": CREATED_UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        {
            "schema_version": "ScientificClaim/v1",
            "statement": {
                "subject": "synthetic-circle-cloud",
                "predicate": "topology",
                "object": "one-dimensional-cycle",
            },
            "claim_class": "candidate_hypothesis",
            "claim_status": "under_investigation",
            "epistemic_source": "operator",
            "support_refs": [],
            "created_utc": CREATED_UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        {
            "schema_version": "ScientificClaim/v1",
            "statement": {
                "subject": "synthetic-spd-3x3",
                "predicate": "is-positive-definite",
                "object": "by-construction",
            },
            "claim_class": "derived_result",
            "claim_status": "supported",
            "epistemic_source": "derivation",
            "support_refs": [_synthetic_sha256_ref("support-spd-proof")],
            "created_utc": CREATED_UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        {
            "schema_version": "ScientificClaim/v1",
            "statement": {
                "subject": "synthetic-two-cluster-cloud",
                "predicate": "has-cluster-count",
                "object": "two",
            },
            "claim_class": "candidate_hypothesis",
            "claim_status": "proposed",
            "epistemic_source": "operator",
            "support_refs": [],
            "created_utc": CREATED_UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        {
            "schema_version": "ScientificClaim/v1",
            "statement": {
                "subject": "synthetic-regime-series",
                "predicate": "mean-shift-at",
                "object": "midpoint",
            },
            "claim_class": "empirical_observation",
            "claim_status": "inconclusive",
            "epistemic_source": "experiment",
            "support_refs": [_synthetic_sha256_ref("support-regime")],
            "created_utc": CREATED_UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
    ]
    return statements[index]


def _enrich_claim(statement: dict[str, Any]) -> dict[str, Any]:
    """Add a deterministic claim_id to a claim statement."""
    enriched = dict(statement)
    enriched["claim_id"] = _claim_id(statement)
    return enriched


def generate_claims(output_dir: Path) -> list[Path]:
    """Generate the six synthetic ScientificClaim-shaped objects."""
    written: list[Path] = []
    for i in range(_CLAIM_COUNT):
        statement = _claim_statement(i)
        claim = _enrich_claim(statement)
        path = output_dir / f"claim-{i:02d}.json"
        _write_json(path, claim)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# MANIFEST
# ---------------------------------------------------------------------------
def _manifest_excluded(name: str) -> bool:
    """Files that are provenance documents, not corpus artifacts."""
    return name in {"MANIFEST.json", "README.md", "generate.py"}


def generate_manifest(output_dir: Path) -> Path:
    """Generate MANIFEST.json with sha256 and byte size for every fixture."""
    entries: dict[str, Any] = {}
    for path in sorted(output_dir.iterdir()):
        if not path.is_file() or _manifest_excluded(path.name):
            continue
        entries[path.name] = {
            "byte_size": path.stat().st_size,
            "generator_version": GENERATOR_VERSION,
            "license": LICENSE,
            "sha256": _sha256_file(path),
        }
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "license": LICENSE,
        "entries": entries,
        "seed": SEED,
    }
    manifest_path = output_dir / "MANIFEST.json"
    _write_json(manifest_path, manifest)
    return manifest_path


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------
_README_TEXT: Final[str] = """# Public synthetic fixture corpus

This directory contains a fully synthetic, deterministic corpus used for
tutorials, CI gates, and reproducible examples in the Scientific Resource Lab.

## Provenance

Every artifact in this directory was generated by `fixtures/public/generate.py`
using the Python standard library only. No real data, personal information, or
proprietary sources were used. The corpus is therefore safe to redistribute,
modify, and include in public repositories and CI logs.

- Generator version: `wp-a05-1.0.0`
- Deterministic seed: `20260728`
- License: `CC0-1.0`

## Regeneration

To regenerate the corpus in place from the repository root:

```bash
python3 fixtures/public/generate.py all
```

Running the generator twice and comparing `MANIFEST.json` entries produces
identical SHA-256 digests, confirming byte-determinism.

## Redistribution clearance

The entire `fixtures/public/` corpus is released under CC0-1.0. You may copy,
modify, distribute, and use it for any purpose without attribution or
permission.

## Contents

- `series-*.json` — synthetic univariate time series (512 points each).
- `cloud-*.json` — synthetic 2-D point clouds for future TDA tutorials.
- `spd-*.json` — synthetic positive-definite matrices constructed as `A = L * L^T`.
- `claim-*.json` — synthetic ScientificClaim-shaped objects for tutorial use.
- `MANIFEST.json` — per-file SHA-256, byte size, and provenance.
"""


def generate_readme(output_dir: Path) -> Path:
    """Write the README.md provenance document."""
    path = output_dir / "README.md"
    path.write_text(_README_TEXT, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _all_paths(written: list[Path]) -> None:
    """Print each generated path to stdout."""
    for path in written:
        print(path)


def cmd_all(args: argparse.Namespace) -> int:
    """Generate the full corpus, manifest, and README."""
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    written.extend(generate_series(output_dir))
    written.extend(generate_clouds(output_dir))
    written.extend(generate_spd(output_dir))
    written.extend(generate_claims(output_dir))
    written.append(generate_manifest(output_dir))
    written.append(generate_readme(output_dir))
    _all_paths(written)
    return 0


def cmd_series(args: argparse.Namespace) -> int:
    """Generate only the time series fixtures."""
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    _all_paths(generate_series(output_dir))
    return 0


def cmd_cloud(args: argparse.Namespace) -> int:
    """Generate only the point cloud fixtures."""
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    _all_paths(generate_clouds(output_dir))
    return 0


def cmd_spd(args: argparse.Namespace) -> int:
    """Generate only the SPD matrix fixtures."""
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    _all_paths(generate_spd(output_dir))
    return 0


def cmd_claims(args: argparse.Namespace) -> int:
    """Generate only the synthetic claim fixtures."""
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    _all_paths(generate_claims(output_dir))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="Generate the SRL public synthetic fixture corpus.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_HERE,
        help="Directory to write fixtures to (default: the script's directory).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("all", help="Generate every fixture, MANIFEST, and README.")
    subparsers.add_parser("series", help="Generate the synthetic time series.")
    subparsers.add_parser("cloud", help="Generate the synthetic point clouds.")
    subparsers.add_parser("spd", help="Generate the synthetic SPD matrices.")
    subparsers.add_parser("claims", help="Generate the synthetic claim set.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch the CLI subcommand."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers: dict[str, Any] = {
        "all": cmd_all,
        "series": cmd_series,
        "cloud": cmd_cloud,
        "spd": cmd_spd,
        "claims": cmd_claims,
    }
    handler = handlers[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
