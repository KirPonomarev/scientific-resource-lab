"""Unit tests for ArtifactRef/v1 validation (srl.contracts.artifact_refs).

Pins:

1. A valid reference (with and without the optional ``path``) is accepted.
2. The digest, media type, and size validators each reject their bad inputs.
3. Portable-path rules reject absolute, ``..``, backslash, and drive-letter
   paths, all carrying ``fail_reason='CONTRACT_INVALID'``.
"""

from __future__ import annotations

import pytest

from srl.contracts.artifact_refs import (
    ARTIFACT_REF_FAIL_REASON,
    ARTIFACT_REF_SCHEMA_VERSION,
    ArtifactRefError,
    validate_artifact_ref,
    validate_digest,
    validate_media_type,
    validate_portable_path,
)

# A canonical, valid 64-hex digest.
_GOOD_DIGEST = "sha256:" + "a" * 64


def _good_ref(**overrides: object) -> dict[str, object]:
    """Return a valid ArtifactRef dict, with optional field overrides."""
    base: dict[str, object] = {
        "schema_version": ARTIFACT_REF_SCHEMA_VERSION,
        "media_type": "application/json",
        "digest": _GOOD_DIGEST,
        "size_bytes": 42,
    }
    base.update(overrides)
    return base


def test_validate_artifact_ref_accepts_minimal() -> None:
    """A valid reference without a path is accepted."""
    ref = _good_ref()
    assert validate_artifact_ref(ref) == ref


def test_validate_artifact_ref_accepts_with_portable_path() -> None:
    """A valid reference with a repo-relative path is accepted."""
    ref = _good_ref(path="data/claims/c1.json")
    assert validate_artifact_ref(ref) == ref


def test_validate_artifact_ref_rejects_non_object() -> None:
    """A non-object is rejected."""
    with pytest.raises(ArtifactRefError):
        validate_artifact_ref([1, 2, 3])  # type: ignore[arg-type]


def test_validate_artifact_ref_rejects_wrong_schema_version() -> None:
    """A wrong schema_version is rejected."""
    with pytest.raises(ArtifactRefError) as exc_info:
        validate_artifact_ref(_good_ref(schema_version="ArtifactRef/v2"))
    assert exc_info.value.field == "schema_version"


def test_validate_artifact_ref_rejects_missing_required() -> None:
    """A missing required key is rejected."""
    ref = _good_ref()
    del ref["digest"]  # type: ignore[typeddict-item]
    with pytest.raises(ArtifactRefError) as exc_info:
        validate_artifact_ref(ref)
    assert "digest" in exc_info.value.field


def test_validate_artifact_ref_rejects_extra_key() -> None:
    """An unexpected key is rejected."""
    with pytest.raises(ArtifactRefError) as exc_info:
        validate_artifact_ref(_good_ref(unexpected="x"))
    assert exc_info.value.field == "unexpected"


def test_validate_artifact_ref_rejects_bool_size() -> None:
    """A bool size_bytes is rejected (a flag is not a size)."""
    with pytest.raises(ArtifactRefError):
        validate_artifact_ref(_good_ref(size_bytes=True))


def test_validate_artifact_ref_rejects_negative_size() -> None:
    """A negative size_bytes is rejected."""
    with pytest.raises(ArtifactRefError):
        validate_artifact_ref(_good_ref(size_bytes=-1))


def test_validate_artifact_ref_rejects_bad_path() -> None:
    """A non-portable path is rejected at the ref level."""
    with pytest.raises(ArtifactRefError):
        validate_artifact_ref(_good_ref(path="/etc/passwd"))


# --- Field-level validators -------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [_GOOD_DIGEST, "sha256:" + "0" * 64, "sha256:" + "f" * 64],
)
def test_validate_digest_accepts(value: str) -> None:
    """Valid digests are accepted."""
    assert validate_digest(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "sha256:abc",  # too short
        "sha256:" + "A" * 64,  # uppercase
        "md5:" + "a" * 64,  # wrong algo
        "a" * 64,  # no prefix
        "",
    ],
)
def test_validate_digest_rejects(value: str) -> None:
    """Invalid digests are rejected."""
    with pytest.raises(ArtifactRefError) as exc_info:
        validate_digest(value)
    assert exc_info.value.fail_reason == ARTIFACT_REF_FAIL_REASON


@pytest.mark.parametrize(
    "value",
    ["application/json", "text/plain", "application/vnd.srlab.claim+json"],
)
def test_validate_media_type_accepts(value: str) -> None:
    """Valid media types are accepted."""
    assert validate_media_type(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "application", "json/application/extra", "no-slash"],
)
def test_validate_media_type_rejects(value: str) -> None:
    """Invalid media types are rejected."""
    with pytest.raises(ArtifactRefError):
        validate_media_type(value)


@pytest.mark.parametrize(
    "value",
    ["data/c1.json", "a/b/c.json", "file.txt"],
)
def test_validate_portable_path_accepts(value: str) -> None:
    """Portable repo-relative paths are accepted."""
    assert validate_portable_path(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "/etc/passwd",  # absolute
        "../../secret",  # traversal
        "legit/../escape",  # mid-path traversal
        "C:\\evil\\path",  # drive + backslash
        "data\\file.json",  # backslash
        "C:data.json",  # drive letter
    ],
)
def test_validate_portable_path_rejects(value: str) -> None:
    """Non-portable paths are rejected with CONTRACT_INVALID."""
    with pytest.raises(ArtifactRefError) as exc_info:
        validate_portable_path(value)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_validate_portable_path_rejects_empty() -> None:
    """An empty path is rejected."""
    with pytest.raises(ArtifactRefError):
        validate_portable_path("")
