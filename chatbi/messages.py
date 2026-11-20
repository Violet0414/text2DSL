"""消息记录模型与仓库协议(FR-C5):全量问答消息持久化,支持会话回看。

与 ChatSession.history(最近 5 轮摘要,FR-C3)不同:消息表存全量消息,
供前端会话列表与历史回看使用;traceId 是回放锚点。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

TITLE_MAX_LEN = 20


@dataclass(frozen=True)
class ChatMessage:
    """一条问答消息:user 提问或 assistant 应答载荷。"""

    message_id: int
    session_id: str
    role: str
    payload: dict[str, Any]
    trace_id: str
    created_at: str


@dataclass(frozen=True)
class SessionSummary:
    """会话列表条目:标题取首轮问题截断。"""

    session_id: str
    title: str
    message_count: int
    updated_at: str


def build_title(text: str) -> str:
    """首轮用户问题截断为会话标题(确定性)。"""
    text = text.strip().replace("\n", " ")
    return text[:TITLE_MAX_LEN]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MessageRepository(Protocol):
    def append(
        self, session_id: str, role: str, payload: dict[str, Any], trace_id: str = ""
    ) -> int: ...

    def history(self, session_id: str) -> list[ChatMessage]: ...

    def list_sessions(self) -> list[SessionSummary]: ...

    def delete(self, session_id: str) -> int: ...
