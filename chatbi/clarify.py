"""分步澄清引擎(FR-B1/B2/B4)。

纪律:澄清文案 100% 由规则模板生成,同输入同文案(快照可测);LLM 只负责识别歧义。
分步:一次只问一类缺口,顺序 口径(tax) → 时间(time) → 维度值(dimension)。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

TAX_OPTIONS = ("不含税(营收)", "含税")
TIME_OPTIONS = ("上个月", "本月", "近30天", "全部时间")
STEP_ORDER = ("tax", "time", "dimension")


class ClarifyStep:
    """澄清步骤标识(字符串常量,保持模板 id 稳定)。"""

    TAX = "tax"
    TIME = "time"
    DIMENSION = "dimension"


@dataclass(frozen=True)
class Clarification:
    """一次澄清的渲染结果(template_id + 文案 + 选项,可快照)。"""

    step: str
    template_id: str
    question_text: str
    options: tuple[str, ...] = ()


def render_clarification(
    step: str,
    question: str,
    restated: str,
    dimension: str = "",
    invalid_value: str = "",
    enum_values: list[str] | None = None,
) -> Clarification:
    """按步骤渲染澄清文案(规则模板,无 LLM 参与)。"""
    if step == ClarifyStep.TAX:
        return Clarification(
            step=step,
            template_id="clarify_tax",
            question_text=f"{restated}:「销售额」存在口径歧义,您要查含税还是不含税?",
            options=TAX_OPTIONS,
        )
    if step == ClarifyStep.TIME:
        return Clarification(
            step=step,
            template_id="clarify_time",
            question_text=f"{restated}:请确认统计时间范围",
            options=TIME_OPTIONS,
        )
    if step == ClarifyStep.DIMENSION:
        enums = tuple(enum_values or ())
        return Clarification(
            step=step,
            template_id="clarify_dimension",
            question_text=(
                f"{restated}:「{invalid_value}」不在维度「{dimension}」的可选值中,请选择"
            ),
            options=enums,
        )
    raise ValueError(f"未知澄清步骤: {step}")


def next_step(step: str) -> str | None:
    """分步顺序中的下一步;最后一步返回 None。"""
    order = list(STEP_ORDER)
    if step not in order:
        return None
    idx = order.index(step)
    if idx + 1 >= len(order):
        return None
    return order[idx + 1]


def normalize_dimension_value(value: str) -> str:
    """FR-B4 归一化:去首尾空白 + 全角转半角(NFKC)。归一化后仍不匹配才澄清。"""
    normalized = unicodedata.normalize("NFKC", value).strip()
    return normalized
