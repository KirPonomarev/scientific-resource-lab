"""ArtifactRef/v1 validation: a portable, content-addressed reference.

An :code:`ArtifactRef/v1` is the standard way one SRL artifact points at
another. It carries enough to fetch and verify the referenced bytes without
trusting the path:

- ``schema_version``: the const ``"ArtifactRef/v1"`` identity anchor.
- ``media_type``: an IANA-style media type string (e.g.
  ``"application/json"``), non-empty.
- ``digest``: a content digest ``"sha256:<64 lowercase hex>"``. The lowercase
  hex rule keeps digests byte-stable (uppercase would hash differently).
- ``size_bytes``: the non-negative integer byte count of the referenced
  payload. A bool is rejected (a flag is not a size).
- ``path`` (optional): a **portable** repo-relative path to the bytes. If
  present it must be relative, must not contain ``..``, must not contain a
  drive letter (``C:\\``), must not start with ``/``, and must not contain a
  backslash. The path is a *hint*; the ``digest`` is authoritative.

Portability
-----------
The path rules mirror :mod:`srl.autonomy.scopes` but are tightened for
artifacts: an artifact reference may be packed and unpacked on any platform,
so a Windows-style drive letter or backslash is rejected outright rather than
re-interpreted. The typed failure is :class:`ArtifactRefError` with
``fail_reason='CONTRACT_INVALID'``.
"""

from __future__ import annotations

import re
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.numbers import NumericContractError, validate_integer_byte_count

# Schema identity. Bumped only on a contract change to the reference shape.
ARTIFACT_REF_SCHEMA_VERSION: Final[str] = "ArtifactRef/v1"

# Typed fail reason for artifact-reference violations.
ARTIFACT_REF_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Digest policy: "sha256:" + exactly 64 lowercase hex digits. Lowercase-only
# so the canonical encoding (and therefore the identity hash) is stable.
_DIGEST_PATTERN: Final[str] = r"^sha256:[0-9a-f]{64}$"
_DIGEST_RE: Final[re.Pattern[str]] = re.compile(_DIGEST_PATTERN)

# Media type policy: "type/subtype" with optional tree/parameter suffix. Kept
# permissive but non-empty and slash-bearing so a bare token is rejected.
_MEDIA_TYPE_PATTERN: Final[str] = r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$"
_MEDIA_TYPE_RE: Final[re.Pattern[str]] = re.compile(_MEDIA_TYPE_PATTERN)

# A leading drive letter followed by ':' or '\\' (Windows drive / UNC start).
_DRIVE_LETTER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:[\\/]")


class ArtifactRefError(ContractError):
    """Raised when an ``ArtifactRef/v1`` value violates the contract.

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``) and the offending
    ``field`` for diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        field: str = "",
        fail_reason: str = ARTIFACT_REF_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.field: str = field


def validate_digest(value: Any, *, field: str = "digest") -> str:
    """Validate a content digest as ``"sha256:<64 lowercase hex>"``.

    Parameters
    ----------
    value:
        Candidate digest.

    Returns
    -------
    str
        The validated digest.

    Raises
    ------
    ArtifactRefError
        If ``value`` is not a string or does not match the digest policy
        (wrong algorithm, wrong length, or uppercase hex).
    """
    if not isinstance(value, str):
        msg = f"field {field!r} must be a string, got {type(value).__name__}"
        raise ArtifactRefError(msg, field=field)
    if not _DIGEST_RE.fullmatch(value):
        msg = (
            f"field {field!r}={value!r} must match {_DIGEST_PATTERN!r} (sha256 + 64 lowercase hex)"
        )
        raise ArtifactRefError(msg, field=field)
    return value


def validate_media_type(value: Any, *, field: str = "media_type") -> str:
    """Validate a non-empty IANA-style media type string.

    Raises
    ------
    ArtifactRefError
        If ``value`` is not a non-empty ``type/subtype`` string.
    """
    if not isinstance(value, str) or not value:
        msg = f"field {field!r} must be a non-empty string, got {type(value).__name__}"
        raise ArtifactRefError(msg, field=field)
    if not _MEDIA_TYPE_RE.fullmatch(value):
        msg = f"field {field!r}={value!r} must be a 'type/subtype' media type"
        raise ArtifactRefError(msg, field=field)
    return value


def validate_portable_path(value: Any, *, field: str = "path") -> str:
    """Validate ``value`` as a portable repo-relative path (artifact-safe).

    A portable path is:

    - a non-empty string;
    - relative (no leading ``/``);
    - free of ``..`` segments (no parent traversal);
    - free of backslashes (no Windows separators);
    - free of a leading drive letter (no ``C:\\`` style drive).

    Raises
    ------
    ArtifactRefError
        If any rule is violated.
    """
    if not isinstance(value, str) or value == "":
        msg = f"field {field!r} must be a non-empty string, got {type(value).__name__}"
        raise ArtifactRefError(msg, field=field)
    if value.startswith("/"):
        msg = f"field {field!r}={value!r} is absolute (must be repo-relative)"
        raise ArtifactRefError(msg, field=field)
    if "\\" in value:
        msg = f"field {field!r}={value!r} contains a backslash (non-portable)"
        raise ArtifactRefError(msg, field=field)
    if _DRIVE_LETTER_RE.fullmatch(value[:3]) or ":" in value.split("/", 1)[0]:
        msg = f"field {field!r}={value!r} contains a drive letter (non-portable)"
        raise ArtifactRefError(msg, field=field)
    # Reject any '..' segment, even mid-path. A reference never needs parent
    # traversal, and '..' is a strong signal of an escape attempt.
    parts = value.split("/")
    if ".." in parts:
        msg = f"field {field!r}={value!r} contains '..' (traversal forbidden)"
        raise ArtifactRefError(msg, field=field)
    return value


def validate_artifact_ref(value: Any) -> dict[str, Any]:
    """Validate ``value`` as an ``ArtifactRef/v1`` object.

    Parameters
    ----------
    value:
        Candidate artifact reference. Must be a JSON object with exactly the
        keys ``schema_version``, ``media_type``, ``digest``, ``size_bytes``,
        and the optional ``path``.

    Returns
    -------
    dict[str, Any]
        The validated reference (a plain dict).

    Raises
    ------
    ArtifactRefError
        If ``value`` is not an object, has missing/extra keys, or any field
        fails its validator.
    """
    if not isinstance(value, dict):
        msg = f"ArtifactRef must be a JSON object, got {type(value).__name__}"
        raise ArtifactRefError(msg, field="")
    # Strict key set: the four required keys plus the optional 'path'.
    required = ("schema_version", "media_type", "digest", "size_bytes")
    allowed = frozenset((*required, "path"))
    actual = set(value.keys())
    missing = [k for k in required if k not in actual]
    if missing:
        msg = f"ArtifactRef missing required key(s): {sorted(missing)}"
        raise ArtifactRefError(msg, field=missing[0])
    extra = sorted(actual - allowed)
    if extra:
        msg = f"ArtifactRef has unexpected key(s): {extra}"
        raise ArtifactRefError(msg, field=extra[0])
    if value["schema_version"] != ARTIFACT_REF_SCHEMA_VERSION:
        msg = (
            f"ArtifactRef.schema_version is {value['schema_version']!r}, "
            f"expected {ARTIFACT_REF_SCHEMA_VERSION!r}"
        )
        raise ArtifactRefError(msg, field="schema_version")
    validate_media_type(value["media_type"], field="media_type")
    validate_digest(value["digest"], field="digest")
    # The size and path validators raise their own typed errors; translate them
    # to ArtifactRefError so a caller validating a whole ref gets one error
    # family for any field failure, carrying the offending field name.
    try:
        validate_integer_byte_count(value["size_bytes"], field="size_bytes")
    except NumericContractError as exc:
        raise ArtifactRefError(str(exc), field="size_bytes") from exc
    if "path" in value:
        try:
            validate_portable_path(value["path"], field="path")
        except ArtifactRefError:
            raise
    return value


__all__ = [
    "ARTIFACT_REF_FAIL_REASON",
    "ARTIFACT_REF_SCHEMA_VERSION",
    "ArtifactRefError",
    "validate_artifact_ref",
    "validate_digest",
    "validate_media_type",
    "validate_portable_path",
]
