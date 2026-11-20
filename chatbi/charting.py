"""图表推荐与 ECharts option 组装(移植自民政数据报表工作流,确定性无 LLM)。

推荐权重表 V0.1(与工作流 13-特征提取与图表推荐节点逐项一致;调整分值以权重表为准,
后续可迁移到后端配置表)。图表 option 拼装镜像工作流 3-组装所选图表节点。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

BASELINE = {"bar": 10, "line": 10, "pie": 10}
FACTOR_WEIGHTS = {
    "F1": {"bar": 10, "line": 40, "pie": -10},
    "F2": {"bar": 12, "line": 0, "pie": 20},
    "F3": {"bar": 22, "line": 0, "pie": 8},
    "F4": {"bar": 18, "line": -5, "pie": -25},
    "F5": {"bar": 0, "line": 0, "pie": 25},
    "F6": {"bar": 20, "line": 0, "pie": -30},
    "F7": {"bar": 15, "line": -10, "pie": -20},
    "F8": {"bar": 5, "line": -10, "pie": 35},
    "F9": {"bar": 5, "line": 35, "pie": -10},
    "F10": {"bar": 30, "line": 0, "pie": -10},
}
CHART_LABELS = {"bar": "柱状图", "line": "折线图", "pie": "饼图"}
CHART_PURPOSE = {"bar": "适合对比量级", "line": "适合呈现趋势", "pie": "适合展示构成"}
TIE_GAP = 5
TIE_PRIORITY = {"bar": 0, "line": 1, "pie": 2}
EXCLUDED = -999
PIE_MAX_CATEGORIES = 12

CHART_TYPES = ("bar", "line", "pie")
MAX_ROWS_IN_CHART = 15
MAX_ROWS_IN_PIE = 8

# 时间样式值:2026 / 2026-10 / 2026年10月 / 2026Q1 / 2026年第1季度
TIME_PAT = re.compile(
    r"^\d{4}([\-/.]\d{1,2}){0,2}$|^\d{4}年(\d{1,2}月(\d{1,2}日)?)?$"
    r"|^\d{4}(年)?[Qq][1-4]$|^\d{4}年第?[1-4]季度$"
)
KEYWORD_MAP = {
    "F8": ["占比", "比例", "构成", "分布", "结构", "份额"],
    "F9": ["趋势", "变化", "增长", "同比", "环比", "逐年", "走势"],
    "F10": ["对比", "分别", "排行", "排名", "top", "前几", "前3", "前10", "多少"],
}
# 用户点名图表类型(如「用饼图展示」);英文别名按词边界,「路线图」不误命中线图
CHART_ALIAS = {
    "bar": ["柱状", "柱图", "条形图", "直方图", "bar"],
    "line": ["折线", "线图", "line"],
    "pie": ["饼图", "饼状", "pie"],
}


@dataclass(frozen=True)
class ChartOption:
    """一条图表推荐:类型 + 中文标签 + 用途说明 + 得分(调试用)。"""

    type: str
    label: str
    purpose: str
    score: int = 0


def detect_user_chart(question: str) -> str:
    """取问句中最早出现的图表类型词;用户点名优先于任何特征得分。"""
    ql = (question or "").lower()
    q2 = re.sub(r"\s+", "", ql)
    best = ""
    pos = None
    for chart_type, aliases in CHART_ALIAS.items():
        for alias in aliases:
            if alias.isascii():
                match = re.search(r"\b" + alias + r"\b", ql)
            elif alias == "线图":
                match = re.search(r"(?<!路)线图", q2)
            else:
                match = re.search(re.escape(alias), q2)
            if match and (pos is None or match.start() < pos):
                pos = match.start()
                best = chart_type
    return best


def to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _cell(row: Any, column: str) -> Any:
    return row.get(column) if isinstance(row, dict) else None


def detect_numeric_columns(
    rows: tuple[dict[str, Any], ...], columns: tuple[str, ...]
) -> list[str]:
    """前 10 行采样判定数值列:可解析值占非空值过半即视为数值(容忍个别脏值)。"""
    flags = []
    for column in columns:
        non_null = 0
        parsed = 0
        for row in rows[:10]:
            value = _cell(row, column)
            if value is None or str(value).strip() == "":
                continue
            non_null += 1
            if to_float(value) is not None:
                parsed += 1
        flags.append(non_null > 0 and parsed * 2 >= non_null)
    return [c for i, c in enumerate(columns) if flags[i]]


def _detect_time_dimension(
    rows: tuple[dict[str, Any], ...], columns: tuple[str, ...]
) -> bool:
    for column in columns:
        for row in rows[:20]:
            value = str(_cell(row, column) or "").strip()
            if value and TIME_PAT.match(value):
                return True
    return False


def _semantic_hits(question: str) -> set[str]:
    ql = (question or "").lower()
    return {fid for fid, words in KEYWORD_MAP.items() if any(w in ql for w in words)}


def recommend_charts(
    question: str,
    rows: tuple[dict[str, Any], ...],
    columns: tuple[str, ...],
) -> tuple[ChartOption, ...]:
    """按权重表对三种图表打分,返回降序推荐(含用户点名优先与饼图排除)。"""
    rows = rows or ()
    columns = tuple(columns or ())
    numeric_cols = detect_numeric_columns(rows, columns)
    category_count = len(rows)
    has_time = _detect_time_dimension(rows, columns)
    hits = _semantic_hits(question)

    def _category_factor(fid: str) -> bool:
        if fid == "F2":
            return 3 <= category_count <= 6
        if fid == "F3":
            return 7 <= category_count <= 12
        if fid == "F4":
            return category_count > 12
        return False

    active_factors: list[str] = []
    if has_time:
        active_factors.append("F1")
    active_factors.extend(fid for fid in ("F2", "F3", "F4") if _category_factor(fid))
    if len(numeric_cols) == 1:
        active_factors.append("F5")
    non_numeric = [c for c in columns if c not in numeric_cols]
    if len(non_numeric) >= 2:
        active_factors.append("F6")
    if len(numeric_cols) >= 2:
        active_factors.append("F7")
    active_factors.extend(sorted(hits))

    scores = dict(BASELINE)
    for fid in active_factors:
        for chart_type in CHART_TYPES:
            scores[chart_type] += FACTOR_WEIGHTS[fid][chart_type]

    # 饼图排除纪律:类别数超上限(工作流 EXCLUDED 常量语义)
    if category_count > PIE_MAX_CATEGORIES:
        scores["pie"] = EXCLUDED

    named = detect_user_chart(question)
    if named:
        scores[named] += 1000

    ordered = sorted(CHART_TYPES, key=lambda ct: (-scores[ct], TIE_PRIORITY[ct]))
    return tuple(
        ChartOption(
            type=ct,
            label=CHART_LABELS[ct],
            purpose=CHART_PURPOSE[ct],
            score=scores[ct],
        )
        for ct in ordered
        if scores[ct] > EXCLUDED
    )


def build_chart_option(
    rows: tuple[dict[str, Any], ...],
    columns: tuple[str, ...],
    chart_type: str,
    question: str,
) -> dict[str, Any] | None:
    """由查询结果拼装 ECharts option;无数值列时返回 None(无法绘图)。"""
    if chart_type not in CHART_TYPES:
        chart_type = "bar"
    rows = rows or ()
    columns = tuple(columns or ())
    numeric_cols = detect_numeric_columns(rows, columns)
    if not columns or not numeric_cols:
        return None

    cat_col = columns[0]
    cats = [str(_cell(row, cat_col) or "-") for row in rows[:MAX_ROWS_IN_CHART]]

    if chart_type == "pie":
        val_col = numeric_cols[0]
        data = []
        for row in rows[:MAX_ROWS_IN_PIE]:
            value = to_float(_cell(row, val_col))
            data.append(
                {
                    "name": str(_cell(row, cat_col) or "-"),
                    "value": value if value is not None else 0,
                }
            )
        return {
            "title": {"text": (question or "")[:40], "left": "center"},
            "tooltip": {"trigger": "item"},
            "legend": {"orient": "vertical", "left": "left"},
            "series": [{"name": val_col, "type": "pie", "radius": "60%", "data": data}],
        }

    series = []
    for val_col in numeric_cols:
        data = []
        for row in rows[:MAX_ROWS_IN_CHART]:
            value = to_float(_cell(row, val_col))
            data.append(value if value is not None else 0)
        series.append({"name": val_col, "type": chart_type, "data": data})
    return {
        "title": {"text": (question or "")[:40], "left": "center"},
        "tooltip": {"trigger": "axis"},
        "legend": {},
        "xAxis": {"type": "category", "data": cats},
        "yAxis": {"type": "value"},
        "series": series,
    }
