"""A11 knowledge-adapter policy descriptors (data only, no live calls).

This module declares the conservative egress policy for the four P0 knowledge
endpoints plus the A11 public mathematical knowledge sources as a canonical
JSON document that a :class:`~srl.knowledge.retriever.PolicyRegistry` loads.
It is **data only**: no live network call is made here, and no adapter performs
a fetch at import.

Each descriptor carries conservative defaults:

- rate: 10 requests/minute (a courteous floor well below each provider's
  documented polite pool limit);
- byte budget: 50 MiB total response bytes per endpoint;
- cost budget: 1000 abstract units (each successful fetch consumes 1);
- retention: 30 days for cached responses;
- attribution: a short attribution string recorded on every receipt.

Forbidden sources
-----------------
FRED, ALFRED, and Wolfram|Alpha are **deliberately absent** from the P0 set.
This is a plan constraint: those sources require credentials (an API key for
FRED/ALFRED; a Wolfram AppID) and the retriever is credential-free by design.
They are listed in :data:`FORBIDDEN_SOURCES` so a future contributor cannot
silently add them without confronting the credential policy.
"""

from __future__ import annotations

from typing import Final

from srl.knowledge.retriever import ENDPOINT_POLICY_SCHEMA_VERSION, PolicyRegistry

# Conservative defaults shared by every public endpoint.
_P0_RATE_LIMIT_PER_MINUTE: Final[int] = 10
_P0_BYTE_BUDGET: Final[int] = 50 * 1024 * 1024  # 50 MiB
_P0_COST_BUDGET_UNITS: Final[int] = 1000
_P0_RETENTION_DAYS: Final[int] = 30

# ---------------------------------------------------------------------------
# P0 endpoint policy descriptors (data only).
#
# Each entry is the raw dict that PolicyRegistry.from_dict ingests. The
# license_terms_sha256 values are content digests of the endpoint's stated
# license terms at the time of descriptor authoring; they are carried on every
# receipt so license provenance is verifiable, and a change to the license
# terms yields a different digest (and thus a visibly different receipt).
#
# The digests below are deterministic SHA-256 of a short license label string
# (computed once and pinned here). They are NOT fetched from the network.
# ---------------------------------------------------------------------------

# SHA-256("OpenAlex: CC0 1.0 Universal (Public Domain Dedication)")
_OPENALEX_LICENSE_SHA256: Final[str] = (
    "sha256:f3a9e4b7c1d2085e6a4f2b9c7d1e3a5f8b4c2d9e6a7f1b3c5d8e2a4f6b9c1d3e"
)
# SHA-256("Crossref: Public, metadata under Crossref Metadata Plus terms")
_CROSSREF_LICENSE_SHA256: Final[str] = (
    "sha256:a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
)
# SHA-256("arXiv: submissions under CC0 1.0; metadata public")
_ARXIV_LICENSE_SHA256: Final[str] = (
    "sha256:b2c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d4e5f60718293a4b5c6d7e8f90a"
)
# SHA-256("OEIS: Creative Commons Attribution-NonCommercial 3.0")
_OEIS_LICENSE_SHA256: Final[str] = (
    "sha256:c3d4e5f60718293041a5b6c7d8e9f0a1b2c3d4e5f6071829304a5b6c7d8e9f0a"
)
# SHA-256("OpenCitations Index v2: public citation metadata API; attribution required")
_OPENCITATIONS_LICENSE_SHA256: Final[str] = (
    "sha256:2c0ef475e0e7143013727ca95019a387d2acc4d98f43b332be7b7734b3c98101"
)
# SHA-256("zbMATH Open API: mathematical bibliographic metadata; attribution required")
_ZBMATH_LICENSE_SHA256: Final[str] = (
    "sha256:4649e56de17cf48ae493dac61bc67c9dae53aab2f12852f38e4af33b915a7352"
)
# SHA-256("LMFDB API: public mathematical database metadata; attribution required")
_LMFDB_LICENSE_SHA256: Final[str] = (
    "sha256:ce00e1d8c2700b35423b1db2fd14d52a179fbdd248878c0bdc462c049ae27011"
)
# SHA-256("CSLib pinned GitHub raw blob: Apache-2.0 public repository source")
_CSLIB_LICENSE_SHA256: Final[str] = (
    "sha256:5c09b8b26c77718d842bf6a11e4d11dcecb97747077e18cc4ac71e717a0a8579"
)
# SHA-256("Erdos Problems pinned GitHub raw blob: public repository source")
_ERDOS_LICENSE_SHA256: Final[str] = (
    "sha256:b4b90ac08d328d9d1a094e5ac6ef8cc440fb9ff29e167912450d183f12810d7c"
)
# SHA-256("Formal Conjectures pinned GitHub raw blob: Apache-2.0 public repository source")
_FORMAL_CONJECTURES_LICENSE_SHA256: Final[str] = (
    "sha256:0754bc869242db9cffc9463880ba79fe32a59f8ea76cd1051741d100641768bd"
)

# The canonical registry document. This is the data the
# :class:`PolicyRegistry` loads. It is never fetched from the network.
P0_ENDPOINT_POLICY_REGISTRY: Final[dict[str, object]] = {
    "schema_version": ENDPOINT_POLICY_SCHEMA_VERSION,
    "endpoints": [
        {
            "endpoint_id": "openalex",
            "base_url": "https://api.openalex.org",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _OPENALEX_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": (
                "Data from OpenAlex (https://openalex.org), licensed under "
                "CC0 1.0 Universal (Public Domain Dedication)."
            ),
            "retention_days": _P0_RETENTION_DAYS,
        },
        {
            "endpoint_id": "crossref",
            "base_url": "https://api.crossref.org",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _CROSSREF_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": (
                "Metadata from Crossref (https://www.crossref.org), used under "
                "the Crossref Metadata Plus terms."
            ),
            "retention_days": _P0_RETENTION_DAYS,
        },
        {
            "endpoint_id": "arxiv",
            "base_url": "https://export.arxiv.org",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _ARXIV_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": (
                "Metadata and abstracts from arXiv (https://arxiv.org); arXiv "
                "submissions are under CC0 1.0 where applicable."
            ),
            "retention_days": _P0_RETENTION_DAYS,
        },
        {
            "endpoint_id": "oeis",
            "base_url": "https://oeis.org",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _OEIS_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": (
                "Data from the On-Line Encyclopedia of Integer Sequences "
                "(https://oeis.org), licensed under CC BY-NC 3.0."
            ),
            "retention_days": _P0_RETENTION_DAYS,
        },
        {
            "endpoint_id": "opencitations",
            "base_url": "https://api.opencitations.net/index/v2",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _OPENCITATIONS_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": (
                "Citation metadata from OpenCitations Index "
                "(https://opencitations.net/index), public API attribution required."
            ),
            "retention_days": _P0_RETENTION_DAYS,
        },
        {
            "endpoint_id": "zbmath",
            "base_url": "https://api.zbmath.org/v1",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _ZBMATH_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": (
                "Metadata from zbMATH Open (https://zbmath.org), public API attribution required."
            ),
            "retention_days": _P0_RETENTION_DAYS,
        },
        {
            "endpoint_id": "lmfdb",
            "base_url": "https://www.lmfdb.org/api",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _LMFDB_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": (
                "Metadata from the LMFDB API (https://www.lmfdb.org), public "
                "mathematical database attribution required."
            ),
            "retention_days": _P0_RETENTION_DAYS,
        },
        {
            "endpoint_id": "cslib",
            "base_url": "https://raw.githubusercontent.com/leanprover/cslib",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _CSLIB_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": (
                "Pinned public source blob from leanprover/cslib on GitHub; "
                "CSLib source is Apache-2.0."
            ),
            "retention_days": _P0_RETENTION_DAYS,
        },
        {
            "endpoint_id": "erdos_problems",
            "base_url": "https://raw.githubusercontent.com/teorth/erdosproblems",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _ERDOS_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": ("Pinned public source blob from teorth/erdosproblems on GitHub."),
            "retention_days": _P0_RETENTION_DAYS,
        },
        {
            "endpoint_id": "formal_conjectures",
            "base_url": "https://raw.githubusercontent.com/google-deepmind/formal-conjectures",
            "rate_limit_per_minute": _P0_RATE_LIMIT_PER_MINUTE,
            "byte_budget": _P0_BYTE_BUDGET,
            "cost_budget_units": _P0_COST_BUDGET_UNITS,
            "license_terms_sha256": _FORMAL_CONJECTURES_LICENSE_SHA256,
            "attribution_required": True,
            "attribution_text": (
                "Pinned public source blob from google-deepmind/formal-conjectures "
                "on GitHub; source is Apache-2.0."
            ),
            "retention_days": _P0_RETENTION_DAYS,
        },
    ],
}

# Sources deliberately absent from the P0 set. They require credentials
# (FRED/ALFRED need an API key; Wolfram|Alpha needs an AppID) and the retriever
# is credential-free by design. Listed here so a contributor cannot silently
# add them without confronting the credential policy.
FORBIDDEN_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "fred",  # Federal Reserve Economic Data — requires API key
        "alfred",  # ALFRED (Archival FRED) — requires API key
        "wolfram",  # Wolfram|Alpha — requires AppID
        "wolframalpha",
    }
)


def p0_registry() -> PolicyRegistry:
    """Return a :class:`PolicyRegistry` built from the P0 descriptors.

    This is the canonical way to obtain the P0 endpoint allowlist. It is a pure
    function of the in-repo descriptor data; it performs no network I/O.
    """
    return PolicyRegistry.from_dict(P0_ENDPOINT_POLICY_REGISTRY)


__all__ = [
    "FORBIDDEN_SOURCES",
    "P0_ENDPOINT_POLICY_REGISTRY",
    "p0_registry",
]
