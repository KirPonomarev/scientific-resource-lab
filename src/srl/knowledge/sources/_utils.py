"""Internal helpers for the P0 knowledge source adapters."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from srl.knowledge.retriever import (
    ApiRetriever,
    EndpointPolicy,
    PolicyRegistry,
    Transport,
)
from srl.knowledge.sources._record import SourceRecordError


def _utc_now() -> str:
    """Return the current UTC time as a canonical RFC 3339 ``...Z`` string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))


def sha256_digest(data: bytes) -> str:
    """Return ``sha256:<hex>`` of ``data``."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def policy_registry_from_endpoint(policy: EndpointPolicy) -> PolicyRegistry:
    """Build a single-endpoint policy registry from ``policy``."""
    return PolicyRegistry.from_dict(
        {
            "schema_version": "EndpointPolicy/v1",
            "endpoints": [asdict(policy)],
        }
    )


def fetch_with_transport(
    endpoint_id: str,
    path: str,
    params: Mapping[str, Any] | None,
    transport: Transport,
    policy: EndpointPolicy,
) -> tuple[bytes, str]:
    """Fetch ``path`` under ``policy`` using the supplied ``transport``.

    A fresh temporary cache directory is used for each call so adapters do not
    share retriever state across invocations. The directory is cleaned up after
    the fetch regardless of success or failure.

    Returns
    -------
    tuple[bytes, str]
        The response payload and the ``retrieved_utc`` timestamp from the receipt.

    Raises
    ------
    SourceRecordError
        If ``policy.endpoint_id`` does not match ``endpoint_id``.
    """
    if policy.endpoint_id != endpoint_id:
        msg = f"adapter for {endpoint_id!r} cannot use a policy for {policy.endpoint_id!r}"
        raise SourceRecordError(msg)
    registry = policy_registry_from_endpoint(policy)
    cache_dir = tempfile.mkdtemp(prefix=f"wp44-{endpoint_id}-")
    try:
        retriever = ApiRetriever(transport=transport)
        result = retriever.fetch(
            endpoint_id,
            path,
            params,
            cache_dir,
            registry,
            rate_limit_sleep=False,
        )
        return result.payload, result.receipt.retrieved_utc
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)


def _load_json(payload: bytes) -> Any:
    """Parse JSON bytes, raising :class:`SourceRecordError` on failure."""
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"payload is not valid UTF-8 JSON: {exc}"
        raise SourceRecordError(msg) from exc


def _attribution(policy: EndpointPolicy) -> str:
    """Return the attribution text for a record under ``policy``."""
    if policy.attribution_text:
        return policy.attribution_text
    return f"Data from {policy.endpoint_id}."


def _cap_limit(limit: int, cap: int = 25) -> int:
    """Return ``limit`` capped at ``cap`` for polite API use."""
    return min(limit, cap) if limit > 0 else cap


__all__ = []
