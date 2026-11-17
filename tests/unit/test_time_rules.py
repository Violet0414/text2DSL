"""时间缺省规则测试(FR-B3):裸指标→澄清时间;带维度/筛选/对比→默认全部时间;K3 继承优先。"""

from __future__ import annotations

from datetime import date

from chatbi.time_rules import TimeDecision, resolve_time

TODAY = date(2026, 11, 16)

PREV_TD = [
    {
        "dimension": "order_date",
        "dateRange": ["2026-10-01", "2026-11-01"],
        "granularity": "month",
    }
]


def test_bare_metric_without_time_clarifies():
    # 裸指标无任何修饰(PoC 偏差记录2 固化):必须澄清时间,不得默认出数
    decision = resolve_time(
        time_spec=None, has_dimensions=False, has_filters=False, prev_td=None
    )
    assert decision.action == "clarify"


def test_metric_with_dimension_defaults_to_all_time():
    decision = resolve_time(
        time_spec=None, has_dimensions=True, has_filters=False, prev_td=None
    )
    assert decision.action == "all_time"
    assert (
        decision.time_dimensions
        and decision.time_dimensions[0]["dateRange"][0] == "2000-01-01"
    )


def test_metric_with_filter_defaults_to_all_time():
    decision = resolve_time(
        time_spec=None, has_dimensions=False, has_filters=True, prev_td=None
    )
    assert decision.action == "all_time"


def test_inherit_takes_priority_over_defaults():
    # K3:上一轮有 timeDimensions 且当前轮未提时间 → 直接继承
    decision = resolve_time(
        time_spec=None, has_dimensions=True, has_filters=False, prev_td=PREV_TD
    )
    assert decision.action == "inherit"
    assert list(decision.time_dimensions) == PREV_TD


def test_explicit_slot_expands_half_open():
    decision = resolve_time(
        time_spec={"slot": "last_month"},
        has_dimensions=False,
        has_filters=False,
        prev_td=PREV_TD,  # 显式时间覆盖继承
    )
    assert decision.action == "expand"
    assert decision.time_dimensions[0]["dateRange"] == ["2026-10-01", "2026-11-01"]
    assert decision.time_dimensions[0]["granularity"] == "month"


def test_comparison_slot_yoy_expands_two_ranges():
    decision = resolve_time(
        time_spec={"slot": "yoy"}, has_dimensions=False, has_filters=False, prev_td=None
    )
    assert decision.action == "expand"
    assert len(decision.time_dimensions) == 2
    assert decision.time_dimensions[1]["dateRange"] == ["2025-11-01", "2025-12-01"]


def test_explicit_range_without_dates_falls_back_to_clarify():
    decision = resolve_time(
        time_spec={"slot": "explicit"},
        has_dimensions=False,
        has_filters=False,
        prev_td=None,
    )
    assert decision.action == "clarify"


def test_all_time_decision_is_immutable():
    decision = TimeDecision(action="clarify")
    try:
        decision.action = "expand"
    except Exception:  # noqa: BLE001
        return
    raise AssertionError("TimeDecision 应为 frozen dataclass")
