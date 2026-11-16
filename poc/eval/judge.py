"""逐条判定:期望标注 vs 规划器实际输出(工具选择/参数/行为三维)。"""

from __future__ import annotations

from datetime import date
from typing import Any

from planner.time_expand import expand_time

TODAY = date(2026, 11, 16)

# 口径歧义/缺参澄清中,期望选项必须覆盖的关键词
TAX_KEYWORDS = ("含税", "不含税")
TIME_OPTION_KEYWORDS = ("月", "周", "天", "年", "时间")


def _actual_ranges(cq: dict[str, Any] | None) -> list[list[str]]:
    """Extract dateRange list(s) from a wren cube query."""
    if not cq:
        return []
    return [td.get("dateRange") for td in cq.get("timeDimensions") or [] if td.get("dateRange")]


def _range_matches(
    expected_slot: str,
    actual_cq: dict[str, Any] | None,
    explicit_range: list[str] | None = None,
) -> bool:
    """Compare actual dateRange(s) against the deterministic expansion of the
    expected slot (comparison slots need both base and compare ranges)."""
    if expected_slot == "explicit" and explicit_range:
        return _actual_ranges(actual_cq) == [explicit_range]
    expected = expand_time(expected_slot, TODAY) if expected_slot else None
    actual = _actual_ranges(actual_cq)
    if expected is None:
        return not actual
    expected_ranges = [expected.base.to_strings()]
    if expected.compare is not None:
        expected_ranges.append(expected.compare.to_strings())
    return actual == expected_ranges


def _dim_in_query(dim: str, cq: dict[str, Any]) -> bool:
    """True when a plain dimension is grouped or value-filtered in the query."""
    if dim in (cq.get("dimensions") or []):
        return True
    for f in cq.get("filters") or []:
        if f.get("dimension") == dim:
            return True
    return False


def _filter_matches(spec: str, cq: dict[str, Any]) -> bool:
    """expected filter spec 形如 'order_status=已完成' 或 'region in [华东,华北]'."""
    if " in " in spec:
        dim, values_part = spec.split(" in ", 1)
        values = [v.strip() for v in values_part.strip("[]").split(",")]
        for f in cq.get("filters") or []:
            if f.get("dimension") == dim.strip() and f.get("operator") == "in":
                got = f.get("value")
                got = got if isinstance(got, list) else [got]
                if set(got) == set(values):
                    return True
        return False
    dim, _, value = spec.partition("=")
    for f in cq.get("filters") or []:
        if f.get("dimension") == dim and str(f.get("value")) == value:
            return True
    return False


def judge_params(expected: dict[str, Any], cq: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """Judge slot-level parameter accuracy. Returns (all_ok, failed_slot_names)."""
    failures: list[str] = []
    if cq is None:
        return False, ["cube_query_missing"]

    got_measures = set(cq.get("measures") or [])
    want_measures = set(expected.get("metric") or [])
    # 澄清行为不判参数;query 行为下期望 metric 必须与实际完全一致
    if got_measures != want_measures:
        failures.append("metric")

    got_dims = {d for d in (cq.get("dimensions") or [])}
    want_dims = set()
    for d in expected.get("dimensions") or []:
        if "=" in d:
            continue  # 带值维度按 filter 判
        want_dims.add(d)
    if got_dims != want_dims:
        failures.append("dimensions")

    for f in expected.get("dimensions") or []:
        if "=" in f and not _filter_matches(f, cq):
            failures.append(f"filter:{f}")
    for f in expected.get("filters") or []:
        if not _filter_matches(f, cq):
            failures.append(f"filter:{f}")

    want_time = expected.get("time")
    if want_time:
        if isinstance(want_time, str):
            time_ok = _range_matches(want_time, cq)
        else:
            # 黄金集标注 {gte, lte} 为闭区间;换算为半开区间后直接比对
            explicit = [want_time["gte"], _gte_plus_one(want_time["lte"])]
            time_ok = _range_matches("explicit", cq, explicit_range=explicit)
        if not time_ok:
            failures.append("time")

    if expected.get("topN"):
        if (cq.get("limit") != expected["topN"]) or not any(
            o.get("member") in want_measures and o.get("direction") == "desc"
            for o in cq.get("orderBy") or []
        ):
            failures.append("topN")

    if expected.get("granularity"):
        got_g = [td.get("granularity") for td in cq.get("timeDimensions") or []]
        if expected["granularity"] not in got_g:
            failures.append("granularity")

    return not failures, failures


def _gte_plus_one(lte: str) -> str:
    """Convert an inclusive golden-set end date into the half-open bound."""
    from datetime import timedelta

    return (date.fromisoformat(lte) + timedelta(days=1)).isoformat()


def judge_clarify_options(expected: dict[str, Any], options: tuple[str, ...]) -> bool:
    """Mechanical option-quality check: 口径歧义需覆盖含税/不含税;缺参需给时间选项."""
    text = " | ".join(options)
    if "clarify_options" in expected:
        return all(k in text for k in TAX_KEYWORDS)
    if expected.get("missing_slots") == ["time"]:
        return bool(options) and any(k in text for k in TIME_OPTION_KEYWORDS)
    return bool(options)


def judge_item(expected: dict[str, Any], result) -> dict[str, Any]:
    """Judge one question. result is a planner.core.PlanResult."""
    want = expected["behavior"]
    got = result.behavior
    verdict: dict[str, Any] = {
        "behavior_ok": got == want,
        "tool_ok": None,
        "params_ok": None,
        "param_failures": [],
        "clarify_options_ok": None,
    }

    if want == "query":
        if got == "query" and result.cube_query:
            got_measures = set(result.cube_query.get("measures") or [])
            want_measures = set(expected.get("metric") or [])
            verdict["tool_ok"] = got_measures == want_measures
        else:
            verdict["tool_ok"] = False
        if got == "query" and result.cube_query:
            ok, failures = judge_params(expected, result.cube_query)
            verdict["params_ok"] = ok
            verdict["param_failures"] = failures
        else:
            verdict["params_ok"] = False
    elif want == "clarify":
        verdict["clarify_options_ok"] = judge_clarify_options(expected, result.clarify_options) if got == "clarify" else None
    elif want == "miss":
        verdict["tool_ok"] = got == "miss"
    elif want == "chitchat":
        verdict["tool_ok"] = got == "chitchat"

    # 幻觉拦截(K1):未注册成员若进入编译,validation 字段应非 passed
    verdict["hallucination_blocked"] = (
        result.validation != "passed" or got != "query"
    ) if got == "query" and result.validation == "intercepted" else None

    verdict["all_ok"] = (
        verdict["behavior_ok"]
        and verdict["tool_ok"] is not False
        and verdict["params_ok"] is not False
        and verdict["clarify_options_ok"] is not False
    )
    return verdict


def attribute_failure(expected: dict[str, Any], result) -> str:
    """失败归因分类(评测方案 §四)。"""
    want, got = expected["behavior"], result.behavior
    if got == "error":
        return "底座编译错误" if result.validation and "intercepted" in result.validation else "意图误判"
    if want == "query" and got == "clarify":
        return "澄清缺失"
    if want == "query" and got == "miss":
        return "检索未召回"
    if want in ("miss", "chitchat") and got == "query":
        return "意图误判"
    if want == "clarify" and got == "query":
        return "澄清缺失"
    if want == "query" and got == "query":
        return "参数填错"
    return "意图误判"
