"""Single read-only application service for SRF user-facing interfaces."""

from __future__ import annotations

import platform
from typing import Final

from srl import __version__
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.labctl import enter_report, labctl_manifest
from srl.planning import load_default_catalog
from srl.solo_agent import (
    SoloAgentError,
    build_portal_for_session,
    export_session,
    replay_session,
    session_result,
    session_status,
    solo_doctor,
    submit_session,
)

INTERFACE_SERVICE_SCHEMA_VERSION: Final[str] = "InterfaceServiceReport/v1"


class InterfaceServiceError(ContractError):
    """Raised when a shared interface request is structurally invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class InterfaceService:
    """Read-only application service shared by CLI, MCP and portal."""

    def safety_consts(self) -> dict[str, object]:
        """Return structural authority-negative constants."""
        return {"canonical_writes": 0, "grants_authority": False}

    def doctor(self) -> dict[str, object]:
        """Return the CLI-compatible doctor report."""
        return {
            "schema_version": "DoctorReport/v1",
            "srl_version": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "status": "ok",
        }

    def solo_doctor(self) -> dict[str, object]:
        """Return the A17 solo-agent doctor report."""
        try:
            return solo_doctor()
        except SoloAgentError as exc:
            raise InterfaceServiceError(str(exc)) from exc

    def version(self) -> dict[str, object]:
        """Return the CLI-compatible version report."""
        return {"schema_version": "VersionReport/v1", "srl_version": __version__}

    def enter(self, cell_id: str = "standalone") -> dict[str, object]:
        """Return the labctl enter report for ``cell_id``."""
        try:
            return enter_report(cell_id)
        except ValueError as exc:
            raise InterfaceServiceError(str(exc)) from exc

    def solo_submit(self, session_dir: str, *, cell_id: str = "standalone") -> dict[str, object]:
        """Create a bounded local solo-agent session."""
        try:
            return submit_session(session_dir, cell_id=cell_id)
        except SoloAgentError as exc:
            raise InterfaceServiceError(str(exc)) from exc

    def solo_status(self, session_dir: str) -> dict[str, object]:
        """Return a solo-agent session status report."""
        try:
            return session_status(session_dir)
        except SoloAgentError as exc:
            raise InterfaceServiceError(str(exc)) from exc

    def solo_result(self, session_dir: str) -> dict[str, object]:
        """Return a solo-agent session result."""
        try:
            return session_result(session_dir)
        except SoloAgentError as exc:
            raise InterfaceServiceError(str(exc)) from exc

    def solo_export(self, session_dir: str) -> dict[str, object]:
        """Build a sanitized export packet for a solo-agent session."""
        try:
            return export_session(session_dir)
        except SoloAgentError as exc:
            raise InterfaceServiceError(str(exc)) from exc

    def solo_replay(self, session_dir: str) -> dict[str, object]:
        """Replay a solo-agent session."""
        try:
            return replay_session(session_dir)
        except SoloAgentError as exc:
            raise InterfaceServiceError(str(exc)) from exc

    def solo_portal(self, session_dir: str) -> dict[str, object]:
        """Render a portal for a solo-agent session."""
        try:
            return build_portal_for_session(session_dir)
        except SoloAgentError as exc:
            raise InterfaceServiceError(str(exc)) from exc

    def capability_list(self) -> dict[str, object]:
        """Return the shipped capability catalog list."""
        catalog = load_default_catalog()
        entries = [
            {
                "profile": entry.profile,
                "capability_id": entry.capability_id,
                "availability": entry.availability,
            }
            for entry in catalog.entries.values()
        ]
        entries.sort(key=lambda item: item["profile"])
        return {
            "schema_version": "CapabilityCatalogList/v1",
            "catalog_digest": catalog.digest,
            "entries": entries,
            **self.safety_consts(),
        }

    def capability_report(self) -> dict[str, object]:
        """Return the full shipped capability catalog report."""
        catalog = load_default_catalog()
        return {
            "schema_version": "CapabilityCatalogReport/v1",
            "catalog": catalog.to_dict(),
            **self.safety_consts(),
        }

    def inspect_capability(self, profile: str) -> dict[str, object]:
        """Return one capability entry by profile."""
        if not isinstance(profile, str) or not profile:
            raise InterfaceServiceError("profile must be a non-empty string")
        catalog = load_default_catalog()
        entry = catalog.entry_for(profile)
        if entry is None:
            raise InterfaceServiceError(f"unknown profile {profile!r}; not in the shipped catalog")
        return {
            "schema_version": "CapabilityCatalogEntry/v1",
            "catalog_digest": catalog.digest,
            "entry": {
                "capability_id": entry.capability_id,
                "profile": entry.profile,
                "adapter_id": entry.adapter_id,
                "availability": entry.availability,
            },
            **self.safety_consts(),
        }

    def portal_manifest(self, *, surface: str) -> dict[str, object]:
        """Return the read-only interface manifest embedded in portal reports."""
        capabilities = self.capability_list()
        return {
            "schema_version": INTERFACE_SERVICE_SCHEMA_VERSION,
            "surface": surface,
            "service": "InterfaceService",
            "manifest": labctl_manifest(),
            "catalog_digest": capabilities["catalog_digest"],
            "capability_count": len(capabilities["entries"]),  # type: ignore[arg-type]
            **self.safety_consts(),
        }


__all__ = ["INTERFACE_SERVICE_SCHEMA_VERSION", "InterfaceService", "InterfaceServiceError"]
