"""应答组装(FR-A2/D2):AnswerCard 口径五要素 + MissResponse + 信封内数据载荷。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnswerCard:
    """query 成功的答案卡:数据 + 角色 + 指标元数据(五要素)+ 图表推荐。"""

    type: str = "answer"
    rows: tuple[dict[str, Any], ...] = ()
    columns: tuple[str, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    metric: dict[str, Any] = field(default_factory=dict)
    cube_query: dict[str, Any] | None = None
    chart_options: tuple[dict[str, str], ...] = ()
    message: str = ""


@dataclass(frozen=True)
class ReportPayload:
    """报表载荷(chart_select 轮):与工作流 report_json 结构对齐。"""

    type: str = "report"
    question: str = ""
    summary: str = ""
    chart: dict[str, Any] = field(default_factory=dict)
    insight: dict[str, Any] = field(default_factory=dict)
    message: str = ""


@dataclass(frozen=True)
class ClarifyPayload:
    """分步澄清载荷(模板生成,PRD §5.2 Clarification)。"""

    type: str = "clarification"
    clarify_step: str = ""
    options: tuple[str, ...] = ()
    template_id: str = ""
    question_text: str = ""


@dataclass(frozen=True)
class MissPayload:
    """未命中载荷:明确回复 + 可查指标清单 + 候选 id(FR-D2)。"""

    type: str = "miss"
    message: str = ""
    available_metrics: tuple[str, ...] = ()
    candidate_id: str = ""


@dataclass(frozen=True)
class ReplyPayload:
    """旁路普通对话载荷(FR-A4)与系统提示。"""

    type: str = "reply"
    text: str = ""


@dataclass(frozen=True)
class ErrorPayload:
    """执行/系统失败载荷:明确解释,绝不返回空结果或未经验证的数据(FR-A5)。"""

    type: str = "error"
    message: str = ""
    rows: tuple[dict[str, Any], ...] = ()


METRIC_META_KEYS = ("name", "definition", "owner", "version", "freshness")


def build_metric_metadata(
    measures: list[str] | tuple[str, ...],
    mdl: dict,
    meta_provider: Callable[[str], dict] | None = None,
) -> dict[str, Any]:
    """组装 FR-A2 口径五要素:name/definition/owner/version/freshness。

    definition 来自 MDL 描述;owner/version 来自门禁配置 meta(治理平台对接后替换);
    freshness M1 框架占位(None),M5 接数据源元数据。
    """
    name = measures[0] if measures else ""
    definition = ""
    for cube in mdl.get("cubes") or []:
        for m in cube.get("measures") or []:
            if m["name"] == name:
                definition = (m.get("properties") or {}).get("description", "")
    meta = meta_provider(name) if meta_provider else {}
    return {
        "name": name,
        "definition": definition,
        "owner": meta.get("owner"),
        "version": meta.get("version"),
        "freshness": meta.get("freshness"),
    }
