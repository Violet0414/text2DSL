"""时间槽位 → 半开区间确定性展开的单元测试(实测事实 #2:dateRange 左闭右开)。"""

from __future__ import annotations

from datetime import date

import pytest

from chatbi.planner.time_expand import DateRange, expand_time

TODAY = date(2026, 11, 16)


def test_last_month_is_half_open():
    expanded = expand_time("last_month", TODAY)
    assert expanded.base.to_strings() == ["2026-10-01", "2026-11-01"]
    assert expanded.compare is None


def test_today_is_single_day_half_open():
    expanded = expand_time("today", TODAY)
    assert expanded.base.to_strings() == ["2026-11-16", "2026-11-17"]


def test_last_7d_ends_exclusive_at_today():
    expanded = expand_time("last_7d", TODAY)
    assert expanded.base.to_strings() == ["2026-11-09", "2026-11-16"]


def test_yoy_yields_base_and_compare_ranges():
    expanded = expand_time("yoy", TODAY)
    assert expanded.base.to_strings() == ["2026-11-01", "2026-12-01"]
    assert expanded.compare is not None
    assert expanded.compare.to_strings() == ["2025-11-01", "2025-12-01"]


def test_mom_compare_is_previous_month():
    expanded = expand_time("mom", TODAY)
    assert expanded.base.to_strings() == ["2026-11-01", "2026-12-01"]
    assert expanded.compare.to_strings() == ["2026-10-01", "2026-11-01"]


def test_explicit_range_passthrough_with_granularity():
    expanded = expand_time(
        "explicit", TODAY, explicit_range=["2026-01-01", "2026-02-01"], granularity="day"
    )
    assert expanded.base.to_strings() == ["2026-01-01", "2026-02-01"]
    assert expanded.granularity == "day"


def test_explicit_without_range_raises():
    import pytest

    with pytest.raises(ValueError):
        expand_time("explicit", TODAY)


def test_unknown_slot_raises():
    import pytest

    with pytest.raises(ValueError):
        expand_time("tomorrow_forever", TODAY)


def test_daterange_is_frozen():
    dr = DateRange(TODAY, TODAY)
    try:
        dr.start = date(2020, 1, 1)  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("DateRange 应为 frozen dataclass")
