"""结果准确率验证:cube query 执行数字 vs 人工 SQL 基准(受控口径天然唯一)。

覆盖 4 类代表性场景:单指标+时间、比率型 measure(refund_rate)、
维度筛选(filter)、Top-N(orderBy+limit)。全部使用半开区间 [start, end)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys_path_parent = str(Path(__file__).resolve().parent.parent)
if sys_path_parent not in sys.path:
    sys.path.insert(0, sys_path_parent)

from wren_core import cube_query_to_sql  # noqa: E402

from planner.schema import load_mdl  # noqa: E402

MDL_PATH = Path(__file__).resolve().parent.parent / "wren_poc" / "target" / "mdl.json"

# (场景名, CubeQuery dict, 人工基准 SQL)
CASES = [
    (
        "单指标+时间",
        {"cube": "sales", "measures": ["order_count"],
         "timeDimensions": [{"dimension": "order_date", "dateRange": ["2025-10-01", "2025-11-01"], "granularity": "year"}]},
        'SELECT COUNT(DISTINCT order_id) FROM orders WHERE order_date >= \'2025-10-01\' AND order_date < \'2025-11-01\'',
    ),
    (
        "比率型 measure(退款率)",
        {"cube": "sales", "measures": ["refund_rate"],
         "timeDimensions": [{"dimension": "order_date", "dateRange": ["2025-01-01", "2026-01-01"], "granularity": "year"}]},
        "SELECT SUM(CASE WHEN order_status = '已退款' THEN amount ELSE 0 END) / NULLIF(SUM(amount), 0) "
        "FROM orders WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'",
    ),
    (
        "维度筛选(华南已完成的客单价)",
        {"cube": "sales", "measures": ["avg_order_value"],
         "filters": [{"dimension": "region", "operator": "eq", "value": "华南"},
                     {"dimension": "order_status", "operator": "eq", "value": "已完成"}],
         "timeDimensions": [{"dimension": "order_date", "dateRange": ["2026-01-01", "2026-11-01"], "granularity": "year"}]},
        "SELECT AVG(amount) FROM orders WHERE region = '华南' AND order_status = '已完成' "
        "AND order_date >= '2026-01-01' AND order_date < '2026-11-01'",
    ),
    (
        "Top-N(营收前3渠道,2025全年)",
        {"cube": "sales", "measures": ["sales_amount"], "dimensions": ["channel"],
         "orderBy": [{"member": "sales_amount", "direction": "desc"}], "limit": 3,
         "timeDimensions": [{"dimension": "order_date", "dateRange": ["2025-01-01", "2026-01-01"], "granularity": "year"}]},
        "SELECT channel, SUM(amount) AS amt FROM orders WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01' "
        "GROUP BY channel ORDER BY amt DESC LIMIT 3",
    ),
]


def main() -> None:
    from wren.cli import _build_engine

    mdl_json = json.dumps(load_mdl(MDL_PATH), ensure_ascii=False)
    data_dir = MDL_PATH.parent.parent / "data"
    conn_json = json.dumps({"datasource": "duckdb", "url": str(data_dir), "format": "duckdb"})
    all_ok = True
    with _build_engine(str(MDL_PATH), conn_json, None) as engine:
        for name, cq, baseline_sql in CASES:
            sql = cube_query_to_sql(json.dumps(cq, ensure_ascii=False), mdl_json)
            got = engine.query(sql).to_pydict()
            base = engine.query(baseline_sql).to_pydict()
            # 取最后一个数值列(measure 列),跳过 DATE_TRUNC 时间列
            if name.startswith("Top-N"):
                got_rows = sorted(zip(got["channel"], [round(v, 2) for v in got["sales_amount"]]))
                base_rows = sorted(zip(base["channel"], [round(v, 2) for v in base["amt"]]))
                ok = got_rows == base_rows
                print(f"[{'PASS' if ok else 'FAIL'}] {name}\n  cube  : {got_rows}\n  manual: {base_rows}")
            else:
                measure_col = [k for k, v in got.items() if v and isinstance(v[0], (int, float))][-1]
                got_vals = [round(float(v), 4) for v in got[measure_col]]
                base_vals = [round(float(v), 4) for v in list(base.values())[-1]]
                ok = got_vals == base_vals
                print(f"[{'PASS' if ok else 'FAIL'}] {name}\n  cube  : {got_vals}\n  manual: {base_vals}")
            all_ok = all_ok and ok
    print("\n结果准确率:", "100% — 全部一致" if all_ok else "存在偏差,须归因")


if __name__ == "__main__":
    main()
