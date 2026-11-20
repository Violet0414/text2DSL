"""FastAPI 入口:POST /api/ask 统一信封(PRD §5.2)。

信封:{success, data, error{code,message}|null, meta{traceId, latencyMs}}
装配:build_default_pipeline() 用 SQLite 存储 + 默认门禁/执行器装配;
LLM 客户端经环境变量(appkey 后期填入),未配置时经信封返回明确错误。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from chatbi.auth import (
    ADMIN_USERNAME,
    BEARER_PREFIX,
    TokenStore,
    admin_password,
    require_user,
)
from chatbi.executor import WrenCliExecutor
from chatbi.gate import FileGateStateRepository, GovernanceGate
from chatbi.messages import MessageRepository
from chatbi.pipeline import ChatPipeline
from chatbi.planner.core import MDL_PATH
from chatbi.planner.schema import load_mdl
from chatbi.security import assert_no_db_credentials
from chatbi.session import SessionRepository
from chatbi.store.memory import InMemoryMiningRepository
from chatbi.store.sqlite import SqliteMessageRepository, SqliteSessionRepository

logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    sessionId: str = Field(min_length=1)
    question: str = Field(min_length=1)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


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


def create_app(
    pipeline: ChatPipeline | None = None,
    message_store: MessageRepository | None = None,
    tokens: TokenStore | None = None,
    session_store: SessionRepository | None = None,
) -> FastAPI:
    """构建 FastAPI 应用;pipeline/message_store/tokens/session_store 可注入(测试)。缺省延迟装配。"""
    app = FastAPI(title="ChatBI API", version="0.1.0")
    state: dict[str, Any] = {"pipeline": pipeline}
    messages = message_store if message_store is not None else None
    sessions = session_store if session_store is not None else None
    token_store = tokens if tokens is not None else TokenStore()

    def _pipe() -> ChatPipeline:
        if state["pipeline"] is None:
            state["pipeline"] = build_default_pipeline()
        return state["pipeline"]

    def _sessions() -> SessionRepository:
        nonlocal sessions
        if sessions is None:
            sessions = SqliteSessionRepository(Path("chatbi_sessions.db"))
        return sessions

    def _messages() -> MessageRepository:
        nonlocal messages
        if messages is None:
            messages = SqliteMessageRepository(Path("chatbi_sessions.db"))
        return messages

    def _guard(request: Request) -> str:
        return require_user(request, token_store)

    def _record_messages(
        session_id: str, question: str, data: dict[str, Any], trace_id: str
    ) -> None:
        """问答消息落库(FR-C5)。落库失败不阻断应答,记日志降级。"""
        try:
            store = _messages()
            store.append(session_id, role="user", payload={"text": question})
            store.append(session_id, role="assistant", payload=data, trace_id=trace_id)
        except Exception:  # noqa: BLE001 — 消息持久化是旁路能力,失败不影响问数主链路
            logger.exception("消息落库失败 sessionId=%s traceId=%s", session_id, trace_id)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    # --- vben 框架契约端点({code,data,errorMessage},与统一信封为显式边界) ---

    @app.post("/api/auth/login")
    def auth_login(body: LoginRequest):
        if body.username != ADMIN_USERNAME or body.password != admin_password():
            return {"code": 1, "data": None, "errorMessage": "用户名或口令错误"}
        return {"code": 0, "data": {"accessToken": token_store.issue()}}

    @app.post("/api/auth/refresh")
    def auth_refresh():
        # v1 token 不做刷新链;401 让前端回到登录页重新登录
        raise HTTPException(status_code=401, detail="token 已过期,请重新登录")

    @app.post("/api/auth/logout")
    def auth_logout(request: Request):
        header = request.headers.get("Authorization", "")
        if header.startswith(BEARER_PREFIX):
            token_store.revoke(header[len(BEARER_PREFIX) :].strip())
        return {"code": 0, "data": None, "errorMessage": None}

    @app.get("/api/auth/codes")
    def auth_codes(request: Request):
        _guard(request)
        return {"code": 0, "data": [], "errorMessage": None}

    @app.get("/api/user/info")
    def user_info(request: Request):
        username = _guard(request)
        return {
            "code": 0,
            "data": {
                "userId": username,
                "username": username,
                "realName": "语义治理管理员",
                "avatar": "",
                "roles": ["admin"],
                "homePath": "/chatbi",
            },
            "errorMessage": None,
        }

    # --- chatbi 业务端点(统一信封) ---

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
            data = asdict(payload)
            _record_messages(req.sessionId, req.question, data, trace_id)
            return {
                "success": True,
                "data": data,
                "error": None,
                "meta": _meta(),
            }
        except Exception as exc:  # noqa: BLE001 — 信封兜底:任何异常不裸奔
            logger.exception(
                "问数处理异常 sessionId=%s traceId=%s", req.sessionId, trace_id
            )
            return {
                "success": False,
                "data": None,
                "error": {"code": type(exc).__name__, "message": str(exc)[:500]},
                "meta": _meta(),
            }

    @app.get("/api/sessions")
    def list_sessions(request: Request):
        _guard(request)
        started = time.monotonic()
        trace_id = uuid.uuid4().hex
        try:
            sessions = _messages().list_sessions()
            return {
                "success": True,
                "data": {
                    "sessions": [
                        {
                            "sessionId": s.session_id,
                            "title": s.title,
                            "messageCount": s.message_count,
                            "updatedAt": s.updated_at,
                        }
                        for s in sessions
                    ]
                },
                "error": None,
                "meta": {"traceId": trace_id, "latencyMs": int((time.monotonic() - started) * 1000)},
            }
        except Exception as exc:  # noqa: BLE001 — 信封兜底
            return {
                "success": False,
                "data": None,
                "error": {"code": type(exc).__name__, "message": str(exc)[:500]},
                "meta": {"traceId": trace_id, "latencyMs": int((time.monotonic() - started) * 1000)},
            }

    @app.get("/api/sessions/{session_id}/history")
    def session_history(session_id: str, request: Request):
        _guard(request)
        started = time.monotonic()
        trace_id = uuid.uuid4().hex

        def _meta() -> dict[str, Any]:
            return {
                "traceId": trace_id,
                "latencyMs": int((time.monotonic() - started) * 1000),
            }

        try:
            msgs = _messages().history(session_id)
            if not msgs:
                return {
                    "success": False,
                    "data": None,
                    "error": {"code": "NOT_FOUND", "message": f"会话 {session_id} 不存在"},
                    "meta": _meta(),
                }
            return {
                "success": True,
                "data": {
                    "sessionId": session_id,
                    "messages": [
                        {
                            "messageId": m.message_id,
                            "role": m.role,
                            "payload": m.payload,
                            "traceId": m.trace_id,
                            "createdAt": m.created_at,
                        }
                        for m in msgs
                    ],
                },
                "error": None,
                "meta": _meta(),
            }
        except Exception as exc:  # noqa: BLE001 — 信封兜底
            return {
                "success": False,
                "data": None,
                "error": {"code": type(exc).__name__, "message": str(exc)[:500]},
                "meta": _meta(),
            }

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str, request: Request):
        _guard(request)
        started = time.monotonic()
        trace_id = uuid.uuid4().hex

        def _meta() -> dict[str, Any]:
            return {
                "traceId": trace_id,
                "latencyMs": int((time.monotonic() - started) * 1000),
            }

        try:
            # 先清会话残留状态(不可见且可重试);消息删除是权威步骤,放最后:
            # 若状态清理失败,重试仍可得;若消息删除失败,残留状态已被清,无副作用
            _sessions().delete(session_id)
            deleted = _messages().delete(session_id)
            if deleted == 0:
                return {
                    "success": False,
                    "data": None,
                    "error": {"code": "NOT_FOUND", "message": f"会话 {session_id} 不存在"},
                    "meta": _meta(),
                }
            return {
                "success": True,
                "data": {"sessionId": session_id, "deletedMessages": deleted},
                "error": None,
                "meta": _meta(),
            }
        except Exception as exc:  # noqa: BLE001 — 信封兜底
            return {
                "success": False,
                "data": None,
                "error": {"code": type(exc).__name__, "message": str(exc)[:500]},
                "meta": _meta(),
            }

    # --- 前端静态托管(生产单服务交付,W0) ---
    # hash 路由(VITE_ROUTER_HISTORY=hash),仅需 index.html;路由先注册,挂载不遮蔽 /api 与 /docs。
    web_dist = Path(__file__).resolve().parent.parent / "web" / "apps" / "web-antd" / "dist"
    if web_dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")
        logger.info("前端静态资源已托管: %s", web_dist)

    return app


app = create_app()
