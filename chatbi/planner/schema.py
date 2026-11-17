"""MDL JSON → LLM 输出 JSON Schema 枚举(K1 主防线)。

从 target/mdl.json 提取 cube 成员白名单,生成规划器结构化输出的 JSON Schema,
使 LLM 只能在已注册 measure/dimension/time 维度内选值。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TIME_SLOTS = [
    "today",
    "current_week",
    "current_month",
    "current_quarter",
    "current_year",
    "last_week",
    "week_before_last",
    "last_month",
    "last_quarter",
    "last_7d",
    "last_14d",
    "last_30d",
    "last_3m",
    "same_period_last_year",
    "yoy",
    "mom",
    "explicit",
    "all_time",
]
TIME_GRANULARITIES = ["day", "week", "month", "quarter", "year"]
FILTER_OPERATORS = ["eq", "not_eq", "in", "not_in"]
BEHAVIORS = ["query", "clarify", "miss", "chitchat"]


def load_mdl(mdl_path: str | Path) -> dict[str, Any]:
    """Read the compiled mdl.json build artifact."""
    return json.loads(Path(mdl_path).read_text(encoding="utf-8"))


def cube_members(mdl: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Extract per-cube member whitelists from mdl.json.

    Returns {cube_name: {"measures": [...], "dimensions": [...],
                         "time_dimensions": [...]}}
    """
    members: dict[str, dict[str, list[str]]] = {}
    for cube in mdl.get("cubes") or []:
        members[cube["name"]] = {
            "measures": [m["name"] for m in cube.get("measures") or []],
            "dimensions": [d["name"] for d in cube.get("dimensions") or []],
            "time_dimensions": [t["name"] for t in cube.get("timeDimensions") or []],
        }
    return members


def planner_tool_schema(members: dict[str, dict[str, list[str]]]) -> dict[str, Any]:
    """Build the planner output JSON Schema with enum constraints from mdl.json.

    The enums are the K1 hard constraint source: every measure / dimension /
    time dimension / filter target the LLM may emit comes from the compiled
    MDL, so unregistered members are not expressible in valid output.
    """
    cube_names = list(members.keys())
    all_measures = sorted({m for c in members.values() for m in c["measures"]})
    all_dims = sorted({d for c in members.values() for d in c["dimensions"]})
    order_members = sorted(set(all_measures) | set(all_dims))

    return {
        "type": "object",
        "required": ["behavior"],
        "properties": {
            "behavior": {"type": "string", "enum": BEHAVIORS},
            "clarify_question": {"type": "string"},
            "clarify_options": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "reply": {"type": "string"},
            "cube_query": {
                "type": "object",
                "required": ["cube", "measures"],
                "properties": {
                    "cube": {"type": "string", "enum": cube_names},
                    "measures": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "enum": all_measures},
                    },
                    "dimensions": {
                        "type": "array",
                        "items": {"type": "string", "enum": all_dims},
                    },
                    "time": {
                        "type": "object",
                        "properties": {
                            "slot": {"type": "string", "enum": TIME_SLOTS},
                            "explicit_range": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            "granularity": {
                                "type": "string",
                                "enum": TIME_GRANULARITIES,
                            },
                        },
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["dimension", "operator"],
                            "properties": {
                                "dimension": {"type": "string", "enum": all_dims},
                                "operator": {
                                    "type": "string",
                                    "enum": FILTER_OPERATORS,
                                },
                                "value": {},
                            },
                        },
                    },
                    "orderBy": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["member", "direction"],
                            "properties": {
                                "member": {"type": "string", "enum": order_members},
                                "direction": {
                                    "type": "string",
                                    "enum": ["asc", "desc"],
                                },
                            },
                        },
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
        },
    }
