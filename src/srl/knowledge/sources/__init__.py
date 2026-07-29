"""A11 knowledge source adapters."""

from __future__ import annotations

from srl.knowledge.sources._record import SourceRecord, SourceRecordError, make_record_id
from srl.knowledge.sources.arxiv import search as search_arxiv
from srl.knowledge.sources.crossref import search as search_crossref
from srl.knowledge.sources.github_corpus import search as search_github_corpus
from srl.knowledge.sources.lmfdb import search as search_lmfdb
from srl.knowledge.sources.oeis import search as search_oeis
from srl.knowledge.sources.openalex import search as search_openalex
from srl.knowledge.sources.opencitations import search as search_opencitations
from srl.knowledge.sources.zbmath import search as search_zbmath

__all__ = [
    "SourceRecord",
    "SourceRecordError",
    "make_record_id",
    "search_arxiv",
    "search_crossref",
    "search_github_corpus",
    "search_lmfdb",
    "search_oeis",
    "search_openalex",
    "search_opencitations",
    "search_zbmath",
]
