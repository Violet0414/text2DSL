"""v1 最简鉴权(FR-C5 前置 / W0):单管理员账号 + Bearer token。

- 口令来源:环境变量 CHATBI_ADMIN_PASSWORD;未设置时回退开发默认值并告警,
  生产部署必须显式设置(M2 RLS 角色表就绪后本模块整体替换)。
- token 为内存态 UUID,服务重启即失效(重新登录即可);不做刷新链,
  /auth/refresh 返回 401 由前端回到登录页。
- vben 契约端点响应格式 {code, data, errorMessage},与 chatbi 统一信封是显式边界。
"""

from __future__ import annotations

import logging
import os
import uuid

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

ADMIN_USERNAME = "chatbi"
DEV_FALLBACK_PASSWORD = "chatbi-dev"  # 仅限本地开发;生产必须设置 CHATBI_ADMIN_PASSWORD
BEARER_PREFIX = "Bearer "


def admin_password() -> str:
    value = os.environ.get("CHATBI_ADMIN_PASSWORD")
    if not value:
        logger.warning(
            "CHATBI_ADMIN_PASSWORD 未设置,使用开发默认口令;生产部署必须显式设置"
        )
        return DEV_FALLBACK_PASSWORD
    return value


class TokenStore:
    """内存态 token 发放与校验(无过期;重启失效)。"""

    def __init__(self) -> None:
        self._tokens: set[str] = set()

    def issue(self) -> str:
        token = uuid.uuid4().hex
        self._tokens.add(token)
        return token

    def validate(self, token: str) -> bool:
        return token in self._tokens

    def revoke(self, token: str) -> None:
        self._tokens.discard(token)


def bearer_token(request: Request) -> str:
    """从 Authorization 头提取 Bearer token;缺失/格式错误 → 401。"""
    header = request.headers.get("Authorization", "")
    if not header.startswith(BEARER_PREFIX):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    token = header[len(BEARER_PREFIX) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="token 为空")
    return token


def require_user(request: Request, tokens: TokenStore) -> str:
    """鉴权依赖:校验 Bearer token,返回已认证用户名;无效 → 401。"""
    token = bearer_token(request)
    if not tokens.validate(token):
        raise HTTPException(status_code=401, detail="token 无效或已失效")
    return ADMIN_USERNAME
