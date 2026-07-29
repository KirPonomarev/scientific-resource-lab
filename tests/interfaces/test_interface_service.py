from __future__ import annotations

import json
from typing import Any

import pytest

from srl.cli import EXIT_OK, main
from srl.interfaces import InterfaceService
from srl.mcp.methods import MethodContext, m_inspect_capability, m_list_capabilities
from srl.portal import PortalMode, build_portal


def _stdout_json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    line = capsys.readouterr().out.splitlines()[0]
    data = json.loads(line)
    assert isinstance(data, dict)
    return data


def test_cli_and_mcp_capability_list_share_service(
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = InterfaceService().capability_list()

    assert main(["catalog", "list"]) == EXIT_OK
    cli = _stdout_json(capsys)
    mcp = m_list_capabilities(MethodContext(), {})["result"]

    assert cli["catalog_digest"] == service["catalog_digest"] == mcp["catalog_digest"]
    assert cli["entries"] == service["entries"] == mcp["entries"]
    assert cli["canonical_writes"] == 0
    assert cli["grants_authority"] is False


def test_mcp_inspect_capability_matches_service() -> None:
    service = InterfaceService().inspect_capability("algebra_exact")
    mcp = m_inspect_capability(MethodContext(), {"profile": "algebra_exact"})["result"]

    assert mcp["catalog_digest"] == service["catalog_digest"]
    assert mcp["entry"] == service["entry"]


def test_cli_labctl_enter_matches_service(capsys: pytest.CaptureFixture[str]) -> None:
    service = InterfaceService().enter("standalone")

    assert main(["labctl", "enter", "standalone"]) == EXIT_OK
    cli = _stdout_json(capsys)

    assert cli == service


def test_portal_report_carries_service_manifest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    objects = tmp_path / "objects"
    objects.mkdir()
    (objects / "empty.json").write_text("", encoding="utf-8")

    report = build_portal(objects, tmp_path / "out", PortalMode.public_demo)
    service = InterfaceService().capability_list()

    assert report.interface_manifest["service"] == "InterfaceService"
    assert report.interface_manifest["catalog_digest"] == service["catalog_digest"]
    assert report.interface_manifest["canonical_writes"] == 0
    assert report.interface_manifest["grants_authority"] is False
