"""Hermetic tests for the private overlay resolver (WP-G60).

Pins the WAIT_ENVIRONMENT wait (never a default guess), the CONTRACT_INVALID
structural rejections, the successful resolution, and the no-leak property.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import srl.pilot.overlay as overlay_mod
from srl.pilot.overlay import (
    ARTIFACT_STORE_ENV,
    OVERLAY_FAIL_REASON,
    PRIVATE_CONFIG_ENV,
    REQUIRED_ENV_VARS,
    OverlayConfig,
    OverlayError,
    resolve_overlay,
)


def test_overlay_reads_only_two_env_vars() -> None:
    """resolve_overlay reads ONLY SRL_PRIVATE_CONFIG and SRL_ARTIFACT_STORE."""
    assert set(REQUIRED_ENV_VARS) == {PRIVATE_CONFIG_ENV, ARTIFACT_STORE_ENV}


def test_overlay_empty_env_raises_wait_environment() -> None:
    """An empty env raises WAIT_ENVIRONMENT naming both missing vars."""
    with pytest.raises(OverlayError) as exc_info:
        resolve_overlay({})
    assert exc_info.value.fail_reason == OVERLAY_FAIL_REASON
    assert set(exc_info.value.missing_vars) == {PRIVATE_CONFIG_ENV, ARTIFACT_STORE_ENV}


def test_overlay_partial_env_raises_wait_environment() -> None:
    """A partial env (one var set) raises WAIT_ENVIRONMENT naming the missing var."""
    with pytest.raises(OverlayError) as exc_info:
        resolve_overlay({PRIVATE_CONFIG_ENV: "/nonexistent/config.json"})
    assert exc_info.value.fail_reason == OVERLAY_FAIL_REASON
    assert exc_info.value.missing_vars == (ARTIFACT_STORE_ENV,)


@pytest.mark.parametrize(
    "env",
    [
        {},
        {PRIVATE_CONFIG_ENV: ""},
        {ARTIFACT_STORE_ENV: ""},
        {PRIVATE_CONFIG_ENV: "   "},
    ],
)
def test_overlay_never_fabricates_default(env: dict[str, str]) -> None:
    """resolve_overlay never returns a config when env is missing/empty."""
    with pytest.raises(OverlayError):
        resolve_overlay(env)


def test_overlay_resolves_valid_env(tmp_path: Path) -> None:
    """A present, valid env resolves to an OverlayConfig with absolute paths."""
    config = tmp_path / "private-config.json"
    config.write_text(json.dumps({"overlay": "operator-private"}), encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    overlay = resolve_overlay({PRIVATE_CONFIG_ENV: str(config), ARTIFACT_STORE_ENV: str(store)})
    assert isinstance(overlay, OverlayConfig)
    assert overlay.config_path.is_absolute()
    assert overlay.artifact_store.is_absolute()
    assert overlay.config_path == config.resolve()
    assert overlay.artifact_store == store.resolve()


def test_overlay_expands_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ~ in the config path is expanded against the home dir."""
    config = tmp_path / "c.json"
    config.write_text("{}", encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    overlay = resolve_overlay({PRIVATE_CONFIG_ENV: "~/c.json", ARTIFACT_STORE_ENV: str(store)})
    assert overlay.config_path == config.resolve()


def test_overlay_rejects_missing_store_dir(tmp_path: Path) -> None:
    """A store path that is not an existing directory is CONTRACT_INVALID."""
    config = tmp_path / "c.json"
    config.write_text("{}", encoding="utf-8")
    with pytest.raises(OverlayError) as exc_info:
        resolve_overlay(
            {
                PRIVATE_CONFIG_ENV: str(config),
                ARTIFACT_STORE_ENV: str(tmp_path / "does-not-exist"),
            }
        )
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_overlay_rejects_store_not_directory(tmp_path: Path) -> None:
    """A store path that is a file (not a dir) is CONTRACT_INVALID."""
    config = tmp_path / "c.json"
    config.write_text("{}", encoding="utf-8")
    store_file = tmp_path / "not-a-dir"
    store_file.write_text("x", encoding="utf-8")
    with pytest.raises(OverlayError) as exc_info:
        resolve_overlay({PRIVATE_CONFIG_ENV: str(config), ARTIFACT_STORE_ENV: str(store_file)})
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_overlay_rejects_missing_config_file(tmp_path: Path) -> None:
    """A config path that does not exist is CONTRACT_INVALID."""
    store = tmp_path / "store"
    store.mkdir()
    with pytest.raises(OverlayError) as exc_info:
        resolve_overlay(
            {
                PRIVATE_CONFIG_ENV: str(tmp_path / "missing.json"),
                ARTIFACT_STORE_ENV: str(store),
            }
        )
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_overlay_rejects_malformed_config(tmp_path: Path) -> None:
    """A config file that is not valid JSON is CONTRACT_INVALID."""
    config = tmp_path / "c.json"
    config.write_text("{not json", encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    with pytest.raises(OverlayError) as exc_info:
        resolve_overlay({PRIVATE_CONFIG_ENV: str(config), ARTIFACT_STORE_ENV: str(store)})
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_overlay_rejects_non_object_config(tmp_path: Path) -> None:
    """A config file that is valid JSON but not an object is CONTRACT_INVALID."""
    config = tmp_path / "c.json"
    config.write_text("[1, 2, 3]", encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    with pytest.raises(OverlayError) as exc_info:
        resolve_overlay({PRIVATE_CONFIG_ENV: str(config), ARTIFACT_STORE_ENV: str(store)})
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_overlay_config_equality_and_hash(tmp_path: Path) -> None:
    """Two OverlayConfigs with the same paths are equal and hash equally."""
    config = tmp_path / "c.json"
    config.write_text("{}", encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    env = {PRIVATE_CONFIG_ENV: str(config), ARTIFACT_STORE_ENV: str(store)}
    a = resolve_overlay(env)
    b = resolve_overlay(env)
    assert a == b
    assert hash(a) == hash(b)
    assert a != "not an overlay"


def test_overlay_config_does_not_leak_contents(tmp_path: Path) -> None:
    """The OverlayConfig repr exposes only the two paths, never the contents."""
    config = tmp_path / "c.json"
    leak_canary = "SUPER_SECRET_OPERATOR_CONTENT_DO_NOT_LEAK"
    config.write_text(json.dumps({"payload": leak_canary}), encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    overlay = resolve_overlay({PRIVATE_CONFIG_ENV: str(config), ARTIFACT_STORE_ENV: str(store)})
    assert leak_canary not in repr(overlay)


def test_overlay_module_has_no_hardcoded_private_path() -> None:
    """The overlay module source contains no hardcoded absolute private path."""
    src = Path(overlay_mod.__file__).read_text(encoding="utf-8")
    # The module may mention the env var NAMES and may mention ~/.srl in a
    # comment explaining it does NOT fall back to it, but must not contain a
    # real absolute path under /Users, /home, or /Volumes.
    real_path = re.compile(
        r"(?:/Users/[A-Za-z0-9][A-Za-z0-9._-]*|/home/[A-Za-z0-9][A-Za-z0-9._-]*"
        r"|/Volumes/[A-Za-z0-9][A-Za-z0-9._-]*)"
    )
    assert not real_path.search(src), "overlay module has a hardcoded private path"
