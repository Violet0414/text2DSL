"""分步澄清引擎测试(FR-B1/B2/B4):先口径后时间、模板同输入同文案、枚举归一化。"""

from __future__ import annotations

from chatbi.clarify import (
    STEP_ORDER,
    ClarifyStep,
    normalize_dimension_value,
    render_clarification,
)

ENUM_VALUES = ["华东", "华南", "华北", "西南", "东北"]


def test_step_order_is_tax_then_time_then_dimension():
    # FR-B1:一次只问一类缺口;口径歧义先问口径,再问时间
    assert STEP_ORDER == ("tax", "time", "dimension")


def test_tax_clarification_snapshot_stable():
    # FR-B2:模板同输入同文案
    kwargs = {"question": "本月销售额", "restated": "查询「销售额」"}
    a = render_clarification(step="tax", **kwargs)
    b = render_clarification(step="tax", **kwargs)
    assert a == b
    assert a.template_id == "clarify_tax"
    assert a.options == ("不含税(营收)", "含税")
    assert a.step == ClarifyStep.TAX


def test_time_clarification_offers_fixed_time_options():
    c = render_clarification(step="time", question="销售额", restated="查询「销售额」")
    assert c.template_id == "clarify_time"
    assert c.options == ("上个月", "本月", "近30天", "全部时间")


def test_dimension_clarification_lists_enum_options():
    c = render_clarification(
        step="dimension",
        question="营收按大区分布",
        restated="查询「营收」按「大区」分布",
        dimension="region",
        invalid_value="华南区",
        enum_values=ENUM_VALUES,
    )
    assert c.template_id == "clarify_dimension"
    assert c.options == tuple(ENUM_VALUES)
    assert "华南区" in c.question_text
    assert "华南" in c.options
    # FR-B1:选项不出现口径×时间笛卡尔积
    assert len(c.options) == 5


def test_normalize_dimension_value_strips_fullwidth_and_space():
    # FR-B4:归一化后仍无法匹配才澄清
    assert normalize_dimension_value(" 华东 ") == "华东"
    assert (
        normalize_dimension_value("华东区") == "华东区"
    )  # 后缀不自动剥(由归一化映射处理)


def test_normalize_dimension_value_fullwidth_to_halfwidth():
    assert normalize_dimension_value("ＥＡstelle") == "EAstelle"


def test_clarification_is_frozen():
    c = render_clarification(step="time", question="q", restated="r")
    try:
        c.options = ("x",)
    except Exception:  # noqa: BLE001
        return
    raise AssertionError("Clarification 应为 frozen dataclass")


def test_next_step_follows_tax_time_dimension():
    from chatbi.clarify import next_step

    assert next_step("tax") == "time"
    assert next_step("time") == "dimension"
    assert next_step("dimension") is None
