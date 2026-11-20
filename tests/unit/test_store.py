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


class TestMessageRepositoryDelete:
    """消息与会话状态删除:delete 后列表/历史/残留状态均消失。"""

    def test_sqlite_message_delete_returns_count(self, tmp_path):
        from chatbi.store.sqlite import SqliteMessageRepository

        repo = SqliteMessageRepository(tmp_path / "m.db")
        repo.append(session_id="a", role="user", payload={"text": "q"})
        repo.append(session_id="a", role="assistant", payload={"type": "answer"})
        repo.append(session_id="b", role="user", payload={"text": "其他会话"})
        deleted = repo.delete("a")
        assert deleted == 2
        assert repo.history("a") == []
        assert repo.delete("a") == 0  # 幂等:再删返回 0
        assert [s.session_id for s in repo.list_sessions()] == ["b"]

    def test_sqlite_session_delete_clears_pending_state(self, tmp_path):
        repo = SqliteSessionRepository(tmp_path / "s.db")
        repo.save(_session("s1", state="CLARIFYING"))
        assert repo.load("s1").state == "CLARIFYING"
        repo.delete("s1")
        fresh = repo.load("s1")
        assert fresh.state == "IDLE"
        assert fresh.pending_clarification is None


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
