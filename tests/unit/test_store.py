"""会话/挖掘候选存储测试:Repository 协议的内存与 SQLite 双实现。"""

from __future__ import annotations

from chatbi.mining import MiningCandidate
from chatbi.session import ChatSession
from chatbi.store.memory import InMemoryMiningRepository, InMemorySessionRepository
from chatbi.store.sqlite import SqliteMiningRepository, SqliteSessionRepository


def _session(sid="s1", state="IDLE"):
    return ChatSession(
        session_id=sid,
        state=state,
        history=({"question": "q1", "result": {"behavior": "query"}},),
        pending_plan={"behavior": "query", "cube_query": {"cube": "sales"}},
        pending_clarification={"step": "time", "round": 1},
    )


class TestSessionRepositories:
    def test_memory_roundtrip(self):
        repo = InMemorySessionRepository()
        repo.save(_session())
        loaded = repo.load("s1")
        assert loaded.state == "IDLE"
        assert loaded.pending_clarification["step"] == "time"

    def test_sqlite_roundtrip(self, tmp_path):
        repo = SqliteSessionRepository(tmp_path / "t.db")
        repo.save(_session())
        loaded = repo.load("s1")
        assert loaded.state == "IDLE"
        assert loaded.pending_plan["cube_query"]["cube"] == "sales"
        assert len(loaded.history) == 1

    def test_sqlite_load_missing_returns_default_idle(self, tmp_path):
        repo = SqliteSessionRepository(tmp_path / "t.db")
        fresh = repo.load("nope")
        assert fresh.state == "IDLE"
        assert fresh.history == ()

    def test_history_is_capped_at_five_turns(self):
        repo = InMemorySessionRepository()
        # 直接构造超限历史再保存,验证保存时截断
        turns = tuple({"question": f"q{i}", "result": {}} for i in range(9))
        capped = _session("s9").with_history(turns)
        repo.save(capped)
        assert len(repo.load("s9").history) == 5


class TestMiningRepositories:
    def test_memory_candidate_roundtrip(self):
        repo = InMemoryMiningRepository()
        cid = repo.record(
            MiningCandidate(question="库存周转率", normalized="库存周转率", user="u1")
        )
        assert cid
        assert repo.list_candidates()[0].question == "库存周转率"

    def test_sqlite_candidate_roundtrip(self, tmp_path):
        repo = SqliteMiningRepository(tmp_path / "m.db")
        cid = repo.record(
            MiningCandidate(
                question="库存周转率",
                normalized="库存周转率",
                user="u1",
                retrieval_context="ctx",
            )
        )
        cands = repo.list_candidates()
        assert len(cands) == 1
        assert cands[0].candidate_id == cid
        assert cands[0].retrieval_context == "ctx"
