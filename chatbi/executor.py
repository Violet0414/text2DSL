"""查询执行层:已校验 SQL → wren CLI 执行 → JSONL 解析(实测事实 #4)。

失败分类(FR-A5 降级矩阵):timeout / cli_error / parse_error;空集是成功结果
(零行),由应答层负责给出"明确解释+建议"。
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

EXECUTION_TIMEOUT_S = 6.0
DEFAULT_ROW_LIMIT = 1000


@dataclass(frozen=True)
class ExecutionResult:
    """一次执行的结果快照(JSONL 解析后)。"""

    is_ok: bool
    columns: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    row_count: int = 0
    roles: dict[str, str] = field(default_factory=dict)
    error_class: str | None = None
    error_message: str | None = None


Runner = Callable[..., subprocess.CompletedProcess]


class WrenCliExecutor:
    """经 wren CLI 执行治理门内 SQL。runner 可注入(测试替身)。"""

    EXECUTION_TIMEOUT_S = EXECUTION_TIMEOUT_S

    def __init__(
        self,
        runner: Runner | None = None,
        wren_bin: str = "wren",
        project_dir: str | None = None,
    ):
        self._runner = runner or subprocess.run
        self._wren_bin = wren_bin
        self._project_dir = project_dir

    def execute(
        self,
        sql: str,
        limit: int = DEFAULT_ROW_LIMIT,
        cube_query: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute one governed query; returns parsed JSONL rows or failure class."""
        argv = [self._wren_bin, "--sql", sql, "-o", "json", "--limit", str(limit)]
        try:
            proc = self._runner(
                argv, capture_output=True, text=True, timeout=EXECUTION_TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                is_ok=False,
                error_class="timeout",
                error_message=f"执行超时(>{EXECUTION_TIMEOUT_S}s)",
            )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()[:500]
            return ExecutionResult(
                is_ok=False, error_class="cli_error", error_message=msg
            )
        rows, parse_error = _parse_jsonl(proc.stdout)
        if parse_error:
            return ExecutionResult(
                is_ok=False, error_class="parse_error", error_message=parse_error
            )
        columns = tuple(rows[0].keys()) if rows else ()
        return ExecutionResult(
            is_ok=True,
            columns=columns,
            rows=tuple(rows),
            row_count=len(rows),
            roles=derive_roles(cube_query) if cube_query else {},
        )


def _parse_jsonl(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """Parse JSONL (one JSON object per line, NOT an array)."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return [], f"invalid jsonl line: {exc}"
        if not isinstance(obj, dict):
            return [], f"jsonl line is not an object: {line[:100]}"
        rows.append(obj)
    return rows, None


def derive_roles(cube_query: dict[str, Any]) -> dict[str, str]:
    """FR-E4 结果契约角色映射:measure/dimension/time。"""
    roles: dict[str, str] = {}
    for m in cube_query.get("measures") or []:
        roles[m] = "measure"
    for d in cube_query.get("dimensions") or []:
        roles[d] = "dimension"
    for td in cube_query.get("timeDimensions") or []:
        roles[td.get("dimension", "")] = "time"
    return roles
