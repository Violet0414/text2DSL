"""API 信封契约测试:POST /api/ask 统一信封(PRD §5.2)。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from chatbi.api import create_app


@dataclass(frozen=True)
class FakePayload:
    type: str = "reply"
    text: str = "你好"


class FakePipe:
    def __init__(self, behavior="ok"):
        self.behavior = behavior
        self.calls: list[tuple[str, str]] = []

    def ask(self, session_id: str, question: str):
        self.calls.append((session_id, question))
        if self.behavior == "raise":
            raise RuntimeError("boom")
        return FakePayload()


def _client(pipe=None) -> TestClient:
    return TestClient(create_app(pipeline=pipe or FakePipe()))


class TestEnvelope:
    def test_ask_returns_unified_envelope(self):
        pipe = FakePipe()
        resp = _client(pipe).post("/api/ask", json={"sessionId": "s1", "question": "hi"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["type"] == "reply"
        assert body["error"] is None
        assert body["meta"]["traceId"]
        assert isinstance(body["meta"]["latencyMs"], int)

    def test_session_id_and_question_forwarded_to_pipeline(self):
        pipe = FakePipe()
        _client(pipe).post("/api/ask", json={"sessionId": "s9", "question": "上个月营收"})
        assert pipe.calls == [("s9", "上个月营收")]

    def test_pipeline_exception_maps_to_error_envelope(self):
        resp = _client(FakePipe(behavior="raise")).post(
            "/api/ask", json={"sessionId": "s1", "question": "hi"}
        )
        body = resp.json()
        assert body["success"] is False
        assert body["data"] is None
        assert body["error"]["code"]
        assert body["error"]["message"]

    def test_missing_fields_rejected(self):
        resp = _client().post("/api/ask", json={"question": "hi"})
        assert resp.status_code == 422

    def test_healthz(self):
        assert _client().get("/healthz").json()["status"] == "ok"
