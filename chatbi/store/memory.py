"""内存存储实现(单进程最简方案,Q2)。"""

from __future__ import annotations

from dataclasses import replace

from chatbi.mining import MiningCandidate, new_candidate
from chatbi.session import ChatSession


class InMemorySessionRepository:
    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}

    def load(self, session_id: str) -> ChatSession:
        return self._sessions.get(session_id, ChatSession(session_id=session_id))

    def save(self, session: ChatSession) -> None:
        self._sessions[session.session_id] = session


def _ensure_identity(candidate: MiningCandidate) -> MiningCandidate:
    """候选缺 id/时间戳/规范化时补齐(落库纪律:id 必有)。"""
    if candidate.candidate_id and candidate.created_at and candidate.normalized:
        return candidate
    fresh = new_candidate(
        candidate.question, candidate.user, candidate.retrieval_context
    )
    return replace(
        candidate,
        candidate_id=candidate.candidate_id or fresh.candidate_id,
        created_at=candidate.created_at or fresh.created_at,
        normalized=candidate.normalized or fresh.normalized,
    )


class InMemoryMiningRepository:
    def __init__(self):
        self._candidates: list[MiningCandidate] = []

    def record(self, candidate: MiningCandidate) -> str:
        candidate = _ensure_identity(candidate)
        self._candidates.append(candidate)
        return candidate.candidate_id

    def list_candidates(self) -> list[MiningCandidate]:
        return list(self._candidates)
