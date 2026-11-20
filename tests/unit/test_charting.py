"""图表模块测试:推荐权重表 V0.1(移植自民政数据报表工作流)+ ECharts option 组装。"""

from __future__ import annotations

from chatbi.charting import build_chart_option, recommend_charts

ROWS_TIME = (
    {"order_date__month": "2026-01", "sales_amount": 100},
    {"order_date__month": "2026-02", "sales_amount": 130},
    {"order_date__month": "2026-03", "sales_amount": 90},
)
COLS_TIME = ("order_date__month", "sales_amount")

ROWS_CATEGORY = (
    {"channel": "电商", "sales_amount": 474.3},
    {"channel": "门店", "sales_amount": 589.5},
    {"channel": "小程序", "sales_amount": 918.4},
    {"channel": "app", "sales_amount": 1035.7},
)
COLS_CATEGORY = ("channel", "sales_amount")


class TestRecommendCharts:
    def test_time_trend_semantics_prefers_line(self):
        opts = recommend_charts("营收逐月趋势如何", ROWS_TIME, COLS_TIME)
        assert opts[0].type == "line"

    def test_share_semantics_few_categories_prefers_pie(self):
        opts = recommend_charts("各渠道营收占比", ROWS_CATEGORY, COLS_CATEGORY)
        assert opts[0].type == "pie"

    def test_many_categories_excludes_pie(self):
        rows = tuple({"region": f"R{i}", "amount": i} for i in range(15))
        cols = ("region", "amount")
        opts = recommend_charts("各区县数量分布", rows, cols)
        assert all(o.type != "pie" for o in opts)

    def test_user_named_chart_takes_priority(self):
        opts = recommend_charts("用饼图展示各渠道营收", ROWS_CATEGORY, COLS_CATEGORY)
        assert opts[0].type == "pie"

    def test_option_fields_complete(self):
        opts = recommend_charts("各渠道营收对比", ROWS_CATEGORY, COLS_CATEGORY)
        assert len(opts) == 3
        for o in opts:
            assert o.type in ("bar", "line", "pie")
            assert o.label
            assert o.purpose


class TestBuildChartOption:
    def test_bar_option_shape(self):
        option = build_chart_option(ROWS_CATEGORY, COLS_CATEGORY, "bar", "各渠道营收")
        assert option is not None
        assert option["xAxis"]["data"] == ["电商", "门店", "小程序", "app"]
        assert option["series"][0]["type"] == "bar"
        assert option["series"][0]["data"] == [474.3, 589.5, 918.4, 1035.7]

    def test_pie_option_shape_and_truncation(self):
        rows = tuple({"region": f"R{i}", "amount": i} for i in range(12))
        option = build_chart_option(rows, ("region", "amount"), "pie", "各区县数量")
        assert option is not None
        pie_data = option["series"][0]["data"]
        assert len(pie_data) == 8  # 饼图最多 8 行(工作流 MAX_ROWS_IN_PIE)
        assert pie_data[0]["name"] == "R0"

    def test_bar_truncates_at_15_rows(self):
        rows = tuple({"region": f"R{i}", "amount": i} for i in range(20))
        option = build_chart_option(rows, ("region", "amount"), "bar", "各区县")
        assert len(option["xAxis"]["data"]) == 15

    def test_no_numeric_column_returns_none(self):
        rows = ({"channel": "电商"}, {"channel": "门店"})
        assert build_chart_option(rows, ("channel",), "bar", "渠道") is None

    def test_invalid_type_falls_back_to_bar(self):
        option = build_chart_option(ROWS_CATEGORY, COLS_CATEGORY, "radar", "营收")
        assert option["series"][0]["type"] == "bar"

    def test_non_numeric_values_map_to_zero(self):
        rows = ({"channel": "电商", "amount": "12.5"}, {"channel": "门店", "amount": "-"})
        option = build_chart_option(rows, ("channel", "amount"), "bar", "营收")
        assert option["series"][0]["data"] == [12.5, 0]
