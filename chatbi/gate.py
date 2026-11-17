"""治理门禁每请求实时校验(FR-D4):已确认 + 试运行通过 + 工具启用 + 描述齐备。

M1 数据源:门禁配置文件(仓库内 JSON;M4 治理平台对接后换 Repository 实现)。
安全默认:门禁仓库未登记的指标一律拒绝。
状态每请求实时读取 → 门禁状态变更后查询立即失效。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GATE_CONFIG_PATH = REPO_ROOT / "chatbi" / "gate_config.json"

DOOR_NAMES = ("confirmed", "trial_passed", "tool_enabled")


@dataclass(frozen=True)
class GateVerdict:
    """门禁校验结论:passed=False 时 denied/reasons 给出逐成员原因。"""

    passed: bool
    denied: tuple[str, ...] = ()
    reasons: dict[str, str] = field(default_factory=dict)


class GateStateRepository(Protocol):
    """门禁状态仓库协议(M4 由治理平台对接实现替换)。"""

    def get_flags(self) -> dict[str, dict[str, bool]]: ...


class FileGateStateRepository:
    """从门禁配置 JSON 读取每指标三旗标(第四门"描述齐备"由 MDL 派生)。"""

    def __init__(self, config_path: str | Path | None = None):
        self._path = Path(
            config_path
            or os.environ.get("CHATBI_GATE_CONFIG")
            or DEFAULT_GATE_CONFIG_PATH
        )

    def get_flags(self) -> dict[str, dict[str, bool]]:
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return {name: dict(flags) for name, flags in data.items()}


class GovernanceGate:
    def __init__(self, repo: GateStateRepository, mdl: dict):
        self._repo = repo
        self._descriptions = {}
        for cube in mdl.get("cubes") or []:
            for m in cube.get("measures") or []:
                desc = (m.get("properties") or {}).get("description", "")
                self._descriptions[m["name"]] = desc.strip()

    def check_query(self, cube_query: dict) -> GateVerdict:
        """校验 cube_query 中全部 measure 的四门状态。"""
        flags_by_metric = self._repo.get_flags()
        denied: list[str] = []
        reasons: dict[str, str] = {}
        for measure in cube_query.get("measures") or []:
            flags = flags_by_metric.get(measure)
            if flags is None:
                denied.append(measure)
                reasons[measure] = "unregistered(门禁仓库未登记,安全默认拒绝)"
                continue
            for door in DOOR_NAMES:
                if not flags.get(door, False):
                    denied.append(measure)
                    reasons[measure] = f"{door}=false(门禁未开)"
            if not self._descriptions.get(measure, ""):
                denied.append(measure)
                reasons[measure] = "description=empty(描述不齐备)"
        if not denied:
            return GateVerdict(passed=True)
        return GateVerdict(passed=False, denied=tuple(denied), reasons=reasons)


def check_description_door(mdl: dict) -> dict[str, bool]:
    """派生第四门:measure 描述非空即为齐备。诊断辅助函数。"""
    result = {}
    for cube in mdl.get("cubes") or []:
        for m in cube.get("measures") or []:
            result[m["name"]] = bool(
                (m.get("properties") or {}).get("description", "").strip()
            )
    return result
