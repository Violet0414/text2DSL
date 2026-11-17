"""FastAPI 入口:POST /api/ask 统一信封(PRD §5.2)。

信封:{success, data, error{code,message}|null, meta{traceId, latencyMs}}
装配:build_default_pipeline() 用 SQLite 存储 + 默认门禁/执行器装配;
LLM 客户端经环境变量(appkey 后期填入),未配置时经信封返回明确错误。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from chatbi.executor import WrenCliExecutor
from chatbi.gate import FileGateStateRepository, GovernanceGate
from chatbi.pipeline import ChatPipeline
from chatbi.planner.core import MDL_PATH
from chatbi.planner.schema import load_mdl
from chatbi.security import assert_no_db_credentials
from chatbi.store.memory import InMemoryMiningRepository
from chatbi.store.sqlite import SqliteSessionRepository


class AskRequest(BaseModel):
    sessionId: str = Field(min_length=1)
    question: str = Field(min_length=1)


def build_default_pipeline() -> ChatPipeline:
    """默认装配:SQLite 会话 + 内存候选 + 文件门禁 + wren CLI 执行器。"""
    assert_no_db_credentials()
    gate = GovernanceGate(FileGateStateRepository(), load_mdl(MDL_PATH))
    return ChatPipeline(
        session_store=SqliteSessionRepository(Path("chatbi_sessions.db")),
        mining_store=InMemoryMiningRepository(),
        gate=gate,
        executor=WrenCliExecutor(),
        llm=None,
    )


def create_app(pipeline: ChatPipeline | None = None) -> FastAPI:
    """构建 FastAPI 应用;pipeline 可注入(测试)。缺省延迟装配默认流水线。"""
    app = FastAPI(title="ChatBI API", version="0.1.0")
    state: dict[str, Any] = {"pipeline": pipeline}

    def _pipe() -> ChatPipeline:
        if state["pipeline"] is None:
            state["pipeline"] = build_default_pipeline()
        return state["pipeline"]

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/api/ask")
    def ask(req: AskRequest):
        started = time.monotonic()
        trace_id = uuid.uuid4().hex

        def _meta() -> dict[str, Any]:
            return {
                "traceId": trace_id,
                "latencyMs": int((time.monotonic() - started) * 1000),
            }

        try:
            payload = _pipe().ask(req.sessionId, req.question)
            return {
                "success": True,
                "data": asdict(payload),
                "error": None,
                "meta": _meta(),
            }
        except Exception as exc:  # noqa: BLE001 — 信封兜底:任何异常不裸奔
            return {
                "success": False,
                "data": None,
                "error": {"code": type(exc).__name__, "message": str(exc)[:500]},
                "meta": _meta(),
            }

    return app


app = create_app()
