"""会话模型与仓库协议(§5.3):状态外置存储,服务无状态化。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

MAX_HISTORY_TURNS = 5
STATES = (
    "IDLE",
    "ROUTING",
    "FILLING",
    "CLARIFYING",
    "EXECUTING",
    "ANSWERING",
    "MINING_CANDIDATE",
    "ERROR_ANSWER",
)


@dataclass(frozen=True)
class ChatSession:
    """一次会话的外置状态快照(不可变,经 replace 演进)。"""

    session_id: str
    state: str = "IDLE"
    history: tuple[dict[str, Any], ...] = ()
    pending_plan: dict[str, Any] | None = None
    pending_clarification: dict[str, Any] | None = None
    last_answer: dict[str, Any] | None = None  # 最近一次查询缓存(rows/columns/question),供图表轮复用

    def with_history(self, turns) -> ChatSession:
        """返回截断至最近 MAX_HISTORY_TURNS 轮的新会话(FR-C3 上下文窗口)。"""
        return replace(self, history=tuple(turns[-MAX_HISTORY_TURNS:]))

    def append_history(self, question: str, result: dict[str, Any]) -> ChatSession:
        return self.with_history(
            self.history + ({"question": question, "result": result},)
        )


class SessionRepository(Protocol):
    def load(self, session_id: str) -> ChatSession: ...

    def save(self, session: ChatSession) -> None: ...

    def delete(self, session_id: str) -> None: ...
