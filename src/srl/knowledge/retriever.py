"""Budgeted, content-addressed API retriever with query receipts (WP-D33).

The retriever fetches bytes from an external HTTPS endpoint under a declared
:class:`EndpointPolicy` and records an immutable :class:`QueryReceipt` that
proves the retrieval happened and what came back — without ever carrying
credentials, raw query secrets, or the authority to make a scientific claim.

Honesty model
-------------
A query receipt proves *retrieval*, not *truth*. The vintage (the retrieval
date) is part of the receipt because a response's meaning can drift over time.
The response bytes are content-addressed and cached so a later agent can
re-verify that the bytes hash to the recorded ``response_sha256``; the cache
is a local content-addressed store, never an authority. A receipt's
``canonical_writes`` is always ``0`` and ``grants_authority`` is always
``false``: a retrieval never mutates canonical state and never grants the
authority to assert a scientific claim.

Defense in depth
----------------
The retriever refuses, at construction and at fetch:

- **credentials**: any constructor keyword resembling an auth header or token
  (``authorization``, ``x-api-key``, ``cookie``, and a small set of common
  auth-bearing names) raises :class:`NetworkPolicyError` before the retriever
  exists. The retriever never reads environment variables for credentials.
- **non-HTTPS schemes**: an ``http://`` URL is refused with
  :class:`NetworkPolicyError` (``NETWORK_POLICY_VIOLATION``). Only ``https``
  is egress-permitted.
- **unknown endpoints**: a fetch against an ``endpoint_id`` not in the supplied
  :class:`PolicyRegistry` is refused with ``NETWORK_POLICY_VIOLATION``. The
  registry is the allowlist.
- **budget overruns**: a response larger than the remaining byte budget is
  refused with :class:`ResourceLimitError` (``RESOURCE_LIMIT``) and **nothing
  is cached** (no partial cache).
- **rate limits**: a per-endpoint token bucket (persisted in the cache dir)
  gates requests; exceeding the rate produces a typed :class:`RateLimitedError`
  (a ``WAIT_*`` reason) rather than a silent drop or an unbounded burst.

Transport is injectable
-----------------------
The default transport is a thin wrapper over :mod:`urllib` (stdlib only — no
``requests``, no new dependency). Tests and the WP-D33 gate inject a fake
transport that returns canned bytes, so no live network ever runs in tests or
CI. The transport protocol (:class:`Transport`) takes a resolved URL and a
timeout and returns the raw response bytes plus the final (post-redirect) URL
scheme/host, so the retriever can re-assert HTTPS after a redirect.

Canonical JSON is reused from :mod:`srl.contracts.canonical` so receipts are
byte-stable and the digests are deterministic across machines.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

import certifi

from srl.contracts.canonical import dumps as canonical_dumps

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Fail-reason constants. Mirror automation/fail-reasons.json. Kept as named
# constants so the string lives in one place and tests assert against symbols.
# ---------------------------------------------------------------------------

# Egress policy violation: non-HTTPS scheme, unknown endpoint, or a
# credential-like constructor kwarg. hard_stop=true in the registry.
NETWORK_POLICY_FAIL_REASON: Final[str] = "NETWORK_POLICY_VIOLATION"

# A hard resource limit (the response byte budget) was exceeded.
# hard_stop=false in the registry; the caller may widen the budget via policy.
RESOURCE_LIMIT_FAIL_REASON: Final[str] = "RESOURCE_LIMIT"

# An operation exceeded its bounded wall-clock budget (the transport timeout).
TIMEOUT_FAIL_REASON: Final[str] = "TIMEOUT"

# The license terms could not be determined for the response.
LICENSE_UNKNOWN_FAIL_REASON: Final[str] = "LICENSE_UNKNOWN"

# A rate limit was hit; the caller should wait and re-check. Mirrors the
# ``wait`` class semantics: hard_stop=false, retriable by waiting.
RATE_LIMITED_FAIL_REASON: Final[str] = "WAIT_RESOURCE"

# ---------------------------------------------------------------------------
# Schema identity anchors.
# ---------------------------------------------------------------------------

QUERY_RECEIPT_SCHEMA_VERSION: Final[str] = "QueryReceipt/v1"
ENDPOINT_POLICY_SCHEMA_VERSION: Final[str] = "EndpointPolicy/v1"

# ---------------------------------------------------------------------------
# Transport and budget defaults.
# ---------------------------------------------------------------------------

# Default per-request wall-clock timeout for the urllib transport (seconds).
DEFAULT_TIMEOUT_SECONDS: Final[int] = 30

# Maximum retry attempts for a transient (429 / 5xx) response. The first
# attempt is not a retry, so a fetch makes at most 1 + MAX_RETRIES requests.
MAX_RETRIES: Final[int] = 2

# Base for the exponential backoff (seconds). Attempt N sleeps
# ``_BACKOFF_BASE * _BACKOFF_BASE ** (N-1)`` plus a jitter term.
_BACKOFF_BASE_SECONDS: Final[float] = 0.5

# Upper bound on the jitter added to each backoff sleep (seconds). The jitter
# decorrelates retried requests so two concurrent retriers do not synchronize.
_BACKOFF_MAX_JITTER_SECONDS: Final[float] = 0.25

# Per-second granularity for the token-bucket rate limiter. The bucket refills
# at ``rate_limit_per_minute / 60`` tokens per second; sleeps are quantized to
# this resolution so the wall clock advances measurably between requests.
_TOKEN_BUCKET_RESOLUTION_SECONDS: Final[float] = 0.05

# HTTP status codes used for the retry classifier in :func:`_fetch_with_retry`.
# 429 Too Many Requests is retried; 5xx server errors are retried. All other
# status codes are treated as hard failures.
_HTTP_STATUS_TOO_MANY_REQUESTS: Final[int] = 429
_HTTP_STATUS_SERVER_ERROR_START: Final[int] = 500
_HTTP_STATUS_SERVER_ERROR_END: Final[int] = 600

# The byte-budget headroom: a response is refused if it is strictly greater
# than the remaining budget. ``remaining`` starts at ``byte_budget`` and is
# reduced by each successful response's size. The cap is checked *before*
# caching so no partial payload is stored.

# Forbidden constructor keyword names. Any constructor keyword whose lowercase
# form equals one of these (or contains a clear auth signal) is rejected. The
# list is intentionally conservative: it covers the HTTP auth headers plus the
# most common API-key-bearing names. Matching is case-insensitive and also
# rejects a value supplied via the standard header dict form.
_FORBIDDEN_KWARGS: Final[frozenset[str]] = frozenset(
    {
        "authorization",
        "x_api_key",
        "xapikey",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "secret",
        "password",
        "passwd",
        "cookie",
        "cookies",
        "bearer",
        "bearer_token",
    }
)

# Forbidden HTTP header names (lowercased). If a ``headers`` mapping is passed
# to the constructor, any of these keys (case-insensitively) is rejected.
_FORBIDDEN_HEADERS: Final[frozenset[str]] = frozenset(
    {"authorization", "x-api-key", "cookie", "proxy-authorization"}
)


class NetworkPolicyError(ValueError):
    """Raised when a request violates the declared network egress policy.

    Covers: non-HTTPS scheme, an endpoint not in the registry allowlist, and a
    credential-like constructor kwarg or header. The typed ``fail_reason`` is
    always :data:`NETWORK_POLICY_FAIL_REASON`.

    Attributes
    ----------
    fail_reason:
        Typed fail reason (``NETWORK_POLICY_VIOLATION``).
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = NETWORK_POLICY_FAIL_REASON,
    ) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason


class ResourceLimitError(ValueError):
    """Raised when the response byte budget is exceeded.

    Nothing is cached on this failure: a response larger than the remaining
    budget is refused outright, not partially stored. The typed
    ``fail_reason`` is :data:`RESOURCE_LIMIT_FAIL_REASON`.

    Attributes
    ----------
    fail_reason:
        Typed fail reason (``RESOURCE_LIMIT``).
    endpoint_id:
        The endpoint whose budget was exceeded.
    """

    def __init__(
        self,
        message: str,
        *,
        endpoint_id: str = "",
        fail_reason: str = RESOURCE_LIMIT_FAIL_REASON,
    ) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason
        self.endpoint_id: str = endpoint_id


class RetrievalTimeoutError(ValueError):
    """Raised when the transport exceeds its bounded wall-clock budget.

    The typed ``fail_reason`` is :data:`TIMEOUT_FAIL_REASON`.

    Attributes
    ----------
    fail_reason:
        Typed fail reason (``TIMEOUT``).
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = TIMEOUT_FAIL_REASON,
    ) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason


class RateLimitedError(ValueError):
    """Raised when a per-endpoint rate limit is exceeded.

    This is a *typed wait*: the caller should wait for ``retry_after_seconds``
    and re-check, rather than silently dropping the request or bursting.
    Mirrors the ``wait`` fail-reason class. The typed ``fail_reason`` is
    :data:`RATE_LIMITED_FAIL_REASON`.

    Attributes
    ----------
    fail_reason:
        Typed fail reason (``WAIT_RESOURCE``).
    endpoint_id:
        The endpoint whose rate limit was hit.
    retry_after_seconds:
        A lower bound on how long the caller should wait before retrying.
    """

    def __init__(
        self,
        message: str,
        *,
        endpoint_id: str = "",
        retry_after_seconds: float = 0.0,
        fail_reason: str = RATE_LIMITED_FAIL_REASON,
    ) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason
        self.endpoint_id: str = endpoint_id
        self.retry_after_seconds: float = retry_after_seconds


# ---------------------------------------------------------------------------
# Endpoint policy + registry.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EndpointPolicy:
    """A declared egress policy for one HTTPS endpoint.

    The policy is the allowlist entry: a fetch is permitted only against an
    ``endpoint_id`` present in the registry, and the fetch is bounded by the
    policy's rate, byte, and cost caps. The policy is loaded from a canonical
    JSON dict (the registry), **never** from network.

    Attributes
    ----------
    endpoint_id:
        Stable identifier (e.g. ``"openalex"``). Used as the registry key and
        recorded on receipts.
    base_url:
        The HTTPS base URL for the endpoint (e.g.
        ``"https://api.openalex.org"``). Must be ``https://``.
    rate_limit_per_minute:
        Maximum requests per minute (token-bucket capacity/refill).
    byte_budget:
        Total response-byte budget for this endpoint. Responses larger than
        the remaining budget are refused with ``RESOURCE_LIMIT``.
    cost_budget_units:
        Total cost budget in abstract units (for metered endpoints).
    license_terms_sha256:
        SHA-256 (``sha256:<64 hex>``) of the endpoint's license terms. Carried
        on every receipt so license provenance is verifiable.
    attribution_required:
        Whether attribution text must be recorded with the response.
    attribution_text:
        The attribution string recorded when ``attribution_required`` is true.
    retention_days:
        How long cached responses for this endpoint may be retained.
    """

    endpoint_id: str
    base_url: str
    rate_limit_per_minute: int
    byte_budget: int
    cost_budget_units: int
    license_terms_sha256: str
    attribution_required: bool
    attribution_text: str = ""
    retention_days: int = 30


def _validate_non_empty_str(value: Any, field_name: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise ValueError."""
    if not isinstance(value, str) or not value:
        msg = f"endpoint policy {field_name!r} must be a non-empty string"
        raise ValueError(msg)
    return value


def _validate_non_negative_int(value: Any, field_name: str) -> int:
    """Return ``value`` if it is a non-negative int, else raise ValueError."""
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"endpoint policy {field_name!r} must be an int, got {type(value).__name__}"
        raise ValueError(msg)
    if value < 0:
        msg = f"endpoint policy {field_name!r} must be >= 0, got {value}"
        raise ValueError(msg)
    return value


def _validate_policy_dict(raw: Any) -> EndpointPolicy:
    """Validate a parsed policy dict and build an :class:`EndpointPolicy`.

    Parameters
    ----------
    raw:
        The parsed JSON object for one endpoint policy.

    Returns
    -------
    EndpointPolicy
        The validated, immutable policy.

    Raises
    ------
    NetworkPolicyError
        If the base URL is not HTTPS.
    ValueError
        If a field is missing, the wrong type, or out of range. A
        :class:`ValueError` (not a typed network error) because a malformed
        *policy document* is a contract bug in the caller, not an egress
        violation.
    """
    if not isinstance(raw, dict):
        msg = f"endpoint policy must be a JSON object, got {type(raw).__name__}"
        raise ValueError(msg)
    try:
        endpoint_id = raw["endpoint_id"]
        base_url = raw["base_url"]
        rate_limit_per_minute = raw["rate_limit_per_minute"]
        byte_budget = raw["byte_budget"]
        cost_budget_units = raw["cost_budget_units"]
        license_terms_sha256 = raw["license_terms_sha256"]
        attribution_required = raw["attribution_required"]
    except KeyError as exc:
        msg = f"endpoint policy missing required key: {exc.args[0]!r}"
        raise ValueError(msg) from exc
    attribution_text = raw.get("attribution_text", "")
    retention_days = raw.get("retention_days", 30)

    endpoint_id = _validate_non_empty_str(endpoint_id, "endpoint_id")
    base_url = _validate_non_empty_str(base_url, "base_url")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https":
        msg = (
            f"endpoint policy 'base_url' must be https://, got scheme {parsed.scheme!r} "
            f"for endpoint {endpoint_id!r}"
        )
        raise NetworkPolicyError(msg)
    if not parsed.netloc:
        msg = f"endpoint policy 'base_url' has no host for endpoint {endpoint_id!r}"
        raise ValueError(msg)
    rate_limit_per_minute = _validate_non_negative_int(
        rate_limit_per_minute, "rate_limit_per_minute"
    )
    byte_budget = _validate_non_negative_int(byte_budget, "byte_budget")
    cost_budget_units = _validate_non_negative_int(cost_budget_units, "cost_budget_units")
    retention_days = _validate_non_negative_int(retention_days, "retention_days")
    if not isinstance(attribution_required, bool):
        msg = "endpoint policy 'attribution_required' must be a bool"
        raise ValueError(msg)
    if not isinstance(attribution_text, str):
        msg = "endpoint policy 'attribution_text' must be a string"
        raise ValueError(msg)
    license_terms_sha256 = _validate_non_empty_str(license_terms_sha256, "license_terms_sha256")

    return EndpointPolicy(
        endpoint_id=endpoint_id,
        base_url=base_url,
        rate_limit_per_minute=rate_limit_per_minute,
        byte_budget=byte_budget,
        cost_budget_units=cost_budget_units,
        license_terms_sha256=license_terms_sha256,
        attribution_required=attribution_required,
        attribution_text=attribution_text,
        retention_days=retention_days,
    )


@dataclass(frozen=True)
class PolicyRegistry:
    """An immutable allowlist of :class:`EndpointPolicy` entries.

    The registry is the egress allowlist: a fetch is permitted only against an
    ``endpoint_id`` present in the registry. It is built from a canonical JSON
    dict (the serialized registry document), never from network.

    Attributes
    ----------
    policies:
        Mapping of endpoint_id -> :class:`EndpointPolicy`.
    """

    policies: Mapping[str, EndpointPolicy]

    def __post_init__(self) -> None:
        # Freeze a defensive copy so the registry is immutable in flight. We
        # use object.__setattr__ because the dataclass is frozen.
        object.__setattr__(self, "policies", dict(self.policies))

    @classmethod
    def from_dict(cls, doc: Any) -> PolicyRegistry:
        """Build a registry from a parsed JSON document.

        The document shape is::

            {
              "schema_version": "EndpointPolicyRegistry/v1",
              "endpoints": [
                {"endpoint_id": "openalex", "base_url": "https://...", ...},
                ...
              ]
            }

        Parameters
        ----------
        doc:
            The parsed registry document.

        Returns
        -------
        PolicyRegistry
            The validated registry.

        Raises
        ------
        ValueError
            If the document is malformed.
        NetworkPolicyError
            If any endpoint's base URL is not HTTPS.
        """
        if not isinstance(doc, dict):
            msg = f"registry must be a JSON object, got {type(doc).__name__}"
            raise ValueError(msg)
        endpoints = doc.get("endpoints")
        if not isinstance(endpoints, list) or not endpoints:
            msg = "registry must have a non-empty 'endpoints' list"
            raise ValueError(msg)
        policies: dict[str, EndpointPolicy] = {}
        for entry in endpoints:
            policy = _validate_policy_dict(entry)
            if policy.endpoint_id in policies:
                msg = f"duplicate endpoint_id in registry: {policy.endpoint_id!r}"
                raise ValueError(msg)
            policies[policy.endpoint_id] = policy
        return cls(policies=policies)

    def get(self, endpoint_id: str) -> EndpointPolicy:
        """Return the policy for ``endpoint_id`` or raise :class:`NetworkPolicyError`.

        An unknown endpoint is an egress violation: the registry is the
        allowlist, and a fetch against an unknown endpoint is refused before
        any network call.
        """
        policy = self.policies.get(endpoint_id)
        if policy is None:
            msg = (
                f"endpoint_id {endpoint_id!r} is not in the policy registry allowlist; "
                "fetch refused (NETWORK_POLICY_VIOLATION)"
            )
            raise NetworkPolicyError(msg)
        return policy

    def __contains__(self, endpoint_id: object) -> bool:
        return endpoint_id in self.policies


# ---------------------------------------------------------------------------
# Query receipt (immutable, content-addressable).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryReceipt:
    """An immutable record of one retrieval (``QueryReceipt/v1``).

    The receipt proves a retrieval happened and what came back. It deliberately
    omits the raw request URL's query string (which may carry secrets) in favor
    of digests, and never carries credentials.

    A receipt's ``canonical_writes`` is always ``0`` (a retrieval never mutates
    canonical state) and ``grants_authority`` is always ``False`` (a retrieval
    never grants the authority to assert a scientific claim). The vintage
    (``retrieved_utc``) is recorded because a response's meaning can drift.

    Attributes
    ----------
    schema_version:
        Const ``"QueryReceipt/v1"`` identity anchor.
    receipt_id:
        Stable id derived from the retrieval content (a digest of the fields
        that define the retrieval), so the same retrieval yields the same id.
    endpoint_id:
        The endpoint the retrieval targeted.
    request_url_digest:
        ``sha256:<64 hex>`` of the full request URL. The raw URL is **not**
        recorded because the query string may carry secrets; the digest lets a
        verifier confirm a URL without echoing it.
    params_digest:
        ``sha256:<64 hex>`` of the canonical encoding of the request params.
    response_sha256:
        ``sha256:<64 hex>`` of the response payload bytes.
    bytes:
        The response payload size in bytes.
    cached:
        ``True`` iff the response was served from the local content-addressed
        cache (no network fetch was made for the payload).
    retrieved_utc:
        Canonical RFC 3339 UTC timestamp (seconds precision, trailing ``Z``).
        The *vintage* of the retrieval.
    license_terms_sha256:
        The license-terms digest recorded for the endpoint.
    vintage:
        The retrieval date (``YYYY-MM-DD``), echoed for convenience.
    canonical_writes:
        Always ``0`` (safety const).
    grants_authority:
        Always ``False`` (safety const).
    attribution:
        The attribution string recorded for the endpoint (may be empty).
    """

    schema_version: str
    receipt_id: str
    endpoint_id: str
    request_url_digest: str
    params_digest: str
    response_sha256: str
    bytes: int
    cached: bool
    retrieved_utc: str
    license_terms_sha256: str
    vintage: str
    canonical_writes: int
    grants_authority: bool
    attribution: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the receipt as a plain dict for canonical encoding."""
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "endpoint_id": self.endpoint_id,
            "request_url_digest": self.request_url_digest,
            "params_digest": self.params_digest,
            "response_sha256": self.response_sha256,
            "bytes": self.bytes,
            "cached": self.cached,
            "retrieved_utc": self.retrieved_utc,
            "license_terms_sha256": self.license_terms_sha256,
            "vintage": self.vintage,
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
            "attribution": self.attribution,
        }


# ---------------------------------------------------------------------------
# Transport protocol + default urllib transport.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportResponse:
    """The raw response from a transport call.

    Attributes
    ----------
    payload:
        The raw response bytes.
    final_scheme:
        The URL scheme after any redirect (so the retriever can re-assert
        HTTPS). ``"https"`` for a clean HTTPS response.
    final_host:
        The URL host after any redirect.
    status:
        The HTTP status code.
    """

    payload: bytes
    final_scheme: str
    final_host: str
    status: int


class Transport(Protocol):
    """The transport contract: fetch ``url`` and return the raw bytes.

    A transport implementation performs the actual network I/O (or, in tests,
    returns canned bytes). It must report the final (post-redirect) scheme and
    host so the retriever can re-assert HTTPS after a redirect. It should raise
    a :class:`RetrievalTimeoutError` when the per-request wall-clock budget is
    exceeded.
    """

    def fetch(self, url: str, *, timeout_seconds: int) -> TransportResponse:  # pragma: no cover
        """Fetch ``url`` and return the raw response bytes.

        Parameters
        ----------
        url:
            The fully-resolved HTTPS URL to fetch.
        timeout_seconds:
            The per-request wall-clock budget.

        Returns
        -------
        TransportResponse
            The raw response bytes and the final (post-redirect) scheme/host.

        Raises
        ------
        RetrievalTimeoutError
            If the request exceeds its wall-clock budget.
        urllib.error.HTTPError
            For non-2xx HTTP responses (the retriever inspects the status to
            decide retry vs. fail).
        """
        ...


class UrllibTransport:
    """The default transport: a thin wrapper over :mod:`urllib` (stdlib).

    No ``requests``, no new dependency. Uses a fresh :class:`urllib.request.OpenerDirector`
    per fetch so no cookies or auth state are carried between requests. The
    opener is injectable at construction so callers (and tests) can supply a
    configured opener; by default a plain :class:`urllib.request.build_opener`
    is used with no proxy handlers that read the environment beyond the system
    default.

    The transport never adds auth headers. If a caller needs UA-based
    courtesy (some APIs require a User-Agent), a static UA may be supplied at
    construction; it is a courtesy string, never a credential.
    """

    def __init__(
        self,
        *,
        opener: urllib.request.OpenerDirector | None = None,
        user_agent: str = "srl-knowledge-retriever/1.0 (https-only)",
    ) -> None:
        self._opener = opener
        self._user_agent = user_agent

    def fetch(self, url: str, *, timeout_seconds: int) -> TransportResponse:
        """Fetch ``url`` via :mod:`urllib` and return the raw bytes.

        Raises :class:`RetrievalTimeoutError` (typed ``TIMEOUT``) if the
        request exceeds its wall-clock budget, and re-raises
        :class:`urllib.error.HTTPError` for non-2xx responses so the retriever
        can classify retry vs. fail.
        """
        opener = self._opener or urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_verified_ssl_context())
        )
        req = urllib.request.Request(  # noqa: S310 - https verified above
            url, headers={"User-Agent": self._user_agent}
        )
        try:
            with opener.open(req, timeout=timeout_seconds) as resp:
                payload = resp.read()
                final_url = resp.geturl()
                status = getattr(resp, "status", 200) or 200
        except urllib.error.HTTPError:
            # Re-raise HTTPError so the retriever can inspect the status code
            # (429/5xx are retried; everything else is a hard fail).
            raise
        except TimeoutError as exc:
            msg = f"transport timed out after {timeout_seconds}s fetching {url}"
            raise RetrievalTimeoutError(msg) from exc
        except OSError as exc:
            # urllib raises URLError (a subclass of OSError) for connection
            # failures. A timeout is surfaced as URLError whose reason is
            # socket.timeout; treat both as a typed TIMEOUT when the reason
            # indicates a timeout, else re-raise.
            reason = getattr(exc, "reason", None)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                msg = f"transport timed out after {timeout_seconds}s fetching {url}"
                raise RetrievalTimeoutError(msg) from exc
            raise
        parsed = urllib.parse.urlsplit(final_url)
        return TransportResponse(
            payload=payload,
            final_scheme=parsed.scheme,
            final_host=parsed.netloc,
            status=int(status),
        )


# ---------------------------------------------------------------------------
# Fetch result bundle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    """The bundle returned by :meth:`ApiRetriever.fetch`.

    Attributes
    ----------
    receipt:
        The immutable :class:`QueryReceipt`.
    payload:
        The response payload bytes (cached or freshly fetched).
    """

    receipt: QueryReceipt
    payload: bytes


# ---------------------------------------------------------------------------
# Internal: persistent token-bucket rate limiter.
# ---------------------------------------------------------------------------


@dataclass
class _BucketState:
    """Mutable token-bucket state for one endpoint.

    Attributes
    ----------
    tokens:
        Current token count (float for fractional refill).
    last_refill_utc_seconds:
        Wall-clock time (seconds since epoch) of the last refill.
    """

    tokens: float
    last_refill_utc_seconds: float


def _rate_state_path(cache_dir: Path, endpoint_id: str) -> Path:
    """Return the persistent rate-limiter state path for ``endpoint_id``."""
    # Content-address the endpoint_id into a filename so the state file name is
    # stable and free of path-separator surprises.
    digest = hashlib.sha256(endpoint_id.encode("utf-8")).hexdigest()[:32]
    return cache_dir / f"ratelimit-{endpoint_id}-{digest}.json"


def _load_bucket_state(path: Path, capacity: int) -> _BucketState:
    """Load the persisted bucket state, or initialize a full bucket."""
    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(doc, dict)
                and isinstance(doc.get("tokens"), int | float)
                and isinstance(doc.get("last_refill_utc_seconds"), int | float)
            ):
                return _BucketState(
                    tokens=float(doc["tokens"]),
                    last_refill_utc_seconds=float(doc["last_refill_utc_seconds"]),
                )
        except (OSError, json.JSONDecodeError):
            pass  # Corrupt state file: start fresh with a full bucket.
    return _BucketState(tokens=float(capacity), last_refill_utc_seconds=time.time())


def _save_bucket_state(path: Path, state: _BucketState) -> None:
    """Persist the bucket state atomically (write-temp + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"tokens": state.tokens, "last_refill_utc_seconds": state.last_refill_utc_seconds}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _acquire_token(
    cache_dir: Path,
    policy: EndpointPolicy,
    *,
    now_seconds: float | None = None,
    sleep: bool = True,
) -> None:
    """Acquire one request token for ``policy``'s endpoint.

    Implements a persistent token bucket: the bucket holds at most
    ``rate_limit_per_minute`` tokens and refills at
    ``rate_limit_per_minute / 60`` tokens per second. Acquiring a token
    consumes one. If the bucket is empty, the call either sleeps until a token
    is available (when ``sleep=True``) or raises :class:`RateLimitedError`
    (when ``sleep=False``, used by the gate to assert the typed wait).

    Parameters
    ----------
    cache_dir:
        Directory holding the persistent rate-limiter state file.
    policy:
        The endpoint policy (provides ``endpoint_id`` and
        ``rate_limit_per_minute``).
    now_seconds:
        Override for the current wall-clock time (seconds since epoch), for
        deterministic tests.
    sleep:
        If ``True`` (default), block until a token is available. If ``False``,
        raise :class:`RateLimitedError` when the bucket is empty.

    Raises
    ------
    RateLimitedError
        If the bucket is empty and ``sleep`` is ``False``.
    """
    capacity = policy.rate_limit_per_minute
    if capacity <= 0:
        # A zero/negative rate means "no requests permitted". This is a typed
        # wait: the endpoint is configured to refuse all requests for now.
        raise RateLimitedError(
            f"endpoint {policy.endpoint_id!r} has rate_limit_per_minute=0; no requests permitted",
            endpoint_id=policy.endpoint_id,
            retry_after_seconds=60.0,
        )
    refill_per_second = capacity / 60.0
    state_path = _rate_state_path(cache_dir, policy.endpoint_id)
    now = now_seconds if now_seconds is not None else time.time()

    while True:
        state = _load_bucket_state(state_path, capacity)
        elapsed = max(0.0, now - state.last_refill_utc_seconds)
        state.tokens = min(float(capacity), state.tokens + elapsed * refill_per_second)
        state.last_refill_utc_seconds = now
        if state.tokens >= 1.0:
            state.tokens -= 1.0
            _save_bucket_state(state_path, state)
            return
        # Not enough tokens. Compute the wait until one token refills.
        needed = 1.0 - state.tokens
        wait_seconds = needed / refill_per_second if refill_per_second > 0 else 60.0
        # Persist the deficit so concurrent callers see the same drained state.
        _save_bucket_state(state_path, state)
        if not sleep:
            raise RateLimitedError(
                f"endpoint {policy.endpoint_id!r} rate limit ({capacity}/min) exceeded; "
                f"retry after ~{wait_seconds:.2f}s",
                endpoint_id=policy.endpoint_id,
                retry_after_seconds=wait_seconds,
            )
        # Sleep at the bucket resolution so the wall clock advances measurably.
        time.sleep(max(_TOKEN_BUCKET_RESOLUTION_SECONDS, wait_seconds))
        now = time.time()


# ---------------------------------------------------------------------------
# Internal: budget accounting (persistent).
# ---------------------------------------------------------------------------


@dataclass
class _BudgetState:
    """Mutable budget state for one endpoint.

    Attributes
    ----------
    bytes_remaining:
        Response bytes remaining in the endpoint's byte_budget.
    cost_units_remaining:
        Cost units remaining in the endpoint's cost_budget_units.
    """

    bytes_remaining: int
    cost_units_remaining: int


def _budget_state_path(cache_dir: Path, endpoint_id: str) -> Path:
    """Return the persistent budget-state path for ``endpoint_id``."""
    digest = hashlib.sha256(endpoint_id.encode("utf-8")).hexdigest()[:32]
    return cache_dir / f"budget-{endpoint_id}-{digest}.json"


def _load_budget_state(path: Path, policy: EndpointPolicy) -> _BudgetState:
    """Load the persisted budget state, or initialize from the policy."""
    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(doc, dict)
                and isinstance(doc.get("bytes_remaining"), int)
                and isinstance(doc.get("cost_units_remaining"), int)
            ):
                return _BudgetState(
                    bytes_remaining=int(doc["bytes_remaining"]),
                    cost_units_remaining=int(doc["cost_units_remaining"]),
                )
        except (OSError, json.JSONDecodeError):
            pass  # Corrupt state file: start fresh from the policy.
    return _BudgetState(
        bytes_remaining=policy.byte_budget,
        cost_units_remaining=policy.cost_budget_units,
    )


def _save_budget_state(path: Path, state: _BudgetState) -> None:
    """Persist the budget state atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "bytes_remaining": state.bytes_remaining,
        "cost_units_remaining": state.cost_units_remaining,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Internal: content-addressed payload store.
# ---------------------------------------------------------------------------


def _payload_store_dir(cache_dir: Path) -> Path:
    """Return the content-addressed payload store directory."""
    return cache_dir / "payloads"


def _cache_key(endpoint_id: str, url: str, params: Mapping[str, Any]) -> str:
    """Return the content-addressed cache key for a request.

    The key is the SHA-256 of the canonical encoding of
    ``{"endpoint_id": ..., "url": ..., "params": canonical(params)}``. Two
    requests with the same endpoint, URL, and params yield the same key, so a
    cache hit returns the identical payload.
    """
    canon_params = canonical_dumps(dict(params))
    key_obj = {"endpoint_id": endpoint_id, "url": url, "params": canon_params.decode("utf-8")}
    blob = canonical_dumps(key_obj)
    return hashlib.sha256(blob).hexdigest()


def _payload_path(store_dir: Path, key: str) -> Path:
    """Return the payload path for ``key`` (sharded by first 2 hex chars)."""
    shard = store_dir / key[:2]
    return shard / f"{key}.bin"


def _meta_path(store_dir: Path, key: str) -> Path:
    """Return the retrieval-metadata path for ``key``."""
    shard = store_dir / key[:2]
    return shard / f"{key}.meta.json"


def _write_payload(store_dir: Path, key: str, payload: bytes, meta: dict[str, Any]) -> None:
    """Write ``payload`` and ``meta`` to the content-addressed store atomically.

    Writes a temp file then renames, so a reader never sees a partial payload.
    """
    payload_path = _payload_path(store_dir, key)
    meta_path = _meta_path(store_dir, key)
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    # Payload: write temp then replace.
    ptmp = payload_path.with_suffix(".bin.tmp")
    ptmp.write_bytes(payload)
    os.replace(ptmp, payload_path)
    # Metadata: write temp then replace.
    mtmp = meta_path.with_suffix(".json.tmp")
    mtmp.write_text(json.dumps(meta, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(mtmp, meta_path)


def _read_payload(store_dir: Path, key: str) -> tuple[bytes, dict[str, Any]] | None:
    """Read the payload and metadata for ``key``, or ``None`` if absent.

    Verifies the payload hash on read so a corrupted/tampered file is detected
    rather than silently served.
    """
    payload_path = _payload_path(store_dir, key)
    meta_path = _meta_path(store_dir, key)
    if not payload_path.exists() or not meta_path.exists():
        return None
    try:
        payload = payload_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    # Integrity check: the stored response_sha256 must match the payload.
    expected = meta.get("response_sha256")
    if not isinstance(expected, str):
        return None
    actual = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual != expected:
        return None
    return payload, meta


# ---------------------------------------------------------------------------
# Internal: URL + digest helpers.
# ---------------------------------------------------------------------------


def _digest(value: bytes | str) -> str:
    """Return ``sha256:<64 hex>`` of ``value``."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _build_url(base_url: str, path: str, params: Mapping[str, Any]) -> str:
    """Build the full request URL from ``base_url``, ``path``, and ``params``.

    ``path`` is joined onto ``base_url``. ``params`` are URL-encoded into the
    query string. Param values are stringified (bools as ``true``/``false``,
    ints/floats as ``str()``); nested values are rejected.
    """
    base = base_url.rstrip("/")
    if path and not path.startswith("/"):
        path = "/" + path
    url = base + path
    if params:
        string_params: list[tuple[str, str]] = []
        for k, v in params.items():
            if isinstance(v, bool):
                string_params.append((k, "true" if v else "false"))
            elif isinstance(v, str | int | float):
                string_params.append((k, str(v)))
            elif v is None:
                continue
            else:
                msg = (
                    f"param {k!r} has unsupported type {type(v).__name__}; only "
                    "str/int/float/bool/None are permitted"
                )
                raise ValueError(msg)
        if string_params:
            url = url + "?" + urllib.parse.urlencode(string_params)
    return url


def _assert_https(url: str, *, context: str) -> None:
    """Raise :class:`NetworkPolicyError` if ``url`` is not HTTPS.

    Parameters
    ----------
    url:
        The URL to check.
    context:
        A short context string for the error message (e.g. ``"request"``).
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        msg = (
            f"network policy requires https:// for {context}, got scheme {parsed.scheme!r} "
            f"(url host: {parsed.netloc!r}); fetch refused (NETWORK_POLICY_VIOLATION)"
        )
        raise NetworkPolicyError(msg)


def _utc_now_seconds() -> str:
    """Return the current UTC time as a canonical RFC 3339 ``...Z`` string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))


def _utc_now_iso(now_seconds: float | None = None) -> str:
    """Return a canonical RFC 3339 UTC timestamp, optionally for ``now_seconds``."""
    t = now_seconds if now_seconds is not None else time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _canonical_params(params: Mapping[str, Any]) -> bytes:
    """Return the canonical encoding of ``params`` for digesting.

    Booleans, ints, floats, and strings are admitted (stringified for stable
    encoding); nested values are rejected so the digest is deterministic.
    """
    clean: dict[str, str] = {}
    for k, v in sorted(params.items()):
        if isinstance(v, bool):
            clean[k] = "true" if v else "false"
        elif isinstance(v, str | int | float):
            clean[k] = str(v)
        elif v is None:
            clean[k] = ""
        else:
            msg = (
                f"param {k!r} has unsupported type {type(v).__name__}; only "
                "str/int/float/bool/None are permitted"
            )
            raise ValueError(msg)
    return canonical_dumps(clean)


# ---------------------------------------------------------------------------
# The retriever.
# ---------------------------------------------------------------------------


@dataclass
class ApiRetriever:
    """A budgeted, content-addressed API retriever (WP-D33).

    The retriever fetches bytes from an HTTPS endpoint declared in a
    :class:`PolicyRegistry` and records an immutable :class:`QueryReceipt`.
    It carries no credentials, reads no environment variables for auth, and
    caches responses in a local content-addressed store keyed by the request
    identity.

    The transport is injectable so tests and the WP-D33 gate can supply a fake
    transport (canned bytes) and never touch the network.

    Parameters
    ----------
    transport:
        The :class:`Transport` to use. Defaults to :class:`UrllibTransport`.
        May be ``None`` to use the default.
    timeout_seconds:
        Per-request wall-clock budget for the transport. Defaults to 30s.
    default_user_agent:
        Courtesy User-Agent for the default urllib transport. Never a
        credential.

    Raises
    ------
    NetworkPolicyError
        If any constructor keyword or supplied ``headers`` mapping resembles
        an auth header or credential. The retriever must never carry
        credentials.

    Notes
    -----
    The retriever is a ``@dataclass`` (not frozen) so the transport can be
    swapped in tests, but its configuration is effectively immutable after
    construction. It performs no network I/O at construction; a fetch happens
    only when :meth:`fetch` is called.
    """

    transport: Transport | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    default_user_agent: str = "srl-knowledge-retriever/1.0 (https-only)"
    # Internal: not part of the public constructor surface, but dataclass
    # requires a default for every field when subclassing like this. Kept as a
    # private field so callers do not set it.
    _headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # The default transport is a plain urllib wrapper.
        if self.transport is None:
            self.transport = UrllibTransport(user_agent=self.default_user_agent)
        # Validate any supplied headers: no auth-bearing names.
        if self._headers:
            lowered = {k.lower() for k in self._headers}
            forbidden = lowered & _FORBIDDEN_HEADERS
            if forbidden:
                msg = (
                    f"refusing to construct retriever with forbidden header(s) "
                    f"{sorted(forbidden)!r}; the retriever never carries credentials "
                    "(NETWORK_POLICY_VIOLATION)"
                )
                raise NetworkPolicyError(msg)

    # -----------------------------------------------------------------
    # Public API.
    # -----------------------------------------------------------------

    def fetch(  # noqa: PLR0913 - fetch orchestrates policy, cache, budget, retry
        self,
        endpoint_id: str,
        path: str,
        params: Mapping[str, Any] | None,
        cache_dir: str | Path,
        policy_registry: PolicyRegistry,
        *,
        transport: Transport | None = None,
        timeout_seconds: int | None = None,
        now_seconds: float | None = None,
        rate_limit_sleep: bool = True,
    ) -> FetchResult:
        """Fetch bytes from ``endpoint_id`` under the registry's policy.

        Enforces, in order: endpoint allowlist, HTTPS, rate limit, cache hit,
        byte budget, cost budget, retry-on-429/5xx, and records an immutable
        :class:`QueryReceipt`.

        Parameters
        ----------
        endpoint_id:
            The endpoint to fetch (must be in ``policy_registry``).
        path:
            The path component (joined onto the endpoint's ``base_url``).
        params:
            Query params (URL-encoded). ``None`` means no params.
        cache_dir:
            Directory for the content-addressed payload store and the
            persistent rate/budget state files.
        policy_registry:
            The :class:`PolicyRegistry` allowlist.
        transport:
            Optional override transport (else the retriever's default).
        timeout_seconds:
            Optional per-request timeout override.
        now_seconds:
            Override for the current wall-clock time (deterministic tests).
        rate_limit_sleep:
            If ``False``, raise :class:`RateLimitedError` instead of sleeping
            when the rate limit is exceeded (used by the gate).

        Returns
        -------
        FetchResult
            The immutable receipt and the payload bytes.

        Raises
        ------
        NetworkPolicyError
            Unknown endpoint or non-HTTPS URL.
        RateLimitedError
            Rate limit exceeded and ``rate_limit_sleep`` is ``False``.
        ResourceLimitError
            Response larger than the remaining byte budget (nothing cached).
        RetrievalTimeoutError
            Transport exceeded its wall-clock budget.
        """
        # Resolve the effective transport and timeout.
        active_transport = transport if transport is not None else self.transport
        assert active_transport is not None  # noqa: S101 - invariant after __post_init__
        effective_timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds

        # 1. Endpoint allowlist: unknown endpoint -> NETWORK_POLICY_VIOLATION.
        policy = policy_registry.get(endpoint_id)

        # 2. Build the URL and assert HTTPS.
        resolved_params: Mapping[str, Any] = params or {}
        url = _build_url(policy.base_url, path, resolved_params)
        _assert_https(url, context=f"endpoint {endpoint_id!r} request")

        # Cache directory setup.
        cache = Path(cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        store_dir = _payload_store_dir(cache)
        store_dir.mkdir(parents=True, exist_ok=True)

        # 3. Cache hit: return the stored payload with cached=True.
        key = _cache_key(endpoint_id, url, resolved_params)
        cached = _read_payload(store_dir, key)
        if cached is not None:
            payload, meta = cached
            receipt = self._build_receipt(
                policy=policy,
                url=url,
                params=resolved_params,
                payload=payload,
                cached=True,
                now_seconds=now_seconds,
            )
            return FetchResult(receipt=receipt, payload=payload)

        # 4. Rate limit (token bucket). Sleeping is the default; the gate
        #    passes rate_limit_sleep=False to assert the typed wait.
        _acquire_token(cache, policy, now_seconds=now_seconds, sleep=rate_limit_sleep)

        # 5. Fetch with retry on transient (429/5xx). Budget accounting happens
        #    per attempt: a response that exceeds the budget is refused and
        #    nothing is cached.
        response = self._fetch_with_retry(
            active_transport,
            url=url,
            timeout_seconds=effective_timeout,
            policy=policy,
        )
        payload = response.payload

        # 6. Byte budget: response larger than remaining -> RESOURCE_LIMIT,
        #    nothing cached.
        budget_path = _budget_state_path(cache, policy.endpoint_id)
        budget = _load_budget_state(budget_path, policy)
        if len(payload) > budget.bytes_remaining:
            msg = (
                f"response for endpoint {policy.endpoint_id!r} is {len(payload)} bytes, "
                f"exceeding the remaining byte budget of {budget.bytes_remaining} bytes; "
                "fetch refused and nothing was cached (RESOURCE_LIMIT)"
            )
            raise ResourceLimitError(msg, endpoint_id=policy.endpoint_id)

        # 7. Cost budget: subtract the configured per-request cost (1 unit by
        #    default). A exhausted cost budget is a typed RESOURCE_LIMIT too.
        if budget.cost_units_remaining < 1:
            msg = (
                f"endpoint {policy.endpoint_id!r} cost budget exhausted "
                f"(0 of {policy.cost_budget_units} units remaining); fetch refused "
                "(RESOURCE_LIMIT)"
            )
            raise ResourceLimitError(msg, endpoint_id=policy.endpoint_id)

        # Commit the budget deduction.
        budget.bytes_remaining -= len(payload)
        budget.cost_units_remaining -= 1
        _save_budget_state(budget_path, budget)

        # 8. Write the payload to the content-addressed store with metadata.
        response_sha = _digest(payload)
        meta = {
            "endpoint_id": policy.endpoint_id,
            "cache_key": key,
            "response_sha256": response_sha,
            "bytes": len(payload),
            "license_terms_sha256": policy.license_terms_sha256,
            "retention_days": policy.retention_days,
        }
        _write_payload(store_dir, key, payload, meta)

        # 9. Build the immutable receipt.
        receipt = self._build_receipt(
            policy=policy,
            url=url,
            params=resolved_params,
            payload=payload,
            cached=False,
            now_seconds=now_seconds,
        )
        return FetchResult(receipt=receipt, payload=payload)

    # -----------------------------------------------------------------
    # Internal helpers.
    # -----------------------------------------------------------------

    def _fetch_with_retry(  # noqa: C901 - retry classifier is naturally branchy
        self,
        transport: Transport,
        *,
        url: str,
        timeout_seconds: int,
        policy: EndpointPolicy,
    ) -> TransportResponse:
        """Fetch ``url`` with bounded retry on 429/5xx.

        Makes at most ``1 + MAX_RETRIES`` attempts. Each transient failure
        sleeps an exponential backoff with jitter before retrying. A timeout
        or a non-transient HTTP error is surfaced immediately as a typed
        error.
        """
        last_exc: Exception | None = None
        for attempt in range(1 + MAX_RETRIES):
            try:
                response = transport.fetch(url, timeout_seconds=timeout_seconds)
            except RetrievalTimeoutError:
                raise
            except urllib.error.HTTPError as exc:
                last_exc = exc
                status = exc.code
                if status == _HTTP_STATUS_TOO_MANY_REQUESTS or (
                    _HTTP_STATUS_SERVER_ERROR_START <= status < _HTTP_STATUS_SERVER_ERROR_END
                ):
                    # Transient: retry if attempts remain.
                    if attempt < MAX_RETRIES:
                        self._backoff_sleep(attempt)
                        continue
                # Non-transient, or retries exhausted: surface as a typed error.
                msg = (
                    f"endpoint {policy.endpoint_id!r} returned HTTP {status} "
                    f"(after {attempt + 1} attempt(s)); fetch refused"
                )
                if status == _HTTP_STATUS_TOO_MANY_REQUESTS:
                    raise RateLimitedError(
                        msg, endpoint_id=policy.endpoint_id, retry_after_seconds=60.0
                    ) from exc
                raise NetworkPolicyError(msg) from exc
            except OSError as exc:
                # Connection-level failure: treat as transient for retry, then
                # surface as a typed error.
                last_exc = exc
                if attempt < MAX_RETRIES:
                    self._backoff_sleep(attempt)
                    continue
                msg = (
                    f"endpoint {policy.endpoint_id!r} transport error: {exc}; "
                    f"fetch refused after {attempt + 1} attempt(s)"
                )
                raise NetworkPolicyError(msg) from exc
            else:
                # Re-assert HTTPS after the transport's final URL (post-redirect).
                if response.final_scheme != "https":
                    msg = (
                        f"endpoint {policy.endpoint_id!r} redirected to non-https scheme "
                        f"{response.final_scheme!r} (host {response.final_host!r}); "
                        "fetch refused (NETWORK_POLICY_VIOLATION)"
                    )
                    raise NetworkPolicyError(msg)
                return response
        # Unreachable: the loop either returns or raises. Kept for type safety.
        msg = f"endpoint {policy.endpoint_id!r} exhausted retries without a response"
        raise NetworkPolicyError(msg) from last_exc

    def _backoff_sleep(self, attempt: int) -> None:
        """Sleep an exponential backoff with jitter before retry ``attempt``.

        ``attempt`` is 0-indexed (0 = first retry). The base sleep is
        ``_BACKOFF_BASE_SECONDS * (2 ** attempt)`` plus up to
        ``_BACKOFF_MAX_JITTER_SECONDS`` of random jitter. The jitter is drawn
        from a local :class:`random.Random` so it does not perturb the global
        RNG state used by other code.
        """
        base = _BACKOFF_BASE_SECONDS * (2**attempt)
        jitter = _LOCAL_RANDOM.uniform(0.0, _BACKOFF_MAX_JITTER_SECONDS)
        time.sleep(base + jitter)

    def _build_receipt(  # noqa: PLR0913 - receipt is a saturated record of retrieval state
        self,
        *,
        policy: EndpointPolicy,
        url: str,
        params: Mapping[str, Any],
        payload: bytes,
        cached: bool,
        now_seconds: float | None,
    ) -> QueryReceipt:
        """Assemble the immutable :class:`QueryReceipt` for a retrieval.

        The receipt digests the full URL (never the raw query string, which may
        carry secrets) and the canonical params, and records the payload's
        content hash. The receipt id is a digest of the retrieval-defining
        fields so the same retrieval yields the same id.
        """
        retrieved_utc = _utc_now_iso(now_seconds)
        vintage = retrieved_utc[:10]  # YYYY-MM-DD
        response_sha = _digest(payload)
        url_digest = _digest(url)
        params_blob = _canonical_params(params)
        params_digest = _digest(params_blob)
        attribution = policy.attribution_text if policy.attribution_required else ""

        # Receipt id: a digest of the fields that define the retrieval. Omit
        # the retrieved_utc so a cache hit and a fresh fetch of the same
        # request yield the same receipt id (the cached flag distinguishes
        # them). This makes the receipt id a stable retrieval identity.
        id_obj = {
            "endpoint_id": policy.endpoint_id,
            "request_url_digest": url_digest,
            "params_digest": params_digest,
            "response_sha256": response_sha,
        }
        receipt_id = _digest(canonical_dumps(id_obj))

        return QueryReceipt(
            schema_version=QUERY_RECEIPT_SCHEMA_VERSION,
            receipt_id=receipt_id,
            endpoint_id=policy.endpoint_id,
            request_url_digest=url_digest,
            params_digest=params_digest,
            response_sha256=response_sha,
            bytes=len(payload),
            cached=cached,
            retrieved_utc=retrieved_utc,
            license_terms_sha256=policy.license_terms_sha256,
            vintage=vintage,
            canonical_writes=0,
            grants_authority=False,
            attribution=attribution,
        )


# A module-local RNG so the backoff jitter does not perturb the global random
# state. Seeded once at import; the jitter only needs to decorrelate retriers.
# The seed is a fixed constant so the jitter sequence is reproducible.
_LOCAL_RANDOM_SEED: Final[int] = 0x5EED
_LOCAL_RANDOM: Final[random.Random] = random.Random(  # noqa: S311 - deterministic jitter, not crypto
    _LOCAL_RANDOM_SEED
)


def _verified_ssl_context() -> ssl.SSLContext:
    """Return a verified TLS context using the pinned runtime CA bundle."""
    return ssl.create_default_context(cafile=certifi.where())


def construct_retriever(**kwargs: Any) -> ApiRetriever:
    """Construct an :class:`ApiRetriever`, rejecting credential-like kwargs.

    This is the safe constructor entry point. It inspects ``kwargs`` for any
    key whose lowercase form is in :data:`_FORBIDDEN_KWARGS` (or a ``headers``
    mapping carrying a forbidden header) and raises :class:`NetworkPolicyError`
    before the retriever is built. Use this in place of the bare
    ``ApiRetriever(...)`` constructor when accepting retriever configuration
    from untrusted input.

    Parameters
    ----------
    **kwargs:
        Constructor keyword arguments forwarded to :class:`ApiRetriever`.

    Returns
    -------
    ApiRetriever
        The constructed retriever.

    Raises
    ------
    NetworkPolicyError
        If any keyword resembles a credential (auth header/token/cookie), or a
        ``headers`` mapping carries a forbidden header name.
    """
    for key in kwargs:
        lowered = key.lower()
        # Direct forbidden kwarg name.
        if lowered in _FORBIDDEN_KWARGS:
            msg = (
                f"refusing to construct retriever with credential-like keyword "
                f"{key!r}; the retriever never carries credentials "
                "(NETWORK_POLICY_VIOLATION)"
            )
            raise NetworkPolicyError(msg)
        # A keyword that looks like an auth header (e.g. contains 'auth',
        # 'token', 'secret', 'password', 'apikey').
        if any(
            sig in lowered
            for sig in (
                "auth",
                "token",
                "secret",
                "password",
                "apikey",
                "credential",
            )
        ):
            msg = (
                f"refusing to construct retriever with credential-like keyword "
                f"{key!r}; the retriever never carries credentials "
                "(NETWORK_POLICY_VIOLATION)"
            )
            raise NetworkPolicyError(msg)
    # A headers mapping: inspect its keys.
    headers = kwargs.get("headers")
    if isinstance(headers, Mapping):
        header_keys_lower = {k.lower() for k in headers}
        forbidden = header_keys_lower & _FORBIDDEN_HEADERS
        if forbidden:
            msg = (
                f"refusing to construct retriever with forbidden header(s) "
                f"{sorted(forbidden)!r}; the retriever never carries credentials "
                "(NETWORK_POLICY_VIOLATION)"
            )
            raise NetworkPolicyError(msg)
    return ApiRetriever(**kwargs)


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ENDPOINT_POLICY_SCHEMA_VERSION",
    "LICENSE_UNKNOWN_FAIL_REASON",
    "MAX_RETRIES",
    "NETWORK_POLICY_FAIL_REASON",
    "QUERY_RECEIPT_SCHEMA_VERSION",
    "RATE_LIMITED_FAIL_REASON",
    "RESOURCE_LIMIT_FAIL_REASON",
    "TIMEOUT_FAIL_REASON",
    "ApiRetriever",
    "EndpointPolicy",
    "FetchResult",
    "NetworkPolicyError",
    "PolicyRegistry",
    "QueryReceipt",
    "RateLimitedError",
    "ResourceLimitError",
    "RetrievalTimeoutError",
    "Transport",
    "TransportResponse",
    "UrllibTransport",
    "construct_retriever",
]
