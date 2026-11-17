"""LlmConfig 凭据解析与客户端构造测试(codingPlan AUTH_TOKEN 兼容)。"""

from __future__ import annotations

import pytest

from chatbi.config import LlmConfig
from chatbi.planner.llm import AnthropicLlmClient, LlmConfigError


class TestLlmConfigFromEnv:
    def test_auth_token_fallback_when_api_key_absent(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-1")
        cfg = LlmConfig.from_env()
        assert cfg.api_key is None
        assert cfg.auth_token == "tok-1"

    def test_api_key_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-1")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-1")
        cfg = LlmConfig.from_env()
        assert cfg.api_key == "ak-1"

    def test_model_overridable_via_env(self, monkeypatch):
        monkeypatch.setenv("CHATBI_LLM_MODEL", "doubao-seed-2-1-turbo")
        cfg = LlmConfig.from_env()
        assert cfg.model == "doubao-seed-2-1-turbo"


class TestAnthropicLlmClientConstruction:
    def test_raises_when_neither_credential_set(self):
        cfg = LlmConfig(api_key=None, auth_token=None)
        with pytest.raises(LlmConfigError):
            AnthropicLlmClient(cfg)

    def test_accepts_auth_token_only(self):
        client = AnthropicLlmClient(LlmConfig(auth_token="tok-1"))
        assert client._config.auth_token == "tok-1"

    def test_accepts_api_key_only(self):
        client = AnthropicLlmClient(LlmConfig(api_key="ak-1"))
        assert client._config.api_key == "ak-1"


class TestDeterministicPlanning:
    def test_default_temperature_is_zero(self):
        # 规划必须确定性:同问题同计划(PoC 基线复现的前提)
        cfg = LlmConfig.from_env()
        assert cfg.temperature == 0.0
