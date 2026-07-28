"""Unit tests for run materialization (srl.execution.materialize).

The materializer resolves content-addressed input references and an optional pack
reference from a store, copies them into a fresh staging tree, re-hashes the
copy, and makes the inputs read-only. A hash mismatch or an unpinned reference
aborts before a run receipt is ever produced.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from srl.cas import LocalArtifactStore
from srl.cas.engine import CasIntegrityError
from srl.cas.store import ArtifactDescriptor, ArtifactStore, FsckReport, StoreIntegrityError
from srl.execution.materialize import (
    MaterializationError,
    StagedRun,
    materialize_run,
)


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture
def input_bytes() -> bytes:
    return b'{"value":"hello"}'


@pytest.fixture
def input_digest(input_bytes: bytes) -> str:
    return _sha256_digest(input_bytes)


class _MinimalStore(ArtifactStore):
    """A minimal in-memory ArtifactStore for injection tests."""

    def __init__(self, data: dict[str, bytes]) -> None:
        self._data = data

    def put(self, data: bytes) -> ArtifactDescriptor:
        raise NotImplementedError

    def has(self, digest: str) -> bool:
        return digest in self._data

    def get(self, digest: str) -> bytes:
        if digest not in self._data:
            raise RuntimeError("not found")
        return self._data[digest]

    def fsck(self) -> FsckReport:
        return FsckReport(objects_checked=0, objects_passed=0, failed_digests=[])


# ---------------------------------------------------------------------------
# Happy paths.
# ---------------------------------------------------------------------------


def test_materialize_single_input_stages_and_verifies(tmp_path: Path) -> None:
    """A single input digest is staged, verified, and chmod 0o400."""
    data = b'{"value":"hello"}'
    digest = _sha256_digest(data)
    store = LocalArtifactStore(tmp_path / "store")
    store.ingest_bytes(data, "application/json")

    run_spec = {
        "adapter_id": "echo.v1",
        "input_payloads": {"input.json": digest},
        "pack_ref": None,
    }
    staged = materialize_run(run_spec, store, tmp_path / "staging")

    assert isinstance(staged, StagedRun)
    assert staged.adapter_id == "echo.v1"
    assert staged.pack_digest is None
    assert staged.input_digests == {"input.json": digest}
    assert staged.staging_path.is_dir()

    staged_file = staged.staging_path / "input.json"
    assert staged_file.read_bytes() == data
    assert os.stat(staged_file).st_mode & 0o777 == 0o400


def test_materialize_multiple_inputs_and_pack(tmp_path: Path) -> None:
    """Several inputs and a pack reference are staged and verified."""
    input_a = b"input-a"
    input_b = b"input-b"
    pack = b"pack-data"
    digests = {
        "input-a.json": _sha256_digest(input_a),
        "input-b.json": _sha256_digest(input_b),
    }
    pack_digest = _sha256_digest(pack)
    store = LocalArtifactStore(tmp_path / "store")
    for data in (input_a, input_b, pack):
        store.ingest_bytes(data, "application/octet-stream")

    run_spec = {
        "adapter_id": "uppercase.v1",
        "input_payloads": digests,
        "pack_ref": pack_digest,
    }
    staged = materialize_run(run_spec, store, tmp_path / "staging")

    assert staged.pack_digest == pack_digest
    for name, data in (("input-a.json", input_a), ("input-b.json", input_b)):
        assert (staged.staging_path / name).read_bytes() == data
    assert (staged.staging_path / "pack.blob").read_bytes() == pack


# ---------------------------------------------------------------------------
# Integrity failures.
# ---------------------------------------------------------------------------


def test_materialize_raises_on_store_corruption(tmp_path: Path) -> None:
    """A corrupted store object is rejected by the store itself before staging."""
    data = b'{"value":"hello"}'
    digest = _sha256_digest(data)
    store = LocalArtifactStore(tmp_path / "store")
    store.ingest_bytes(data, "application/json")
    obj_path = store._object_path(digest)
    # Corrupt one byte in the stored object.
    corrupted = obj_path.read_bytes()[:-1] + b"X"
    obj_path.write_bytes(corrupted)

    run_spec = {
        "adapter_id": "echo.v1",
        "input_payloads": {"input.json": digest},
        "pack_ref": None,
    }
    with pytest.raises((CasIntegrityError, StoreIntegrityError)) as exc_info:
        materialize_run(run_spec, store, tmp_path / "staging")
    assert exc_info.value.fail_reason == "CAS_INTEGRITY_FAILURE"


def test_materialize_raises_on_post_copy_hash_mismatch(tmp_path: Path) -> None:
    """A store that returns mismatched bytes triggers post-copy verification."""
    data = b'{"value":"hello"}'
    declared = _sha256_digest(data)
    wrong = b"different-bytes"
    store = _MinimalStore({declared: wrong})

    run_spec = {
        "adapter_id": "echo.v1",
        "input_payloads": {"input.json": declared},
        "pack_ref": None,
    }
    with pytest.raises((CasIntegrityError, StoreIntegrityError)) as exc_info:
        materialize_run(run_spec, store, tmp_path / "staging")
    assert exc_info.value.fail_reason == "CAS_INTEGRITY_FAILURE"
    observed_digest = getattr(exc_info.value, "expected_digest", "") or getattr(
        exc_info.value, "digest", ""
    )
    assert observed_digest == declared


# ---------------------------------------------------------------------------
# Contract / unpinned references.
# ---------------------------------------------------------------------------


def test_materialize_raises_on_unpinned_input(tmp_path: Path) -> None:
    """A digest not present in the store is unpinned -> CONTRACT_INVALID."""
    missing = "sha256:" + "0" * 64
    run_spec = {
        "adapter_id": "echo.v1",
        "input_payloads": {"input.json": missing},
        "pack_ref": None,
    }
    with pytest.raises(MaterializationError) as exc_info:
        materialize_run(run_spec, LocalArtifactStore(tmp_path / "store"), tmp_path / "staging")
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_materialize_raises_on_unpinned_pack(tmp_path: Path) -> None:
    """A missing pack digest is unpinned -> CONTRACT_INVALID."""
    data = b"x"
    digest = _sha256_digest(data)
    store = LocalArtifactStore(tmp_path / "store")
    store.ingest_bytes(data, "application/json")
    missing = "sha256:" + "0" * 64

    run_spec = {
        "adapter_id": "echo.v1",
        "input_payloads": {"input.json": digest},
        "pack_ref": missing,
    }
    with pytest.raises(MaterializationError) as exc_info:
        materialize_run(run_spec, store, tmp_path / "staging")
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_materialize_raises_on_invalid_digest_format(tmp_path: Path) -> None:
    """A non-sha256 digest string is an unpinned reference -> CONTRACT_INVALID."""
    run_spec = {
        "adapter_id": "echo.v1",
        "input_payloads": {"input.json": "not-a-digest"},
        "pack_ref": None,
    }
    with pytest.raises(MaterializationError) as exc_info:
        materialize_run(run_spec, LocalArtifactStore(tmp_path / "store"), tmp_path / "staging")
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


@pytest.mark.parametrize(
    "spec",
    [
        {},
        {"adapter_id": "echo.v1"},
        {"input_payloads": {}},
        {"adapter_id": 123, "input_payloads": {}, "pack_ref": None},
    ],
)
def test_materialize_raises_on_malformed_run_spec(spec: Any, tmp_path: Path) -> None:
    """A malformed run_spec is a contract error before any staging."""
    with pytest.raises(MaterializationError) as exc_info:
        materialize_run(spec, LocalArtifactStore(tmp_path / "store"), tmp_path / "staging")
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


# ---------------------------------------------------------------------------
# Staging cleanup on failure.
# ---------------------------------------------------------------------------


def test_materialize_cleans_up_staging_on_failure(tmp_path: Path) -> None:
    """A failed materialization does not leave a staging tree behind."""
    data = b"x"
    declared = _sha256_digest(data)
    store = _MinimalStore({declared: b"y"})
    run_spec = {
        "adapter_id": "echo.v1",
        "input_payloads": {"input.json": declared},
        "pack_ref": None,
    }
    with pytest.raises(CasIntegrityError):
        materialize_run(run_spec, store, tmp_path / "staging")
    assert not list((tmp_path / "staging").glob("srl-run-*"))
