"""Deterministic trace ids for SRF receipts and status projections."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from srl.contracts.canonical import dumps


def make_trace_id(*parts: object) -> str:
    """Return a deterministic ``sha256:`` trace id for canonical JSON parts."""
    return "sha256:" + hashlib.sha256(dumps({"parts": list(parts)})).hexdigest()


@dataclass(frozen=True)
class TraceLink:
    """A disclosure-safe trace link between two public receipt identities."""

    trace_id: str
    source_id: str
    target_id: str
    relation: str

    def to_dict(self) -> dict[str, str]:
        """Return the trace link as a JSON-compatible dict."""
        return {
            "trace_id": self.trace_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
        }


__all__ = ["TraceLink", "make_trace_id"]
