"""时间缺省规则(FR-B3,固化 PoC 偏差记录2):裸指标无修饰→澄清时间;带维度/筛选/对比→默认全部时间;K3 继承优先。

纯函数,LLM 不参与时间决策(不靠 LLM 自觉)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from chatbi.planner.time_expand import ExpandedTime, expand_time

TODAY = date(2026, 11, 16)  # PoC 冻结日,评测可复现


@dataclass(frozen=True)
class TimeDecision:
    """时间缺省规则决策结果。"""

    action: str  # inherit / expand / all_time / clarify
    time_dimensions: tuple[dict[str, Any], ...] = ()
    expanded: ExpandedTime | None = None


def resolve_time(
    time_spec: dict[str, Any] | None,
    has_dimensions: bool,
    has_filters: bool,
    prev_td: list[dict[str, Any]] | None = None,
    today: date = TODAY,
) -> TimeDecision:
    """确定性时间决策:继承 > 显式槽位展开 > 缺省规则 > 澄清。

    FR-B3:裸指标无修饰→澄清时间;带维度/筛选/对比→默认全部时间;K3 继承优先。
    """
    slot = (time_spec or {}).get("slot")
    if slot is None and prev_td:
        return TimeDecision(action="inherit", time_dimensions=tuple(prev_td))
    if slot is not None:
        if slot == "explicit" and not (time_spec or {}).get("explicit_range"):
            return TimeDecision(action="clarify")
        expanded = expand_time(
            slot,
            today,
            (time_spec or {}).get("explicit_range"),
            (time_spec or {}).get("granularity"),
        )
        return TimeDecision(
            action="expand", time_dimensions=_tds_from(expanded), expanded=expanded
        )
    if has_dimensions or has_filters:
        return _all_time_decision(today)
    return TimeDecision(action="clarify")


def _tds_from(expanded: ExpandedTime) -> tuple[dict[str, Any], ...]:
    """ExpandedTime → wren timeDimensions 元组(半开区间,granularity 缺省 month)。"""
    tds = []
    ranges = [expanded.base.to_strings()]
    if expanded.compare is not None:
        ranges.append(expanded.compare.to_strings())
    for r in ranges:
        tds.append(
            {
                "dimension": "__time__",
                "dateRange": r,
                "granularity": expanded.granularity or "month",
            }
        )
    return tuple(tds)


def _all_time_decision(today: date) -> TimeDecision:
    """FR-B3 缺省:带维度/筛选的泛问句默认"全部时间"(all_time 槽位确定性展开)。"""
    expanded = expand_time("all_time", today)
    return TimeDecision(
        action="all_time", time_dimensions=_tds_from(expanded), expanded=expanded
    )
