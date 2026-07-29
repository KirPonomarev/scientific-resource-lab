"""Shared application service used by CLI, MCP and portal surfaces."""

from __future__ import annotations

from srl.interfaces.service import InterfaceService, InterfaceServiceError

__all__ = ["InterfaceService", "InterfaceServiceError"]
