"""挖掘候选(FR-D3):未命中/低置信不收敛/no_match 落库,推治理平台 FR-12 队列。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from chatbi.clarify import normalize_dimension_value


@dataclass(frozen=True)
class MiningCandidate:
    """挖掘候选快照:问题原文 + 规范化 + 检索上下文。"""

    question: str
    normalized: str
    user: str = ""
    retrieval_context: str = ""
    candidate_id: str = ""
    created_at: str = ""


def new_candidate(
    question: str, user: str = "", retrieval_context: str = ""
) -> MiningCandidate:
    """构造带 id/时间戳/规范化问题的候选(落库前的唯一入口)。"""
    now = datetime.now().isoformat(timespec="seconds")
    return MiningCandidate(
        question=question,
        normalized=normalize_dimension_value(question),
        user=user,
        retrieval_context=retrieval_context,
        candidate_id=uuid.uuid4().hex[:12],
        created_at=now,
    )


class MiningRepository(Protocol):
    def record(self, candidate: MiningCandidate) -> str: ...

    def list_candidates(self) -> list[MiningCandidate]: ...
