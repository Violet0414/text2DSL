"""NFR-2 安全设施:用户问题注入防护 + 零数据库凭据启动校验。

纪律:用户问题永远只是数据段(分隔符包裹+分隔符剥除);问数数据链路
只经 WrenAI 治理门,禁止直连数据库凭据进入链路。
"""

from __future__ import annotations

import os

QUESTION_OPEN = "<<<USER_QUESTION>>>"
QUESTION_CLOSE = "<<</USER_QUESTION>>>"

BANNED_CREDENTIAL_KEYS = (
    "DB_PASSWORD",
    "DATABASE_URL",
    "MYSQL_PASSWORD",
    "POSTGRES_PASSWORD",
    "DATA_DB_DSN",
)


class SecurityViolation(RuntimeError):
    """安全约束被违反(启动期 fail fast)。"""


def wrap_user_question(question: str) -> str:
    """把用户问题包裹为数据段:剥除分隔符碰撞后以分隔符包裹。"""
    cleaned = question.replace(QUESTION_OPEN, "").replace(QUESTION_CLOSE, "")
    return f"{QUESTION_OPEN}\n{cleaned.strip()}\n{QUESTION_CLOSE}"


def assert_no_db_credentials(env: dict[str, str] | None = None) -> None:
    """校验问数链路不含直连数据库凭据;存在即抛 SecurityViolation。"""
    source = env if env is not None else dict(os.environ)
    leaked = [k for k in BANNED_CREDENTIAL_KEYS if source.get(k)]
    if leaked:
        raise SecurityViolation(f"问数链路检测到直连数据库凭据: {', '.join(leaked)}")
