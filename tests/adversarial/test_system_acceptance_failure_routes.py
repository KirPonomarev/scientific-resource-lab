from __future__ import annotations

import json
from pathlib import Path

from srl.cas.capacity import CapacityDecision, check_capacity
from srl.execution.adversarial import AdversarialKind
from srl.runtime import HeavyCapabilityStatus

RECEIPT_PATH = Path("docs/verification/system-acceptance-receipt.json")


def _receipt() -> dict[str, object]:
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def test_s25_receipt_does_not_convert_failures_into_authority() -> None:
    receipt = _receipt()
    chaos = receipt["chaos_receipts"]
    assert isinstance(chaos, dict)

    for chaos_id, item in chaos.items():
        assert isinstance(item, dict), chaos_id
        assert item["canonical_writes"] == 0, chaos_id
        assert item["grants_authority"] is False, chaos_id
        assert item["live_actions"] == 0, chaos_id


def test_s25_failure_taxonomy_is_backed_by_runtime_enums() -> None:
    adversarial = {kind.value for kind in AdversarialKind}

    assert {"command_injection", "path_injection", "corrupted_input"} <= adversarial
    assert check_capacity(50 * 1024**3) is CapacityDecision.EXCEEDED
    assert HeavyCapabilityStatus.REJECTED.value == "REJECTED"


def test_s25_chaos_routes_name_real_test_selectors() -> None:
    receipt = _receipt()
    chaos = receipt["chaos_receipts"]
    assert isinstance(chaos, dict)

    for chaos_id, item in chaos.items():
        assert isinstance(item, dict), chaos_id
        selectors = item["test_selectors"]
        assert isinstance(selectors, list), chaos_id
        assert selectors, chaos_id
        for selector in selectors:
            assert isinstance(selector, str), chaos_id
            path = selector.split("::", maxsplit=1)[0]
            assert Path(path).exists(), f"{chaos_id}: {selector}"
