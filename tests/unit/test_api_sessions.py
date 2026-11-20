"""会话列表/历史回看端点 + vben 登录契约适配端点测试(FR-C5 / W0)。

纪律:chatbi 业务端点走统一信封 {success,data,error,meta};
vben 框架适配端点(/api/auth/*,/api/user/info)走 vben 契约 {code,data,errorMessage},
两者是显式边界,不混用。
"""

from __future__ import annotations

import json

from dataclasses import dataclass

from fastapi.testclient import TestClient

from chatbi.api import create_app
from chatbi.store.memory import InMemorySessionRepository
from chatbi.store.sqlite import SqliteMessageRepository


@dataclass(frozen=True)
class FakePayload:
    type: str = "answer"
    text: str = "口径数据"


class FakePipe:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def ask(self, session_id: str, question: str):
        self.calls.append((session_id, question))
        return FakePayload()


def _client(tmp_path, pipe=None) -> TestClient:
    store = SqliteMessageRepository(tmp_path / "msg.db")
    app = create_app(
        pipeline=pipe or FakePipe(),
        message_store=store,
        session_store=InMemorySessionRepository(),
    )
    return TestClient(app)


def _login(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/login",
        json={"username": "chatbi", "password": "chatbi-dev"},
    )
    assert resp.json()["code"] == 0
    return resp.json()["data"]["accessToken"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestAuthAdapter:
    """vben 登录契约:{code,data,errorMessage},口令走环境变量。"""

    def test_login_ok_returns_access_token(self, tmp_path):
        client = _client(tmp_path)
        resp = client.post(
            "/api/auth/login",
            json={"username": "chatbi", "password": "chatbi-dev"},
        )
        body = resp.json()
        assert resp.status_code == 200
        assert body["code"] == 0
        assert body["data"]["accessToken"]

    def test_login_wrong_password_rejected(self, tmp_path):
        client = _client(tmp_path)
        resp = client.post(
            "/api/auth/login",
            json={"username": "chatbi", "password": "bad"},
        )
        body = resp.json()
        assert resp.status_code == 200
        assert body["code"] != 0
        assert body["errorMessage"]

    def test_login_honors_env_password(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHATBI_ADMIN_PASSWORD", "s3cret-env")
        client = _client(tmp_path)
        ok = client.post(
            "/api/auth/login",
            json={"username": "chatbi", "password": "s3cret-env"},
        )
        bad = client.post(
            "/api/auth/login",
            json={"username": "chatbi", "password": "chatbi-dev"},
        )
        assert ok.json()["code"] == 0
        assert bad.json()["code"] != 0

    def test_user_info_requires_bearer_token(self, tmp_path):
        client = _client(tmp_path)
        assert client.get("/api/user/info").status_code == 401
        token = _login(client)
        resp = client.get("/api/user/info", headers=_auth_header(token))
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["username"] == "chatbi"
        assert body["data"]["roles"]

    def test_access_codes_returns_list(self, tmp_path):
        client = _client(tmp_path)
        token = _login(client)
        resp = client.get("/api/auth/codes", headers=_auth_header(token))
        assert resp.json()["code"] == 0
        assert isinstance(resp.json()["data"], list)

    def test_logout_revokes_token(self, tmp_path):
        client = _client(tmp_path)
        token = _login(client)
        resp = client.post("/api/auth/logout", headers=_auth_header(token))
        assert resp.json()["code"] == 0
        assert client.get("/api/user/info", headers=_auth_header(token)).status_code == 401


class TestSessionList:
    """GET /api/sessions:统一信封,会话摘要含标题(首轮问题截断)。"""

    def test_empty_sessions(self, tmp_path):
        client = _client(tmp_path)
        resp = client.get(
            "/api/sessions", headers=_auth_header(_login(client))
        )
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["sessions"] == []

    def test_ask_creates_session_summary(self, tmp_path):
        client = _client(tmp_path, pipe=FakePipe())
        client.post("/api/ask", json={"sessionId": "s1", "question": "上个月各渠道营收是多少呢"})
        resp = client.get("/api/sessions", headers=_auth_header(_login(client)))
        body = resp.json()
        assert body["success"] is True
        sessions = body["data"]["sessions"]
        assert len(sessions) == 1
        s = sessions[0]
        assert s["sessionId"] == "s1"
        assert s["messageCount"] == 2  # user + assistant
        assert s["title"].startswith("上个月")
        assert s["updatedAt"]

    def test_sessions_require_auth(self, tmp_path):
        client = _client(tmp_path)
        assert client.get("/api/sessions").status_code == 401


class TestSessionHistory:
    """GET /api/sessions/{id}/history:全量消息回放,含 traceId 锚点。"""

    def test_history_records_user_and_assistant(self, tmp_path):
        client = _client(tmp_path, pipe=FakePipe())
        client.post("/api/ask", json={"sessionId": "s1", "question": "本月销售额"})
        resp = client.get(
            "/api/sessions/s1/history", headers=_auth_header(_login(client))
        )
        body = resp.json()
        assert body["success"] is True
        messages = body["data"]["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["payload"]["text"] == "本月销售额"
        assert messages[1]["payload"]["type"] == "answer"
        assert messages[1]["traceId"], "assistant 消息必须带 traceId 回放锚点"

    def test_history_preserves_order_across_rounds(self, tmp_path):
        client = _client(tmp_path, pipe=FakePipe())
        client.post("/api/ask", json={"sessionId": "s1", "question": "第一问"})
        client.post("/api/ask", json={"sessionId": "s1", "question": "第二问"})
        resp = client.get(
            "/api/sessions/s1/history", headers=_auth_header(_login(client))
        )
        messages = resp.json()["data"]["messages"]
        assert [m["payload"]["text"] for m in messages if m["role"] == "user"] == [
            "第一问",
            "第二问",
        ]

    def test_history_unknown_session_is_error_envelope(self, tmp_path):
        client = _client(tmp_path)
        resp = client.get(
            "/api/sessions/ghost/history", headers=_auth_header(_login(client))
        )
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    def test_history_requires_auth(self, tmp_path):
        client = _client(tmp_path)
        assert client.get("/api/sessions/s1/history").status_code == 401


class TestSessionDelete:
    """DELETE /api/sessions/{id}:物理删除消息,残留会话状态同步清除。"""

    def test_delete_removes_messages_and_session_summary(self, tmp_path):
        client = _client(tmp_path, pipe=FakePipe())
        client.post("/api/ask", json={"sessionId": "s1", "question": "本月销售额"})
        token = _login(client)
        resp = client.delete("/api/sessions/s1", headers=_auth_header(token))
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["sessionId"] == "s1"
        assert body["data"]["deletedMessages"] == 2  # user + assistant
        listing = client.get("/api/sessions", headers=_auth_header(token))
        assert listing.json()["data"]["sessions"] == []
        history = client.get("/api/sessions/s1/history", headers=_auth_header(token))
        assert history.json()["success"] is False

    def test_delete_unknown_session_is_not_found(self, tmp_path):
        client = _client(tmp_path)
        resp = client.delete(
            "/api/sessions/ghost", headers=_auth_header(_login(client))
        )
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    def test_delete_requires_auth(self, tmp_path):
        client = _client(tmp_path)
        assert client.delete("/api/sessions/s1").status_code == 401


class TestMessageStore:
    """SqliteMessageRepository 直测(仓库协议)。"""

    def test_append_and_history(self, tmp_path):
        repo = SqliteMessageRepository(tmp_path / "m.db")
        repo.append(session_id="a", role="user", payload={"text": "q"})
        repo.append(session_id="a", role="assistant", payload={"type": "answer"}, trace_id="t1")
        msgs = repo.history("a")
        assert len(msgs) == 2
        assert msgs[1].trace_id == "t1"
        assert repo.history("missing") == []

    def test_list_sessions_orders_by_recency(self, tmp_path):
        repo = SqliteMessageRepository(tmp_path / "m.db")
        repo.append(session_id="old", role="user", payload={"text": "旧会话"})
        repo.append(session_id="new", role="user", payload={"text": "新会话"})
        sessions = repo.list_sessions()
        assert [s.session_id for s in sessions] == ["new", "old"]

    def test_payload_json_roundtrip(self, tmp_path):
        repo = SqliteMessageRepository(tmp_path / "m.db")
        payload = {"rows": [{"渠道": "华南", "营收": 123}], "metric": {"name": "营收"}}
        repo.append(session_id="a", role="assistant", payload=payload, trace_id="t")
        msg = repo.history("a")[0]
        assert json.loads(json.dumps(msg.payload)) == payload
