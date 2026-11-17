"""治理门禁四门校验测试(FR-D4):已确认+试运行通过+工具启用+描述齐备。"""

from __future__ import annotations

import pytest

from chatbi.gate import FileGateStateRepository, GovernanceGate

MEASURES = [
    "sales_amount",
    "sales_amount_with_tax",
    "order_count",
    "avg_order_value",
    "refund_rate",
]


def _mdl_with_descriptions(desc_by_measure: dict[str, str]) -> dict:
    return {
        "cubes": [
            {
                "name": "sales",
                "measures": [
                    {"name": m, "properties": {"description": desc_by_measure.get(m, "")}}
                    for m in MEASURES
                ],
                "dimensions": [],
                "timeDimensions": [],
            }
        ]
    }


def _all_open_flags() -> dict[str, dict[str, bool]]:
    return {
        m: {"confirmed": True, "trial_passed": True, "tool_enabled": True} for m in MEASURES
    }


class FakeGateRepo:
    def __init__(self, flags: dict[str, dict[str, bool]]):
        self._flags = flags

    def get_flags(self) -> dict[str, dict[str, bool]]:
        return self._flags


def _make_gate(flags=None, descriptions=None) -> GovernanceGate:
    return GovernanceGate(
        repo=FakeGateRepo(flags if flags is not None else _all_open_flags()),
        mdl=_mdl_with_descriptions(descriptions or {m: "口径说明" for m in MEASURES}),
    )


def _query(measures: list[str]) -> dict:
    return {"cube": "sales", "measures": measures}


class TestFourDoors:
    def test_query_with_all_doors_open_passes(self):
        verdict = _make_gate().check_query(_query(["sales_amount", "order_count"]))
        assert verdict.passed
        assert verdict.denied == ()

    @pytest.mark.parametrize("door", ["confirmed", "trial_passed", "tool_enabled"])
    def test_each_closed_door_denies_measure(self, door):
        flags = _all_open_flags()
        flags["sales_amount"][door] = False
        verdict = _make_gate(flags=flags).check_query(_query(["sales_amount"]))
        assert not verdict.passed
        assert "sales_amount" in verdict.denied
        assert door in verdict.reasons["sales_amount"]

    def test_unknown_measure_denied_by_safe_default(self):
        # 门禁仓库中没有登记的指标一律拒绝(安全默认)
        verdict = _make_gate(flags={}).check_query(_query(["sales_amount"]))
        assert not verdict.passed
        assert "sales_amount" in verdict.denied

    def test_missing_description_closes_fourth_door(self):
        descriptions = {m: "口径说明" for m in MEASURES}
        descriptions["refund_rate"] = ""
        verdict = _make_gate(descriptions=descriptions).check_query(_query(["refund_rate"]))
        assert not verdict.passed
        assert "description" in verdict.reasons["refund_rate"]

    def test_partial_denial_reports_only_denied_members(self):
        flags = _all_open_flags()
        flags["refund_rate"]["tool_enabled"] = False
        verdict = _make_gate(flags=flags).check_query(_query(["sales_amount", "refund_rate"]))
        assert verdict.denied == ("refund_rate",)
        assert "sales_amount" not in verdict.denied


class TestDefaultConfig:
    def test_default_gate_config_keeps_poc_metrics_all_open(self):
        # PoC 基线指标四门默认全开,保证与 poc 行为一致
        repo = FileGateStateRepository()
        flags = repo.get_flags()
        for m in MEASURES:
            assert flags[m] == {"confirmed": True, "trial_passed": True, "tool_enabled": True}
