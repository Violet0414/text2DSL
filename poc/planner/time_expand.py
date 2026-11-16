"""时间槽位 → 半开区间 [start, end) dateRange 的确定性展开。

关键底座事实(实测):wren cube query 的 dateRange 生成 SQL 为
``>= start AND < end``(左闭右开),因此所有槽位一律展开为半开区间,
月末 = 次月 1 日,避免漏掉最后一天。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from planner.schema import TIME_SLOTS


@dataclass(frozen=True)
class DateRange:
    """Half-open date range [start, end)."""

    start: date
    end: date

    def to_strings(self) -> list[str]:
        return [self.start.isoformat(), self.end.isoformat()]


@dataclass(frozen=True)
class ExpandedTime:
    """One or two ranges: comparison slots (yoy/mom) yield base + compare."""

    base: DateRange
    compare: DateRange | None = None
    granularity: str | None = None


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_add(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def _week_start(d: date) -> date:
    # ISO week: Monday = weekday 0
    return d - timedelta(days=d.weekday())


def _quarter_start(d: date) -> date:
    return date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)


def _expand_base(slot: str, today: date) -> DateRange:
    """Expand a single non-comparison slot into a half-open range."""
    matchers: dict[str, Callable[[date], DateRange]] = {
        "today": lambda t: DateRange(t, t + timedelta(days=1)),
        "current_week": lambda t: DateRange(_week_start(t), _week_start(t) + timedelta(days=7)),
        "current_month": lambda t: DateRange(_month_start(t), _month_add(t, 1)),
        "current_quarter": lambda t: DateRange(_quarter_start(t), _month_add(_quarter_start(t), 3)),
        "current_year": lambda t: DateRange(date(t.year, 1, 1), date(t.year + 1, 1, 1)),
        "last_week": lambda t: DateRange(
            _week_start(t) - timedelta(days=7), _week_start(t)
        ),
        "week_before_last": lambda t: DateRange(
            _week_start(t) - timedelta(days=14), _week_start(t) - timedelta(days=7)
        ),
        "last_month": lambda t: DateRange(_month_add(t, -1), _month_start(t)),
        "last_quarter": lambda t: DateRange(
            _month_add(_quarter_start(t), -3), _quarter_start(t)
        ),
        "last_7d": lambda t: DateRange(t - timedelta(days=7), t),
        "last_14d": lambda t: DateRange(t - timedelta(days=14), t),
        "last_30d": lambda t: DateRange(t - timedelta(days=30), t),
        "last_3m": lambda t: DateRange(_month_add(t, -3), t),
        "same_period_last_year": lambda t: DateRange(
            date(t.year - 1, t.month, 1), date(t.year - 1, t.month, 1) + timedelta(days=calendar.monthrange(t.year - 1, t.month)[1])
        ),
        "all_time": lambda t: DateRange(date(2000, 1, 1), date(t.year + 1, 1, 1)),
    }
    if slot in matchers:
        return matchers[slot](today)
    raise ValueError(f"无法解析的时间槽位: {slot} (合法槽位: {TIME_SLOTS})")


def expand_time(
    slot: str,
    today: date,
    explicit_range: list[str] | None = None,
    granularity: str | None = None,
) -> ExpandedTime:
    """Expand a planner time slot; yoy/mom yield base(本月) + compare range."""
    if slot == "explicit":
        if not explicit_range or len(explicit_range) != 2:
            raise ValueError("explicit 槽位必须提供 explicit_range=[start, end)")
        # explicit_range 约定为 [start, end_exclusive)
        return ExpandedTime(
            base=DateRange(date.fromisoformat(explicit_range[0]), date.fromisoformat(explicit_range[1])),
            granularity=granularity,
        )
    if slot == "yoy":
        base = DateRange(_month_start(today), _month_add(today, 1))
        compare = DateRange(_month_start(today.replace(year=today.year - 1)), _month_add(today.replace(year=today.year - 1), 1))
        return ExpandedTime(base=base, compare=compare)
    if slot == "mom":
        base = DateRange(_month_start(today), _month_add(today, 1))
        compare = DateRange(_month_add(today, -1), _month_start(today))
        return ExpandedTime(base=base, compare=compare)
    return ExpandedTime(base=_expand_base(slot, today), granularity=granularity)
