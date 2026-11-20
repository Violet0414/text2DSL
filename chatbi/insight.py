"""AI 解读模块(镜像民政数据报表工作流 5-AI解读 + 16-自然语言描述,合并单次调用)。

输出三段:summary(自然语言描述)/ core_data(核心数据结论)/ trend_analysis
(趋势或构成分析)。硬性纪律与工作流一致:只依据给定数据,严禁编造数据中
不存在的合计值、同比/环比、增长率。解析失败重试 1 次,仍失败优雅降级
(ok=False),由调用方决定图表照常返回。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from chatbi.planner.llm import LlmClient, parse_json_loose

MAX_PREVIEW_ROWS = 20

SYSTEM_PROMPT = """你是数据报表的解读模块。基于给出的数据和统计特征,输出一个 JSON 对象,包含三部分:

1. summary: 自然语言数据描述——以"根据…统计,"开头点明统计口径(口径表述来自用户问题或字段名,不要编造数据源名称);逐项列出数据点(格式如"昆明市 985 个、曲靖市 672 个");结尾汇总句:共N项,若指标可加总给出合计值,指出最大项与最小项;仅当数据确实包含同比基数或对比数据时才可写增长/下降结论及幅度。

2. core_data: 核心数据——用1~3条列出最关键的数字结论(总量、最大/最小项及其具体数值)。

3. trend_analysis: 趋势分析——若数据含时间维度,分析随时间的变化趋势与拐点(增长/下降/波动及幅度);若数据无时间维度,则分析类别间的差异规律(量级对比、构成集中度)。

硬性要求:
- 只输出一个 JSON 对象: {"summary": "...", "core_data": "...", "trend_analysis": "..."},不要输出任何其他文字或 markdown 代码块
- 只依据给出的数据,严禁编造数据中不存在的合计值、全省总数、同比/环比、增长率
- 若数据为空,直接说明未查询到数据并建议调整筛选条件
"""


@dataclass(frozen=True)
class InsightResult:
    """解读结果快照:ok=False 时字段为空,调用方降级为无解读的图表。"""

    ok: bool = False
    summary: str = ""
    core_data: str = ""
    trend_analysis: str = ""
    error: str | None = None


def _build_user_prompt(
    question: str, rows: tuple[dict[str, Any], ...], columns: tuple[str, ...]
) -> str:
    lines = [f"用户问题: {question}", "数据明细(最多20行):"]
    for row in rows[:MAX_PREVIEW_ROWS]:
        lines.append("; ".join(f"{c}={row.get(c, '-')}" for c in columns))
    return "\n".join(lines)


def build_insight(
    question: str,
    rows: tuple[dict[str, Any], ...],
    columns: tuple[str, ...],
    llm: LlmClient,
) -> InsightResult:
    """单次 LLM 产出三段解读;解析失败重试 1 次(FR-A5 纪律),仍失败优雅降级。"""
    rows = rows or ()
    columns = tuple(columns or ())
    user_prompt = _build_user_prompt(question, rows, columns)
    messages = [{"role": "user", "content": user_prompt}]
    last_error = "unknown"
    for _attempt in (1, 2):
        call = llm.call(SYSTEM_PROMPT, messages, None)
        if call.error:
            last_error = call.error
            continue
        # 剥掉 <think> 思考轨迹(镜像工作流组装节点的 re.sub 纪律)
        text = re.sub(
            r"<think>.*?</think>", "", call.output_text, flags=re.DOTALL
        ).strip()
        parsed = parse_json_loose(text)
        if parsed and parsed.get("core_data") is not None:
            return InsightResult(
                ok=True,
                summary=str(parsed.get("summary", "")),
                core_data=str(parsed.get("core_data", "")),
                trend_analysis=str(parsed.get("trend_analysis", "")),
            )
        last_error = f"unparseable insight output: {call.output_text[:200]}"
    return InsightResult(ok=False, error=last_error)
