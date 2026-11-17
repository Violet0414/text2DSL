"""Anthropic 兼容 API 封装:工具强制结构化输出,解析失败时 JSON 修复回退。

注意:ANTHROPIC_BASE_URL 代理后端实测为 doubao-seed-2-1-turbo;
模型名经代理映射,规划器 LLM 可替换,PoC 报告须如实记录实测模型。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from anthropic import Anthropic

from chatbi.config import LlmConfig

MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 2048


class LlmClient(Protocol):
    """规划器 LLM 客户端协议:测试注入 Fake,生产注入 AnthropicLlmClient。"""

    def call(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tool_schema: dict[str, Any] | None,
    ) -> LlmCall: ...


class LlmConfigError(RuntimeError):
    """LLM 配置不完整(appkey 未填)时抛出,构造期 fail fast。"""


class AnthropicLlmClient:
    """Anthropic 兼容实现:凭据/模型/base_url 全部来自 LlmConfig(环境变量)。

    凭据二选一:codingPlan 的 ANTHROPIC_AUTH_TOKEN(Bearer)或标准 ANTHROPIC_API_KEY
    (x-api-key);二者皆缺则构造期 fail fast。
    """

    def __init__(self, config: LlmConfig):
        if not config.api_key and not config.auth_token:
            raise LlmConfigError(
                "LLM 凭据未配置:请设置 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN 环境变量。"
            )
        self._config = config
        client_kwargs: dict[str, Any] = {"base_url": config.base_url}
        if config.api_key:
            client_kwargs["api_key"] = config.api_key
        else:
            client_kwargs["auth_token"] = config.auth_token
        self._client = Anthropic(**client_kwargs)

    def call(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tool_schema: dict[str, Any] | None,
    ) -> LlmCall:
        """Call the LLM; when tool_schema given, force the 'plan' tool for output."""
        started = time.monotonic()
        error: str | None = None
        tool_input: dict[str, Any] | None = None
        text = ""
        try:
            kwargs: dict[str, Any] = {
                "model": self._config.model,
                "max_tokens": self._config.max_tokens,
                "temperature": self._config.temperature,
                "system": system,
                "messages": messages,
            }
            if tool_schema is not None:
                kwargs["tools"] = [
                    {
                        "name": "plan",
                        "description": "输出受控问数规划结果(行为分支 + cube query 参数)",
                        "input_schema": tool_schema,
                    }
                ]
                kwargs["tool_choice"] = {"type": "tool", "name": "plan"}
            resp = self._client.messages.create(**kwargs)
            tool_input = _extract_tool_input(resp)
            text = _extract_text(resp) or (
                json.dumps(tool_input, ensure_ascii=False) if tool_input else ""
            )
        except Exception as exc:  # noqa: BLE001 — 统一归因为调用失败,由上层修复回退
            error = f"{type(exc).__name__}: {exc}"
        return LlmCall(
            model=self._config.model,
            output_text=text,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=error,
        )


@dataclass(frozen=True)
class LlmCall:
    """单次 LLM 调用的输入输出快照(落盘可回放,对应评测方案 §7.5)。"""

    model: str
    output_text: str
    latency_ms: int
    error: str | None = None


def _extract_tool_input(resp: Any) -> dict[str, Any] | None:
    """Pull the first tool_use block's input dict from a response, if any."""
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            return block.input
    return None


def _extract_text(resp: Any) -> str:
    """Concatenate all text blocks of a response."""
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def call_llm(
    system: str,
    messages: list[dict[str, Any]],
    tool_schema: dict[str, Any] | None,
) -> LlmCall:
    """Call the LLM; when tool_schema given, force the 'plan' tool for output."""
    client = Anthropic()
    started = time.monotonic()
    error: str | None = None
    tool_input: dict[str, Any] | None = None
    text = ""
    try:
        kwargs: dict[str, Any] = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": messages,
        }
        if tool_schema is not None:
            kwargs["tools"] = [
                {
                    "name": "plan",
                    "description": "输出受控问数规划结果(行为分支 + cube query 参数)",
                    "input_schema": tool_schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": "plan"}
        resp = client.messages.create(**kwargs)
        tool_input = _extract_tool_input(resp)
        text = _extract_text(resp) or (
            json.dumps(tool_input, ensure_ascii=False) if tool_input else ""
        )
    except Exception as exc:  # noqa: BLE001 — 统一归因为调用失败,由上层修复回退
        error = f"{type(exc).__name__}: {exc}"
    return LlmCall(
        model=MODEL,
        output_text=text,
        latency_ms=int((time.monotonic() - started) * 1000),
        error=error,
    )


def parse_json_loose(text: str) -> dict[str, Any] | None:
    """Parse planner output text; tolerate fenced/before-after prose JSON."""
    if not text.strip():
        return None
    candidates = [text]
    stripped = text.strip()
    if stripped.startswith("```"):
        candidates.append(stripped.strip("`").lstrip("json").strip())
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None
