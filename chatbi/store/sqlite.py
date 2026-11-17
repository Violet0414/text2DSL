"""SQLite 持久化实现(单机部署默认,可平替 Redis 的最简方案,Q2)。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from chatbi.mining import MiningCandidate
from chatbi.session import ChatSession
from chatbi.store.memory import _ensure_identity


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS mining_candidates (
            candidate_id TEXT PRIMARY KEY, question TEXT, normalized TEXT,
            user TEXT, retrieval_context TEXT, created_at TEXT)""")
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
