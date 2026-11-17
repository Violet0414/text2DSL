"""SQLite 持久化实现(单机部署默认,可平替 Redis 的最简方案,Q2)。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from chatbi.messages import ChatMessage, SessionSummary, build_title, now_iso
from chatbi.mining import MiningCandidate
from chatbi.session import ChatSession
from chatbi.store.memory import _ensure_identity


def _connect(path: str | Path) -> sqlite3.Connection:
    # check_same_thread=False:连接随仓库对象复用(FastAPI 线程池执行端点),
    # 写入均为单条事务,由 commit 串行化
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS mining_candidates (
            candidate_id TEXT PRIMARY KEY, question TEXT, normalized TEXT,
            user TEXT, retrieval_context TEXT, created_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, role TEXT NOT NULL,
            payload TEXT NOT NULL, trace_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL)""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_session"
        " ON chat_messages (session_id, id)"
    )
    return conn


class SqliteSessionRepository:
    def __init__(self, path: str | Path):
        self._conn = _connect(path)

    def load(self, session_id: str) -> ChatSession:
        row = self._conn.execute(
            "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return ChatSession(session_id=session_id)
        data = json.loads(row[0])
        return ChatSession(
            session_id=data["session_id"],
            state=data.get("state", "IDLE"),
            history=tuple(data.get("history") or ()),
            pending_plan=data.get("pending_plan"),
            pending_clarification=data.get("pending_clarification"),
        )

    def save(self, session: ChatSession) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, data) VALUES (?, ?)",
            (session.session_id, json.dumps(asdict(session), ensure_ascii=False)),
        )
        self._conn.commit()


class SqliteMiningRepository:
    def __init__(self, path: str | Path):
        self._conn = _connect(path)

    def record(self, candidate: MiningCandidate) -> str:
        candidate = _ensure_identity(candidate)
        self._conn.execute(
            "INSERT OR REPLACE INTO mining_candidates VALUES (?, ?, ?, ?, ?, ?)",
            (
                candidate.candidate_id,
                candidate.question,
                candidate.normalized,
                candidate.user,
                candidate.retrieval_context,
                candidate.created_at,
            ),
        )
        self._conn.commit()
        return candidate.candidate_id

    def list_candidates(self) -> list[MiningCandidate]:
        rows = self._conn.execute(
            "SELECT candidate_id, question, normalized, user, retrieval_context, created_at"
            " FROM mining_candidates ORDER BY created_at"
        ).fetchall()
        return [
            MiningCandidate(
                candidate_id=r[0],
                question=r[1],
                normalized=r[2],
                user=r[3],
                retrieval_context=r[4],
                created_at=r[5],
            )
            for r in rows
        ]


class SqliteMessageRepository:
    """全量问答消息持久化(chat_messages 表,FR-C5 历史回看数据源)。"""

    def __init__(self, path: str | Path):
        self._conn = _connect(path)

    def append(
        self, session_id: str, role: str, payload: dict, trace_id: str = ""
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO chat_messages (session_id, role, payload, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, role, json.dumps(payload, ensure_ascii=False), trace_id, now_iso()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def history(self, session_id: str) -> list[ChatMessage]:
        rows = self._conn.execute(
            "SELECT id, session_id, role, payload, trace_id, created_at"
            " FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [
            ChatMessage(
                message_id=r[0],
                session_id=r[1],
                role=r[2],
                payload=json.loads(r[3]),
                trace_id=r[4],
                created_at=r[5],
            )
            for r in rows
        ]

    def list_sessions(self) -> list[SessionSummary]:
        rows = self._conn.execute(
            """SELECT session_id,
                    (SELECT payload FROM chat_messages m2
                     WHERE m2.session_id = m.session_id AND m2.role = 'user'
                     ORDER BY m2.id LIMIT 1) AS first_payload,
                    COUNT(*) AS message_count,
                    MAX(created_at) AS updated_at
            FROM chat_messages m
            GROUP BY session_id
            ORDER BY MAX(id) DESC"""
        ).fetchall()
        return [
            SessionSummary(
                session_id=r[0],
                title=build_title(json.loads(r[1]).get("text", "")) if r[1] else "",
                message_count=int(r[2]),
                updated_at=r[3],
            )
            for r in rows
        ]
