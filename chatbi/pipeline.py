"""问数流水线(§5.3 状态机编排):plan → gate → time_rules → executor → 应答组装。

降级矩阵(FR-A5):LLM 解析失败重试 1 次→仍失败明确解释;执行失败/超时明确解释;
空集给出建议;任何失败不返回空结果或未经验证的数据。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, ClassVar

from wren_core import cube_query_to_sql

from chatbi.answer import (
    AnswerCard,
    ClarifyPayload,
    ErrorPayload,
    MissPayload,
    ReplyPayload,
    ReportPayload,
    build_metric_metadata,
)
from chatbi.charting import (
    CHART_LABELS,
    CHART_TYPES,
    build_chart_option,
    recommend_charts,
)
from chatbi.clarify import render_clarification
from chatbi.executor import WrenCliExecutor
from chatbi.gate import GovernanceGate
from chatbi.insight import InsightResult, build_insight
from chatbi.mining import MiningRepository, new_candidate
from chatbi.planner.core import MDL_PATH, PlanResult, get_default_llm_client, plan
from chatbi.planner.llm import LlmConfigError
from chatbi.planner.schema import cube_members, load_mdl
from chatbi.session import ChatSession, SessionRepository
from chatbi.time_rules import TODAY

RESET_PHRASES = {"重新问", "清空", "重置", "清空上下文"}
MAX_CLARIFY_ROUNDS = 2
TIME_OPTION_TO_SLOT = {
    "上个月": "last_month",
    "本月": "current_month",
    "近30天": "last_30d",
    "全部时间": "all_time",
}
_TAX_HINTS = ("含税", "口径")
# FR-B3 总览泛问句后缀:出现即视为"默认全部时间"意图,不做裸指标时间兜底
OVERVIEW_SUFFIXES = (
    "情况",
    "怎么样",
    "多少",
    "对比",
    "趋势",
    "如何",
    "整体",
    "总共",
    "概览",
)


class ChatPipeline:
    """单条问数请求的编排器;状态外置到 SessionRepository,自身无状态。"""

    def __init__(
        self,
        session_store: SessionRepository,
        mining_store: MiningRepository,
        gate: GovernanceGate,
        executor: WrenCliExecutor,
        llm=None,
    ):
        self._sessions = session_store
        self._mining = mining_store
        self._gate = gate
        self._executor = executor
        self._llm = llm
        mdl = load_mdl(MDL_PATH)
        self._mdl = mdl
        self._members = cube_members(mdl)
        self._mdl_json = json.dumps(mdl, ensure_ascii=False)

    def ask(self, session_id: str, question: str):
        """处理一轮提问,返回应答载荷(AnswerCard/Clarification/Miss/Reply/Error/Report)。"""
        session = self._sessions.load(session_id)
        if question.strip() in RESET_PHRASES:
            self._sessions.save(ChatSession(session_id=session_id))
            return ReplyPayload(text="已清空上下文,请重新提问")
        chart_selection = self._parse_chart_select(question)
        if chart_selection:
            return self._handle_chart_select(session, chart_selection)
        if session.pending_clarification:
            return self._handle_clarify_answer(session, question)
        return self._plan_and_answer(session, question)

    # --- 规划与分发 ---

    def _plan_and_answer(self, session: ChatSession, question: str):
        session = replace(session, state="ROUTING")
        history = list(session.history)
        result = plan(question, history=history, llm=self._llm)
        if result.behavior == "error":
            result = plan(question, history=history, llm=self._llm)  # FR-A5 重试 1 次
            if result.behavior == "error":
                self._sessions.save(replace(session, state="ERROR_ANSWER"))
                return ErrorPayload(message="问题解析失败,请换一种问法")
        if result.behavior == "chitchat":
            self._sessions.save(
                session.append_history(question, {"behavior": result.behavior})
            )
            return ReplyPayload(text=result.reply or "")
        if result.behavior == "miss":
            cand = new_candidate(question)
            self._mining.record(cand)
            self._sessions.save(
                replace(session, state="IDLE").append_history(
                    question, {"behavior": result.behavior}
                )
            )
            return MissPayload(
                message=result.reply or "未找到已定义指标",
                available_metrics=self._metric_names(),
                candidate_id=cand.candidate_id,
            )
        if result.behavior == "clarify":
            return self._enter_llm_clarify(session, question, result)
        return self._on_query(session, question, result)

    # --- query 路径 ---

    def _on_query(self, session: ChatSession, question: str, result: PlanResult):
        wren_cq = self._drop_dims_covered_by_filters(result.cube_query or {})
        if wren_cq != result.cube_query:
            # 归一化改变了查询 → 以归一化后的查询重新生成 SQL,保证执行与判定一致
            result = replace(
                result, cube_query=wren_cq, generated_sql=self._to_sql(wren_cq)
            )
        verdict = self._gate.check_query(wren_cq)
        if not verdict.passed:
            self._sessions.save(replace(session, state="IDLE"))
            return MissPayload(
                message=f"指标 {', '.join(verdict.denied)} 门禁未开,暂不可查",
                available_metrics=self._metric_names(),
            )
        has_dims = bool(wren_cq.get("dimensions") or wren_cq.get("filters"))
        has_time = bool(wren_cq.get("timeDimensions"))
        if not has_time and not has_dims:
            # FR-B3 裸指标无修饰 → 模板澄清时间
            return self._enter_time_clarify(session, wren_cq)
        if self._should_force_time_clarify(question, wren_cq, result.time_slot):
            # FR-B3 确定性兜底:裸指标被 LLM 漂移为 all_time 缺省时仍强制澄清
            return self._enter_time_clarify(session, wren_cq)
        return self._execute_and_answer(session, question, wren_cq, result)

    def _enter_time_clarify(self, session: ChatSession, wren_cq: dict):
        clarified = render_clarification(
            step="time",
            question="",
            restated=f"查询「{', '.join(wren_cq.get('measures') or [])}」",
        )
        session = replace(
            session,
            state="CLARIFYING",
            pending_plan={"behavior": "query", "cube_query": wren_cq},
            pending_clarification={"kind": "time", "round": 1},
        )
        self._sessions.save(session)
        return ClarifyPayload(
            clarify_step="time",
            options=clarified.options,
            template_id=clarified.template_id,
            question_text=clarified.question_text,
        )

    def _execute_and_answer(
        self, session: ChatSession, question: str, wren_cq: dict, result: PlanResult
    ):
        session = replace(session, state="EXECUTING")
        exec_result = self._executor.execute(result.generated_sql, cube_query=wren_cq)
        history_turn = {"behavior": result.behavior, "cube_query": wren_cq}
        if not exec_result.is_ok:
            self._sessions.save(
                replace(session, state="ERROR_ANSWER").append_history(
                    question, history_turn
                )
            )
            return ErrorPayload(
                message=f"查询执行失败({exec_result.error_class}):{exec_result.error_message}"
            )
        meta = build_metric_metadata(
            wren_cq.get("measures") or [], self._mdl, self._meta_provider()
        )
        message = ""
        if exec_result.row_count == 0:
            message = "查询成功,但没有符合条件的数据。可尝试放宽时间范围或筛选条件。"
        self._sessions.save(
            replace(
                session,
                state="ANSWERING",
                pending_plan=None,
                pending_clarification=None,
                last_answer={
                    "question": question,
                    "rows": [dict(row) for row in exec_result.rows],
                    "columns": list(exec_result.columns),
                },
            ).append_history(question, history_turn)
        )
        chart_options = recommend_charts(question, exec_result.rows, exec_result.columns)
        return AnswerCard(
            rows=exec_result.rows,
            columns=exec_result.columns,
            roles=exec_result.roles,
            metric=meta,
            cube_query=wren_cq,
            chart_options=tuple(
                {"type": o.type, "label": o.label, "purpose": o.purpose}
                for o in chart_options
            ),
            message=message,
        )

    # --- 澄清路径 ---

    def _enter_llm_clarify(
        self, session: ChatSession, question: str, result: PlanResult
    ):
        text = result.clarify_question or ""
        options = list(result.clarify_options)
        step = (
            "tax"
            if any(h in text or h in "".join(options) for h in _TAX_HINTS)
            else "time"
        )
        clarified = render_clarification(
            step=step, question=question, restated=text or question
        )
        session = replace(
            session,
            state="CLARIFYING",
            pending_clarification={"kind": "llm", "round": 1, "question": question},
        )
        self._sessions.save(session)
        return ClarifyPayload(
            clarify_step=step,
            options=clarified.options,
            template_id=clarified.template_id,
            question_text=clarified.question_text,
        )

    def _handle_clarify_answer(self, session: ChatSession, question: str):
        pend = session.pending_clarification or {}
        kind = pend.get("kind")
        if kind == "time":
            slot = TIME_OPTION_TO_SLOT.get(question.strip())
            if slot is None:
                return self._clarify_round_bump(session, pend)
            plan_pend = session.pending_plan or {}
            session = replace(session, pending_clarification=None, pending_plan=None)
            wren_cq = self._apply_time_slot(plan_pend.get("cube_query") or {}, slot)
            verdict = self._gate.check_query(wren_cq)
            if not verdict.passed:
                self._sessions.save(replace(session, state="IDLE"))
                return MissPayload(
                    message=f"指标 {', '.join(verdict.denied)} 门禁未开,暂不可查",
                    available_metrics=self._metric_names(),
                )
            result = PlanResult(
                question=question,
                behavior="query",
                cube_query=wren_cq,
                generated_sql=self._to_sql(wren_cq),
            )
            return self._execute_and_answer(session, question, wren_cq, result)
        if kind == "llm":
            combined = f"{pend.get('question', '')} {question}".strip()
            session = replace(session, pending_clarification=None, pending_plan=None)
            return self._plan_and_answer(session, combined)
        return self._clarify_round_bump(session, pend)

    def _clarify_round_bump(self, session: ChatSession, pend: dict):
        round_no = int(pend.get("round", 1)) + 1
        if round_no > MAX_CLARIFY_ROUNDS:
            cand = new_candidate(
                session.pending_plan
                and json.dumps(session.pending_plan, ensure_ascii=False)
                or ""
            )
            self._mining.record(cand)
            self._sessions.save(
                replace(
                    session, state="IDLE", pending_plan=None, pending_clarification=None
                )
            )
            return MissPayload(
                message="多轮澄清未收敛,已将您的需求记录为挖掘候选",
                available_metrics=self._metric_names(),
                candidate_id=cand.candidate_id,
            )
        session = replace(
            session,
            state="CLARIFYING",
            pending_clarification={**pend, "round": round_no},
        )
        self._sessions.save(session)
        clarified = render_clarification(
            step=pend.get("kind", "time"), question="", restated="请从选项中选择"
        )
        return ClarifyPayload(
            clarify_step=pend.get("kind", "time"),
            options=clarified.options,
            template_id=clarified.template_id,
            question_text=clarified.question_text,
        )

    # --- 图表选择轮(镜像工作流意图路由 code_router + result_cache 语义) ---

    _CHART_SELECT_ALIASES: ClassVar[dict[str, str]] = {
        "饼图": "pie",
        "柱状图": "bar",
        "柱图": "bar",
        "条形图": "bar",
        "折线图": "line",
        "线图": "line",
    }

    @classmethod
    def _parse_chart_select(cls, question: str) -> str | None:
        """识别图表选择消息:前端按钮 JSON 约定优先,纯文本图表名兜底(镜像 code_router)。"""
        text = (question or "").strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and payload.get("action") == "chart_select":
            chart_type = str(payload.get("chart_type") or "").strip().lower()
            return chart_type if chart_type in CHART_TYPES else "bar"
        return cls._CHART_SELECT_ALIASES.get(text.lower())

    def _handle_chart_select(
        self, session: ChatSession, chart_type: str
    ) -> AnswerCard | ReplyPayload | ReportPayload:
        last = session.last_answer or {}
        rows = last.get("rows") or []
        if not rows:
            return ReplyPayload(
                text="当前会话没有可用的查询结果。请先输入一个数据问题"
                "(如:上个月各渠道营收),查询成功后再选择图表。"
            )
        question = str(last.get("question") or "")
        columns = tuple(last.get("columns") or ())
        row_dicts = tuple(dict(row) for row in rows)
        option = build_chart_option(row_dicts, columns, chart_type, question)
        if option is None:
            return ReplyPayload(text="当前查询结果没有可绘图的数值列,无法生成图表。")
        insight = self._build_insight_safe(question, row_dicts, columns)
        return ReportPayload(
            question=question,
            summary=insight.summary,
            chart={
                "type": chart_type,
                "label": CHART_LABELS[chart_type],
                "echarts_option": option,
            },
            insight=(
                {}
                if not insight.ok
                else {
                    "core_data": insight.core_data,
                    "trend_analysis": insight.trend_analysis,
                }
            ),
            message="" if insight.ok else "AI 解读生成失败,请稍后重试",
        )

    def _build_insight_safe(
        self,
        question: str,
        rows: tuple[dict[str, Any], ...],
        columns: tuple[str, ...],
    ) -> InsightResult:
        """解读失败(含 LLM 未配置)不阻断图表返回,降级为空解读。"""
        try:
            llm = self._llm or get_default_llm_client()
        except LlmConfigError:
            return InsightResult(ok=False, error="llm not configured")
        return build_insight(question, rows, columns, llm)

    # --- 工具函数 ---

    def _apply_time_slot(self, wren_cq: dict, slot: str) -> dict:
        """用户选择时间选项 → 确定性展开并写入 cube_query(无 LLM 参与)。"""
        from chatbi.planner.time_expand import expand_time

        expanded = expand_time(slot, TODAY)
        cube = wren_cq.get("cube", "")
        time_dim = (self._members.get(cube, {}).get("time_dimensions") or ["__time__"])[
            0
        ]
        ranges = [expanded.base.to_strings()]
        if expanded.compare is not None:
            ranges.append(expanded.compare.to_strings())
        tds = [
            {
                "dimension": time_dim,
                "dateRange": r,
                "granularity": expanded.granularity or "month",
            }
            for r in ranges
        ]
        return {**wren_cq, "timeDimensions": tds}

    def _to_sql(self, wren_cq: dict) -> str:
        return cube_query_to_sql(
            json.dumps(wren_cq, ensure_ascii=False), self._mdl_json
        )

    def _meta_provider(self):
        return self._gate.get_meta if hasattr(self._gate, "get_meta") else None

    def _drop_dims_covered_by_filters(self, wren_cq: dict) -> dict:
        """确定性归一化:被单值(eq)筛选的维度不重复进分组维度(FR-A3 规范形态)。

        in 多值筛选是多行对比,分组维度必须保留;仅 eq 单值筛选产生冗余分组。
        """
        eq_filtered = {
            f.get("dimension")
            for f in wren_cq.get("filters") or []
            if f.get("operator") == "eq"
        }
        dims = [d for d in wren_cq.get("dimensions") or [] if d not in eq_filtered]
        if not dims:
            wren_cq = {k: v for k, v in wren_cq.items() if k != "dimensions"}
        else:
            wren_cq = {**wren_cq, "dimensions": dims}
        return wren_cq

    def _should_force_time_clarify(
        self, question: str, wren_cq: dict, time_slot: str | None
    ) -> bool:
        """FR-B3 确定性兜底:裸指标(无维度/筛选)且时间来自 all_time 缺省或缺失时,
        若问题无总览泛问后缀 → 强制澄清时间,不依赖 LLM 自觉。

        显式槽位与多轮继承时间不兜底;总览泛问句(情况/怎么样/多少…)不兜底。
        """
        if wren_cq.get("dimensions") or wren_cq.get("filters"):
            return False
        has_time = bool(wren_cq.get("timeDimensions"))
        if has_time and time_slot != "all_time":
            return False  # 显式或继承时间,不兜底
        return not any(suffix in question for suffix in OVERVIEW_SUFFIXES)

    def _metric_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for cube in self._members.values():
            names.extend(cube["measures"])
        return tuple(sorted(names))
