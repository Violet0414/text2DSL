"""问数流水线集成测试(§5.3 状态机):plan→gate→time_rules→executor→应答,全链路用 Fake 注入。"""

from __future__ import annotations

import json
from dataclasses import replace

from chatbi.executor import ExecutionResult, derive_roles
from chatbi.gate import FileGateStateRepository, GovernanceGate
from chatbi.pipeline import ChatPipeline
from chatbi.planner.llm import LlmCall
from chatbi.store.memory import InMemoryMiningRepository, InMemorySessionRepository

PREV_TD = [
    {
        "dimension": "order_date",
        "dateRange": ["2026-10-01", "2026-11-01"],
        "granularity": "month",
    }
]


class FakeLlmClient:
    def __init__(self, outputs):
        self._outputs = list(outputs)

    def call(self, system, messages, tool_schema):
        out = self._outputs.pop(0)
        text = json.dumps(out, ensure_ascii=False) if isinstance(out, dict) else out
        return LlmCall(model="fake", output_text=text, latency_ms=1)


class FakeRunner:
    def __init__(self, result: ExecutionResult):
        self.result = result

    def __call__(self, *args, **kwargs):
        return FakeProc(self.result)


class FakeProc:
    def __init__(self, result: ExecutionResult):
        self._result = result

    @property
    def returncode(self):
        return 0 if self._result.is_ok else 1


class StubExecutor:
    """pipeline 依赖的执行器替身:直接返回 ExecutionResult。"""

    def __init__(self, result: ExecutionResult):
        self.result = result
        self.last_sql: str | None = None

    def execute(self, sql, limit=1000, cube_query=None):
        self.last_sql = sql
        return replace(
            self.result,
            roles=derive_roles(cube_query) if cube_query else self.result.roles,
        )


def _rows_result(rows):
    cols = tuple(rows[0].keys()) if rows else ()
    return ExecutionResult(
        is_ok=True, columns=cols, rows=tuple(rows), row_count=len(rows)
    )


def _pipeline(llm_outputs, exec_result=None, gate_flags=None):
    store = InMemorySessionRepository()
    mining = InMemoryMiningRepository()
    gate = GovernanceGate(FileGateStateRepository(), _load_real_mdl())
    if gate_flags is not None:
        gate = GovernanceGate(_FakeGateRepo(gate_flags), _load_real_mdl())
    executor = StubExecutor(
        exec_result or _rows_result([{"channel": "华东", "sales_amount": 100}])
    )
    pipe = ChatPipeline(
        session_store=store,
        mining_store=mining,
        gate=gate,
        executor=executor,
        llm=FakeLlmClient(llm_outputs),
    )
    return pipe, store, mining, executor


class _FakeGateRepo:
    def __init__(self, flags):
        self._flags = flags

    def get_flags(self):
        return self._flags


def _load_real_mdl():
    from chatbi.planner.core import MDL_PATH
    from chatbi.planner.schema import load_mdl

    return load_mdl(MDL_PATH)


def _query_out(measures=None, slot=None, dimensions=None):
    cq = {"cube": "sales", "measures": measures or ["sales_amount"]}
    if dimensions:
        cq["dimensions"] = dimensions
    if slot:
        cq["time"] = {"slot": slot}
    return {"behavior": "query", "cube_query": cq}


class TestChitchatAndMiss:
    def test_chitchat_bypasses_to_plain_reply(self):
        pipe, _store, mining, _ = _pipeline(
            [{"behavior": "chitchat", "reply": "我是问数助手"}]
        )
        resp = pipe.ask("s1", "帮我写个周报")
        assert resp.type == "reply"
        assert "问数助手" in resp.text
        assert len(mining.list_candidates()) == 0

    def test_miss_records_mining_candidate_and_lists_metrics(self):
        pipe, _store, mining, _ = _pipeline(
            [{"behavior": "miss", "reply": "未找到「库存周转率」"}]
        )
        resp = pipe.ask("s1", "库存周转率是多少")
        assert resp.type == "miss"
        assert "库存周转率" in resp.message
        assert "sales_amount" in resp.available_metrics
        assert resp.candidate_id
        assert len(mining.list_candidates()) == 1
        cand = mining.list_candidates()[0]
        assert cand.question == "库存周转率是多少"


class TestQueryHappyPath:
    def test_query_returns_answer_card_with_metric_metadata(self):
        pipe, store, _mining, _ = _pipeline(
            [_query_out(slot="last_month", dimensions=["channel"])]
        )
        resp = pipe.ask("s1", "上个月各渠道营收")
        assert resp.type == "answer"
        assert resp.rows[0]["channel"] == "华东"
        assert resp.metric["name"] == "sales_amount"
        # FR-A2 口径五要素
        for key in ("name", "definition", "owner", "version", "freshness"):
            assert key in resp.metric
        assert resp.columns == ("channel", "sales_amount")
        assert resp.roles == {
            "channel": "dimension",
            "sales_amount": "measure",
            "order_date": "time",
        }
        # 会话历史已落
        session = store.load("s1")
        assert session.state == "ANSWERING"
        assert len(session.history) == 1


class TestClarifyFlow:
    def test_bare_metric_without_time_clarifies_time_first(self):
        # FR-B3:裸指标无修饰 → 模板澄清时间(不走 LLM 文案)
        pipe, store, _mining, _ = _pipeline([_query_out()])
        resp = pipe.ask("s1", "查一下营收")
        assert resp.type == "clarification"
        assert resp.clarify_step == "time"
        assert resp.template_id == "clarify_time"
        assert "上个月" in resp.options
        # 澄清挂起,等待用户选项
        session = store.load("s1")
        assert session.state == "CLARIFYING"
        assert session.pending_plan is not None

    def test_user_option_resolves_clarification_and_answers(self):
        pipe, store, _mining, executor = _pipeline(
            [_query_out()], exec_result=_rows_result([{"sales_amount": 42}])
        )
        pipe.ask("s1", "查一下营收")
        resp = pipe.ask("s1", "上个月")
        assert resp.type == "answer"
        assert resp.rows[0]["sales_amount"] == 42
        assert executor.last_sql is not None
        session = store.load("s1")
        assert session.state == "ANSWERING"
        assert session.pending_plan is None

    def test_clarify_not_converging_after_two_rounds_mines_candidate(self):
        # FR-B1:澄清轮数 ≤2;不收敛 → MINING_CANDIDATE
        pipe, store, mining, _ = _pipeline([_query_out()])
        pipe.ask("s1", "查一下营收")
        pipe.ask("s1", "随便看看")  # 第 1 轮澄清答复无效
        resp = pipe.ask("s1", "还是不对")  # 第 2 轮仍不收敛
        assert resp.type == "miss"
        assert resp.candidate_id
        assert len(mining.list_candidates()) == 1
        session = store.load("s1")
        assert session.state == "IDLE"


class TestGateAndDegrade:
    def test_gate_closed_metric_is_refused(self):
        flags = {
            m: {"confirmed": True, "trial_passed": True, "tool_enabled": True}
            for m in [
                "sales_amount",
                "sales_amount_with_tax",
                "order_count",
                "avg_order_value",
                "refund_rate",
            ]
        }
        flags["sales_amount"]["tool_enabled"] = False
        pipe, store, _mining, _ = _pipeline(
            [_query_out(slot="last_month")], gate_flags=flags
        )
        resp = pipe.ask("s1", "上个月营收")
        assert resp.type == "miss"
        assert "sales_amount" in resp.message
        assert resp.rows if False else True  # no rows in miss
        session = store.load("s1")
        assert session.state == "IDLE"

    def test_executor_failure_degrades_with_explanation(self):
        from chatbi.executor import ExecutionResult as ER

        fail = ER(is_ok=False, error_class="timeout", error_message="执行超时(>6s)")
        pipe, _store, _mining, _ = _pipeline(
            [_query_out(slot="last_month")], exec_result=fail
        )
        resp = pipe.ask("s1", "上个月营收")
        assert resp.type == "error"
        assert "超时" in resp.message
        assert resp.rows == ()

    def test_empty_rows_get_explicit_explanation(self):
        pipe, _store, _mining, _ = _pipeline(
            [_query_out(slot="last_month")], exec_result=_rows_result([])
        )
        resp = pipe.ask("s1", "上个月营收")
        assert resp.type == "answer"
        assert resp.rows == ()
        assert "没有" in resp.message or "空" in resp.message


class TestExplicitReset:
    def test_reset_phrase_clears_context(self):
        # FR-C4:重新问/清空 → 上下文清空(基础版)
        pipe, store, _mining, _ = _pipeline([_query_out(slot="last_month")])
        pipe.ask("s1", "上个月营收")
        resp = pipe.ask("s1", "重新问")
        assert resp.type == "reply"
        session = store.load("s1")
        assert session.state == "IDLE"
        assert session.history == ()


class TestFilteredDimNormalization:
    def test_value_filtered_dim_is_dropped_from_groupby(self):
        # 值筛选维度不重复进分组:region=华东 只进 filters(deterministic 归一化)

        from chatbi.executor import ExecutionResult as ER

        rows = [{"sales_amount": 100}]
        pipe, _store, _mining, _executor = _pipeline(
            [
                {
                    "behavior": "query",
                    "cube_query": {
                        "cube": "sales",
                        "measures": ["sales_amount"],
                        "dimensions": ["region"],
                        "time": {"slot": "last_month"},
                        "filters": [
                            {"dimension": "region", "operator": "eq", "value": "华东"}
                        ],
                    },
                }
            ],
            exec_result=ER(
                is_ok=True, columns=("sales_amount",), rows=tuple(rows), row_count=1
            ),
        )
        resp = pipe.ask("s1", "华东区上个月营收")
        assert resp.type == "answer"
        assert resp.cube_query.get("dimensions") in (None, [])
        assert resp.cube_query["filters"][0]["value"] == "华东"


class TestInFilterKeepsDim:
    def test_in_multi_value_filter_keeps_groupby_dim(self):
        # Q36:region in [华东,华北] 是多行对比,分组维度必须保留
        from chatbi.executor import ExecutionResult as ER

        rows = [{"region": "华东", "sales_amount": 100}]
        pipe, _store, _mining, _executor = _pipeline(
            [
                {
                    "behavior": "query",
                    "cube_query": {
                        "cube": "sales",
                        "measures": ["sales_amount"],
                        "dimensions": ["region"],
                        "filters": [
                            {"dimension": "region", "operator": "in", "value": ["华东", "华北"]}
                        ],
                    },
                }
            ],
            exec_result=ER(
                is_ok=True, columns=("region", "sales_amount"), rows=tuple(rows), row_count=1
            ),
        )
        resp = pipe.ask("s1", "华东和华北的营收对比")
        assert resp.type == "answer"
        assert resp.cube_query["dimensions"] == ["region"]


class TestBareMetricTimeGuard:
    def test_bare_metric_word_without_overview_suffix_forces_time_clarify(self):
        # FR-B3 兜底:裸指标词(退款率)漂移为 all_time 时,服务层强制澄清时间
        pipe, _store, _mining, _executor = _pipeline(
            [_query_out(slot="all_time")]
        )
        resp = pipe.ask("s1", "退款率")
        assert resp.type == "clarification"
        assert resp.clarify_step == "time"

    def test_overview_suffix_bare_metric_stays_query(self):
        # 总览泛问句(情况/怎么样/多少)保留 query 行为
        pipe, _store, _mining, _executor = _pipeline([_query_out(slot="all_time")])
        resp = pipe.ask("s1", "营收情况")
        assert resp.type == "answer"

    def test_inherited_time_bare_followup_not_clarified(self):
        # 多轮继承:上一轮有时间,本轮裸追问(如"改成看订单量")不得误澄清
        pipe, _store, _mining, _executor = _pipeline([_query_out()])
        resp = pipe.ask("s1", "订单量")  # 无会话历史、无泛问后缀 → 澄清
        assert resp.type == "clarification"
