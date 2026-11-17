"""受控问数规划器核心:NL → 行为分支 + cube query 结构化参数(K1/K2/K3)。

三层防线:
  主防线  JSON Schema 枚举(planner/schema.py,由 mdl.json 生成)
  次防线  wren_core.cube_query_to_sql 编译校验(MDL 级,ValueError 即拦截)
  兜底    校验失败自动修复一次(错误回喂),仍失败则降级为澄清分支
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from wren_core import cube_query_to_sql

from chatbi.config import DEFAULT_WREN_PROJECT_DIR
from chatbi.planner.llm import (
    AnthropicLlmClient,
    LlmClient,
    LlmConfig,
    parse_json_loose,
)
from chatbi.planner.schema import (
    BEHAVIORS,
    cube_members,
    load_mdl,
    planner_tool_schema,
)
from chatbi.planner.time_expand import expand_time

PROJECT_DIR = Path(
    os.environ.get("CHATBI_WREN_PROJECT_DIR", str(DEFAULT_WREN_PROJECT_DIR))
)
MDL_PATH = PROJECT_DIR / "target" / "mdl.json"
RULES_DIR = PROJECT_DIR / "knowledge" / "rules"

TODAY = date(2026, 11, 16)  # PoC 冻结日期,评测可复现

_DEFAULT_LLM_CLIENT: LlmClient | None = None


def get_default_llm_client() -> LlmClient:
    """进程级默认 LLM 客户端(懒构造;appkey 未配置时抛 LlmConfigError)。"""
    global _DEFAULT_LLM_CLIENT
    if _DEFAULT_LLM_CLIENT is None:
        _DEFAULT_LLM_CLIENT = AnthropicLlmClient(LlmConfig.from_env())
    return _DEFAULT_LLM_CLIENT


def reset_default_llm_client() -> None:
    """清空默认客户端单例(测试/换模型热切换用)。"""
    global _DEFAULT_LLM_CLIENT
    _DEFAULT_LLM_CLIENT = None


@dataclass(frozen=True)
class PlanResult:
    """规划器单次输出快照(判定与落盘单位)。"""

    question: str
    behavior: str
    cube_query: dict[str, Any] | None = None
    cube_queries: tuple[dict[str, Any], ...] = ()  # yoy/mom 展开为 base+compare
    generated_sql: str | None = None
    clarify_question: str | None = None
    clarify_options: tuple[str, ...] = ()
    reply: str | None = None
    validation: str = "skipped"  # passed / intercepted / repaired / skipped
    llm_latency_ms: int = 0
    llm_error: str | None = None
    raw_output: str = ""


def load_rules() -> str:
    """Concatenate knowledge/rules/*.md as the planner's business rules."""
    parts = []
    for f in sorted(RULES_DIR.glob("*.md")):
        parts.append(f"## 规则文件: {f.name}\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def cube_catalog_text(mdl: dict[str, Any]) -> str:
    """Render cube members + descriptions for the system prompt."""
    lines = []
    for cube in mdl.get("cubes") or []:
        lines.append(
            f"### cube: {cube['name']} — {cube.get('properties', {}).get('description', '')}"
        )
        for m in cube.get("measures") or []:
            desc = m.get("properties", {}).get("description", "")
            lines.append(f"- measure `{m['name']}`: {desc}")
        for d in cube.get("dimensions") or []:
            desc = d.get("properties", {}).get("description", "")
            lines.append(f"- dimension `{d['name']}`: {desc}")
        for t in cube.get("timeDimensions") or []:
            lines.append(
                f"- time_dimension `{t['name']}`: 时间粒度在 time.slot/granularity 中指定"
            )
    return "\n".join(lines)


def build_system_prompt(mdl: dict[str, Any]) -> str:
    """Assemble the planner system prompt: rules + catalog + date + protocol."""
    return f"""你是受控问数系统的规划器。将用户问题规划为以下四种行为之一:

1. **query**:信息充分,输出 cube_query。
2. **clarify**:缺参数或口径歧义,输出 clarify_question + clarify_options(选项须可操作)。
3. **miss**:询问的指标或维度未在下方指标清单中注册,**不得编造**,输出 reply 说明并列出可查指标。
4. **chitchat**:非问数意图(寒暄/建指标/天气等),输出 reply 旁路引导。

## 业务规则(必须遵守)

{load_rules()}

## 受控指标清单(唯一合法出口)

{cube_catalog_text(mdl)}

## 时间处理

- 今天是 {TODAY.isoformat()}。相对时间表达输出 time.slot(枚举),由系统确定性展开,不要自己算日期。
- 用户给出明确日期区间时用 slot=explicit + explicit_range=[start, end),end 为**开区间**。
- yoy/mom 槽位表示同比/环比对比,系统会自动展开为当期+对比期两次查询。

## 多轮上下文

- 对话历史中附带上一轮的规划结果 JSON。当前问题未提及的槽位**继承**上一轮
  cube_query 的同位置参数;当前问题显式提及的槽位**覆盖**上一轮。
- 追问"XX呢/改成XX"类问题时,优先做槽位替换而非重新规划。

## 输出

严格按 plan 工具的 JSON Schema 输出。behavior=query 时 cube_query 必填;
behavior=clarify/miss/chitchat 时 cube_query 必须省略。
"""


def _to_wren_cube_query(
    cq: dict[str, Any],
    members: dict[str, dict[str, list[str]]],
    prev_cube_query: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Normalize LLM output into a wren CubeQuery dict (time slot expanded)."""
    cube_name = cq.get("cube")
    if cube_name not in members:
        return None
    wren_cq: dict[str, Any] = {
        "cube": cube_name,
        "measures": list(cq.get("measures") or []),
    }
    if cq.get("dimensions"):
        wren_cq["dimensions"] = list(cq["dimensions"])

    time_spec = cq.get("time") or {}
    slot = time_spec.get("slot")
    time_dimensions = []
    if slot is None and prev_cube_query and prev_cube_query.get("timeDimensions"):
        # K3 确定性槽位继承:追问轮未提时间时,直接继承上一轮 timeDimensions
        time_dimensions = list(prev_cube_query["timeDimensions"])
        ranges = None
        granularity = None
    elif slot is None:
        ranges = []  # 无上一轮可继承,退化为无时间查询
        granularity = None
    elif slot == "explicit":
        ranges = [time_spec.get("explicit_range") or []]
        granularity = time_spec.get("granularity")
    else:
        expanded = expand_time(
            slot, TODAY, time_spec.get("explicit_range"), time_spec.get("granularity")
        )
        ranges = [expanded.base.to_strings()]
        if expanded.compare is not None:
            ranges.append(expanded.compare.to_strings())
        granularity = expanded.granularity
    for r in ranges or []:
        td: dict[str, Any] = {
            "dimension": members[cube_name]["time_dimensions"][0],
            "dateRange": r,
            "granularity": granularity or "month",  # wren-core 必填字段;缺省月粒度
        }
        time_dimensions.append(td)
    wren_cq["timeDimensions"] = time_dimensions

    if cq.get("filters"):
        wren_cq["filters"] = list(cq["filters"])
    if cq.get("orderBy"):
        wren_cq["orderBy"] = list(cq["orderBy"])
    if cq.get("limit"):
        wren_cq["limit"] = cq["limit"]
    return wren_cq


def _validate_and_repair(
    wren_cq: dict[str, Any],
    mdl_json: str,
    members: dict[str, dict[str, list[str]]],
    messages: list[dict[str, Any]],
    system: str,
    llm: LlmClient,
) -> tuple[dict[str, Any] | None, str | None]:
    """K1 次防线:编译校验;失败回喂修复一次。

    Returns (validated_query, status):
      (query, None)        首次校验通过
      (query, "repaired")  修复回喂后通过
      (None, "intercepted: ..." / "repair_failed: ...") 拦截/修复失败
    """
    try:
        cube_query_to_sql(json.dumps(wren_cq, ensure_ascii=False), mdl_json)
        return wren_cq, None
    except Exception as exc:  # noqa: BLE001 — wren-core 抛错类型不固定,统一拦截
        first_error = str(exc)
    repaired = llm.call(
        system,
        messages
        + [
            {
                "role": "user",
                "content": f"你上一次的规划输出 {json.dumps(wren_cq, ensure_ascii=False)} "
                f"编译失败:{first_error}。请按规则修复并重新输出。",
            }
        ],
        _tool_schema_cached(),
    )
    parsed = parse_json_loose(repaired.output_text)
    if parsed and parsed.get("behavior") == "query" and parsed.get("cube_query"):
        fixed = _to_wren_cube_query(parsed["cube_query"], members)
        if fixed is not None:
            try:
                cube_query_to_sql(json.dumps(fixed, ensure_ascii=False), mdl_json)
                return fixed, "repaired"
            except Exception as exc2:  # noqa: BLE001
                return None, f"repair_failed: {exc2}"
    return None, f"intercepted: {first_error}"


_TOOL_SCHEMA_CACHE: dict[str, Any] | None = None


def _tool_schema_cached() -> dict[str, Any]:
    global _TOOL_SCHEMA_CACHE
    if _TOOL_SCHEMA_CACHE is None:
        mdl = load_mdl(MDL_PATH)
        _TOOL_SCHEMA_CACHE = planner_tool_schema(cube_members(mdl))
    return _TOOL_SCHEMA_CACHE


def plan(
    question: str,
    history: list[dict[str, Any]] | None = None,
    llm: LlmClient | None = None,
) -> PlanResult:
    """Plan one question (optionally with multi-turn history) into a PlanResult.

    llm:可注入的 LLM 客户端;缺省用进程级默认客户端(appkey 经环境变量,后期填入)。
    """
    llm = llm or get_default_llm_client()
    mdl = load_mdl(MDL_PATH)
    members = cube_members(mdl)
    mdl_json = json.dumps(mdl, ensure_ascii=False)
    system = build_system_prompt(mdl)

    messages: list[dict[str, Any]] = []
    for turn in history or []:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(turn["result"], ensure_ascii=False),
            }
        )
    messages.append({"role": "user", "content": question})

    call = llm.call(system, messages, _tool_schema_cached())
    parsed = parse_json_loose(call.output_text)
    if call.error or parsed is None:
        return PlanResult(
            question=question,
            behavior="error",
            llm_latency_ms=call.latency_ms,
            llm_error=call.error or "unparseable output",
            raw_output=call.output_text,
        )

    behavior = parsed.get("behavior")
    if behavior not in BEHAVIORS:
        behavior = "error"

    if behavior == "query" and parsed.get("cube_query"):
        prev_cq = None
        for turn in reversed(history or []):
            if turn.get("result", {}).get("cube_query"):
                prev_cq = turn["result"]["cube_query"]
                break
        wren_cq = _to_wren_cube_query(parsed["cube_query"], members, prev_cq)
        if wren_cq is None:
            return PlanResult(
                question=question,
                behavior="error",
                raw_output=json.dumps(parsed, ensure_ascii=False),
            )
        validated, status = _validate_and_repair(
            wren_cq, mdl_json, members, messages, system, llm
        )
        if validated is None:
            return PlanResult(
                question=question,
                behavior="clarify",  # 兜底降级:编译失败不得出数
                clarify_question="查询规划未通过语义校验,请补充或改写问题。",
                validation=status or "intercepted",
                llm_latency_ms=call.latency_ms,
                raw_output=json.dumps(parsed, ensure_ascii=False),
            )
        sql = cube_query_to_sql(json.dumps(validated, ensure_ascii=False), mdl_json)
        return PlanResult(
            question=question,
            behavior="query",
            cube_query=validated,
            generated_sql=sql,
            validation="passed" if status is None else status,
            llm_latency_ms=call.latency_ms,
            raw_output=json.dumps(parsed, ensure_ascii=False),
        )

    return PlanResult(
        question=question,
        behavior=behavior,
        clarify_question=parsed.get("clarify_question"),
        clarify_options=tuple(parsed.get("clarify_options") or ()),
        reply=parsed.get("reply"),
        validation="skipped",
        llm_latency_ms=call.latency_ms,
        raw_output=json.dumps(parsed, ensure_ascii=False),
    )
