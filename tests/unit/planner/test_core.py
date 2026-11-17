"""plan() 行为契约测试:四行为分支 + 三层防线 + K3 槽位继承(FakeLlm 注入,不调真实 LLM)。"""

from __future__ import annotations

import json
from datetime import date

from chatbi.planner.core import PlanResult, plan
from chatbi.planner.llm import LlmCall

TODAY = date(2026, 11, 16)


class FakeLlmClient:
    """LlmClient 协议的可控替身:按序返回预置输出,记录全部调用参数。"""

    def __init__(self, outputs: list[dict | str | LlmCall]):
        self._outputs = list(outputs)
        self.calls: list[dict] = []

    def call(self, system: str, messages: list[dict], tool_schema: dict | None) -> LlmCall:
        self.calls.append({"system": system, "messages": messages, "tool_schema": tool_schema})
        out = self._outputs.pop(0)
        if isinstance(out, LlmCall):
            return out
        if isinstance(out, dict):
            text = json.dumps(out, ensure_ascii=False)
        else:
            text = out
        return LlmCall(model="fake-model", output_text=text, latency_ms=1)

    def assert_no_pending(self) -> None:
        assert not self._outputs, f"FakeLlm 尚有未消费的预置输出: {self._outputs}"


def _query_payload(cube: str = "sales", measures: list[str] | None = None, **time_spec) -> dict:
    payload = {
        "behavior": "query",
        "cube_query": {
            "cube": cube,
            "measures": measures or ["sales_amount"],
        },
    }
    if time_spec:
        payload["cube_query"]["time"] = time_spec
    return payload


# ---------------------------------------------------------------
# 四行为分支
# ---------------------------------------------------------------


def test_query_behavior_produces_validated_cube_query_and_sql():
    fake = FakeLlmClient([_query_payload(slot="last_month")])
    result = plan("上个月营收是多少", llm=fake)

    assert result.behavior == "query"
    assert result.validation == "passed"
    assert result.cube_query is not None
    assert result.cube_query["measures"] == ["sales_amount"]
    assert result.cube_query["timeDimensions"][0]["dateRange"] == ["2026-10-01", "2026-11-01"]
    assert result.cube_query["timeDimensions"][0]["granularity"] == "month"
    assert result.generated_sql and "sales_amount" in result.generated_sql
    fake.assert_no_pending()


def test_clarify_behavior_passthrough():
    fake = FakeLlmClient(
        [
            {
                "behavior": "clarify",
                "clarify_question": "您想查含税还是不含税销售额?",
                "clarify_options": ["含税", "不含税"],
            }
        ]
    )
    result = plan("本月销售额", llm=fake)

    assert result.behavior == "clarify"
    assert result.clarify_question == "您想查含税还是不含税销售额?"
    assert list(result.clarify_options) == ["含税", "不含税"]
    assert result.cube_query is None


def test_miss_behavior_passthrough():
    fake = FakeLlmClient(
        [
            {
                "behavior": "miss",
                "reply": "未找到已定义指标「库存周转率」",
            }
        ]
    )
    result = plan("库存周转率是多少", llm=fake)

    assert result.behavior == "miss"
    assert result.reply and "库存周转率" in result.reply
    assert result.cube_query is None


def test_chitchat_behavior_passthrough():
    fake = FakeLlmClient([{"behavior": "chitchat", "reply": "我是问数助手,请提数据问题"}])
    result = plan("帮我写个周报", llm=fake)

    assert result.behavior == "chitchat"
    assert result.cube_query is None


# ---------------------------------------------------------------
# 三层防线(FR-D1)
# ---------------------------------------------------------------


def test_hallucinated_measure_intercepted_then_degrades_to_clarify():
    # 主防线被 FakeLlm 绕过(直接返回结构化 JSON),次防线编译校验必须拦截
    fake = FakeLlmClient(
        [
            _query_payload(measures=["nonexistent_measure"]),
            _query_payload(measures=["also_wrong"]),  # 修复回喂仍失败
        ]
    )
    result = plan("查一下幻觉指标", llm=fake)

    assert result.behavior == "clarify"  # 兜底:绝不出数
    assert result.cube_query is None
    assert result.validation is not None and result.validation != "passed"
    fake.assert_no_pending()


def test_hallucinated_measure_repaired_once_passes():
    fake = FakeLlmClient(
        [
            _query_payload(measures=["ghost_measure"]),
            _query_payload(measures=["sales_amount"], slot="last_month"),
        ]
    )
    result = plan("查一下需要修复的指标", llm=fake)

    assert result.behavior == "query"
    assert result.validation == "repaired"
    assert result.cube_query["measures"] == ["sales_amount"]


def test_unknown_cube_is_intercepted():
    fake = FakeLlmClient([_query_payload(cube="ghost_cube")])
    result = plan("查幽灵 cube", llm=fake)

    assert result.behavior == "error"
    assert result.cube_query is None


# ---------------------------------------------------------------
# K3 确定性槽位继承(FR-C1 基础)
# ---------------------------------------------------------------


def test_time_slot_inherited_from_previous_turn():
    prev_cube_query = {
        "cube": "sales",
        "measures": ["sales_amount"],
        "timeDimensions": [
            {
                "dimension": "order_date",
                "dateRange": ["2026-10-01", "2026-11-01"],
                "granularity": "month",
            }
        ],
    }
    history = [{"question": "上个月各渠道营收", "result": {"behavior": "query", "cube_query": prev_cube_query}}]
    fake = FakeLlmClient([_query_payload()])  # 当前轮无 time 槽位
    result = plan("华南区呢", history=history, llm=fake)

    assert result.behavior == "query"
    assert result.cube_query["timeDimensions"] == prev_cube_query["timeDimensions"]


def test_history_is_sent_to_llm_as_user_assistant_pairs():
    history = [
        {"question": "上个月营收", "result": {"behavior": "query", "cube_query": {"cube": "sales"}}}
    ]
    fake = FakeLlmClient([{"behavior": "chitchat", "reply": "ok"}])
    plan("谢谢", history=history, llm=fake)

    messages = fake.calls[0]["messages"]
    assert messages[0] == {"role": "user", "content": "上个月营收"}
    assert messages[1]["role"] == "assistant"


# ---------------------------------------------------------------
# LLM 调用失败归因
# ---------------------------------------------------------------


def test_llm_error_returns_error_behavior():
    fake = FakeLlmClient([LlmCall(model="fake-model", output_text="", latency_ms=0, error="boom")])
    result = plan("任意问题", llm=fake)

    assert result.behavior == "error"
    assert result.llm_error == "boom"
    assert result.cube_query is None


def test_unparseable_llm_output_returns_error_behavior():
    fake = FakeLlmClient(["这不是JSON输出"])
    result = plan("任意问题", llm=fake)

    assert result.behavior == "error"


def test_unknown_behavior_normalized_to_error():
    fake = FakeLlmClient([{"behavior": "teleport"}])
    result = plan("任意问题", llm=fake)

    assert result.behavior == "error"


def test_plan_result_is_frozen_dataclass():
    result = PlanResult(question="q")
    try:
        result.behavior = "x"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("PlanResult 应为 frozen dataclass")
