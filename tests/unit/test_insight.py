"""AI 解读模块测试:单次 LLM 产出 summary/core_data/trend_analysis,失败降级不阻断。"""

from __future__ import annotations

import json

from chatbi.insight import build_insight
from chatbi.planner.llm import LlmCall

ROWS = (
    {"channel": "电商", "sales_amount": 474.3},
    {"channel": "门店", "sales_amount": 589.5},
    {"channel": "小程序", "sales_amount": 918.4},
)
COLUMNS = ("channel", "sales_amount")


class FakeLlmClient:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls: list[tuple[str, list]] = []

    def call(self, system, messages, tool_schema):
        self.calls.append((system, messages))
        out = self._outputs.pop(0)
        text = json.dumps(out, ensure_ascii=False) if isinstance(out, dict) else out
        return LlmCall(model="fake", output_text=text, latency_ms=1)


class TestBuildInsight:
    def test_success_parses_all_fields(self):
        llm = FakeLlmClient(
            [
                {
                    "summary": "根据sales_amount统计,共3项,最大项为小程序",
                    "core_data": "合计 1982.2;最大项 小程序 918.4",
                    "trend_analysis": "各渠道量级差异明显,小程序约为电商的 1.9 倍",
                }
            ]
        )
        result = build_insight("各渠道营收", ROWS, COLUMNS, llm)
        assert result.ok is True
        assert result.core_data == "合计 1982.2;最大项 小程序 918.4"
        assert "1.9 倍" in result.trend_analysis
        assert result.summary.startswith("根据")

    def test_retries_once_on_unparseable_output(self):
        llm = FakeLlmClient(
            ["抱歉我无法输出JSON", {"summary": "s", "core_data": "c", "trend_analysis": "t"}]
        )
        result = build_insight("各渠道营收", ROWS, COLUMNS, llm)
        assert result.ok is True
        assert len(llm.calls) == 2

    def test_both_attempts_fail_degrades_gracefully(self):
        llm = FakeLlmClient(["输出1", "输出2"])
        result = build_insight("各渠道营收", ROWS, COLUMNS, llm)
        assert result.ok is False
        assert result.core_data == ""
        assert result.error

    def test_prompt_forbids_fabrication_and_includes_data(self):
        llm = FakeLlmClient([{"summary": "s", "core_data": "c", "trend_analysis": "t"}])
        build_insight("各渠道营收", ROWS, COLUMNS, llm)
        system = llm.calls[0][0]
        assert "编造" in system
        user_msg = llm.calls[0][1][-1]["content"]
        assert "各渠道营收" in user_msg
        assert "918.4" in user_msg  # 真实数据喂给 LLM

    def test_rows_capped_at_20_in_prompt(self):
        rows = tuple({"region": f"R{i}", "amount": i} for i in range(50))
        llm = FakeLlmClient([{"summary": "s", "core_data": "c", "trend_analysis": "t"}])
        build_insight("各区县数量", rows, ("region", "amount"), llm)
        user_msg = llm.calls[0][1][-1]["content"]
        assert "R49" not in user_msg  # 截断到前 20 行
        assert "R19" in user_msg

    def test_think_block_stripped_from_output(self):
        raw = "<think>让我想想 {fake}</think>" + json.dumps(
            {"summary": "s", "core_data": "c", "trend_analysis": "t"}, ensure_ascii=False
        )
        llm = FakeLlmClient([raw])
        result = build_insight("各渠道营收", ROWS, COLUMNS, llm)
        assert result.ok is True
        assert result.core_data == "c"
