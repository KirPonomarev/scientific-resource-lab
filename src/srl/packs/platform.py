"""Execution platform detection and manifest platform matching.

The SRL pack runtime declares which platforms it can run on. This module maps the
local interpreter to a normalized platform tuple and checks whether a manifest's
platform list includes a compatible entry.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from typing import Any, Final

from srl.contracts.errors import ContractError
from srl.packs.manifest import PLATFORM_UNSUPPORTED_REASON, ResourcePackManifest, build_manifest


class PlatformError(ContractError):
    """Raised when the local platform is not supported by a pack manifest.

    Carries the typed fail reason ``PLATFORM_UNSUPPORTED``.
    """

    def __init__(self, message: str, *, fail_reason: str = PLATFORM_UNSUPPORTED_REASON) -> None:
        super().__init__(message, fail_reason=fail_reason)


# Normalized OS names. darwin is reported as macos for SRL portability.
OS_LINUX: Final[str] = "linux"
OS_MACOS: Final[str] = "macos"

# Normalized architecture names.
ARCH_X86_64: Final[str] = "x86_64"
ARCH_ARM64: Final[str] = "arm64"


@dataclass(frozen=True, slots=True)
class CurrentPlatform:
    """Normalized platform tuple for the running interpreter."""

    os: str
    arch: str


def _normalize_os() -> str:
    """Return the SRL-normalized OS name for ``sys.platform``."""
    if sys.platform.startswith("linux"):
        return OS_LINUX
    if sys.platform == "darwin":
        return OS_MACOS
    msg = f"unsupported interpreter OS: {sys.platform!r}"  # type: ignore[unreachable]
    raise PlatformError(msg)


def _normalize_arch(raw: str) -> str:
    """Return the SRL-normalized architecture name for ``platform.machine()``."""
    lower = raw.lower()
    if lower in {ARCH_X86_64, "amd64"}:
        return ARCH_X86_64
    if lower in {ARCH_ARM64, "aarch64"}:
        return ARCH_ARM64
    msg = f"unsupported interpreter architecture: {raw!r}"
    raise PlatformError(msg)


def current_platform() -> dict[str, str]:
    """Return the current platform as a normalized ``{os, arch}`` dict.

    Raises
    ------
    PlatformError
        If the OS or architecture is not supported by the SRL pack contract.
    """
    return {
        "os": _normalize_os(),
        "arch": _normalize_arch(platform.machine()),
    }


def check_manifest_platform(
    manifest: ResourcePackManifest | dict[str, Any],
    current: dict[str, str] | None = None,
) -> None:
    """Verify that ``manifest`` supports the current (or supplied) platform.

    Parameters
    ----------
    manifest:
        A validated :class:`ResourcePackManifest` or a raw dict (which will be
        built first).
    current:
        Optional platform dict to match against. If ``None``,
        :func:`current_platform` is used.

    Raises
    ------
    PlatformError
        With fail reason ``PLATFORM_UNSUPPORTED`` if no platform entry matches.
    PackManifestError
        If ``manifest`` is a raw dict that fails validation.
    """
    if current is None:
        current = current_platform()

    if isinstance(manifest, dict):
        manifest = build_manifest(manifest)

    current_os = current["os"]
    current_arch = current["arch"]
    current_abi = current.get("abi")

    for spec in manifest.platforms:
        if spec.os != current_os or spec.arch != current_arch:
            continue
        if current_abi is not None and spec.abi is not None and spec.abi != current_abi:
            continue
        return

    msg = (
        f"platform {current_os!r}/{current_arch!r} "
        f"(abi={current_abi!r}) is not supported by pack {manifest.pack_id!r}; "
        f"manifest supports: {[(p.os, p.arch, p.abi) for p in manifest.platforms]}"
    )
    raise PlatformError(msg)


__all__ = [
    "ARCH_ARM64",
    "ARCH_X86_64",
    "OS_LINUX",
    "OS_MACOS",
    "PLATFORM_UNSUPPORTED_REASON",
    "CurrentPlatform",
    "PlatformError",
    "check_manifest_platform",
    "current_platform",
]
