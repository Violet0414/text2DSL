"""运行配置:LLM(appkey 后期填入)与 wren 项目路径。

安全纪律:密钥只经环境变量,不落代码;客户端构造时才校验密钥存在。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# M1 默认指向 PoC 语义项目(只读引用 frozen 基线);迁移用 CHATBI_WREN_PROJECT_DIR 覆盖
DEFAULT_WREN_PROJECT_DIR = REPO_ROOT / "poc" / "wren_poc"


@dataclass(frozen=True)
class LlmConfig:
    """规划器 LLM 配置(Q1 定案前用占位模型,appkey 经环境变量填入)。"""

    model: str = "claude-sonnet-5-5"
    max_tokens: int = 2048
    api_key: str | None = None
    base_url: str | None = None

    @classmethod
    def from_env(cls) -> LlmConfig:
        return cls(
            model=os.environ.get("CHATBI_LLM_MODEL", "claude-sonnet-5-5"),
            max_tokens=int(os.environ.get("CHATBI_LLM_MAX_TOKENS", "2048")),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )
