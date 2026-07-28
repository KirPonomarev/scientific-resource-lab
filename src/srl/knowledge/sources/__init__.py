"""P0 knowledge source adapters (OpenAlex, Crossref, arXiv, OEIS)."""

from __future__ import annotations

from srl.knowledge.sources._record import SourceRecord, SourceRecordError, make_record_id
from srl.knowledge.sources.arxiv import search as search_arxiv
from srl.knowledge.sources.crossref import search as search_crossref
from srl.knowledge.sources.oeis import search as search_oeis
from srl.knowledge.sources.openalex import search as search_openalex

__all__ = [
    "SourceRecord",
    "SourceRecordError",
    "make_record_id",
    "search_arxiv",
    "search_crossref",
    "search_oeis",
    "search_openalex",
]
