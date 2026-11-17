"""MDL → JSON Schema 枚举白名单生成(K1 主防线)的单元测试。"""

from __future__ import annotations

import pytest

from chatbi.planner.schema import (
    BEHAVIORS,
    TIME_SLOTS,
    cube_members,
    load_mdl,
    planner_tool_schema,
)

MDL_PATH = "/home/mxr/text2DSL/poc/wren_poc/target/mdl.json"

EXPECTED_MEMBERS = {
    "measures": [
        "sales_amount",
        "sales_amount_with_tax",
        "order_count",
        "avg_order_value",
        "refund_rate",
    ],
    "dimensions": ["channel", "region", "category", "order_status"],
    "time_dimensions": ["order_date"],
}


class TestCubeMembers:
    def test_extracts_member_whitelists_from_mdl(self):
        mdl = load_mdl(MDL_PATH)
        members = cube_members(mdl)
        assert "sales" in members
        for key, expected in EXPECTED_MEMBERS.items():
            assert members["sales"][key] == expected


class TestPlannerToolSchema:
    def test_behavior_enum_constrains_four_behaviors(self):
        mdl = load_mdl(MDL_PATH)
        schema = planner_tool_schema(cube_members(mdl))
        assert schema["required"] == ["behavior"]
        assert schema["properties"]["behavior"]["enum"] == BEHAVIORS
        assert set(BEHAVIORS) == {"query", "clarify", "miss", "chitchat"}

    def test_measure_enum_come_from_mdl_whitelist(self):
        mdl = load_mdl(MDL_PATH)
        schema = planner_tool_schema(cube_members(mdl))
        cq = schema["properties"]["cube_query"]["properties"]
        assert set(cq["measures"]["items"]["enum"]) == set(EXPECTED_MEMBERS["measures"])
        assert set(cq["cube"]["enum"]) == {"sales"}
        assert set(cq["dimensions"]["items"]["enum"]) == set(
            EXPECTED_MEMBERS["dimensions"]
        )

    def test_filters_dimension_enum_and_operators(self):
        mdl = load_mdl(MDL_PATH)
        schema = planner_tool_schema(cube_members(mdl))
        filter_props = schema["properties"]["cube_query"]["properties"]["filters"][
            "items"
        ]["properties"]
        assert set(filter_props["dimension"]["enum"]) == set(
            EXPECTED_MEMBERS["dimensions"]
        )
        assert set(filter_props["operator"]["enum"]) == {"eq", "not_eq", "in", "not_in"}

    def test_time_slot_enum_is_fixed_vocabulary(self):
        mdl = load_mdl(MDL_PATH)
        schema = planner_tool_schema(cube_members(mdl))
        cq = schema["properties"]["cube_query"]["properties"]
        assert cq["time"]["properties"]["slot"]["enum"] == TIME_SLOTS
        assert "explicit" in TIME_SLOTS and "yoy" in TIME_SLOTS

    def test_limit_is_bounded(self):
        mdl = load_mdl(MDL_PATH)
        schema = planner_tool_schema(cube_members(mdl))
        limit = schema["properties"]["cube_query"]["properties"]["limit"]
        assert limit["minimum"] == 1 and limit["maximum"] == 100

    def test_missing_mdl_raises(self):
        with pytest.raises(FileNotFoundError):
            load_mdl("/nonexistent/mdl.json")
