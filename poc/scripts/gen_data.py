"""Generate synthetic sales-order data into a DuckDB file for the PoC.

Baseline schema (PoC评测方案 §三): 订单宽表
  order_id / channel / region / category / amount(不含税) /
  amount_with_tax(含税) / order_status / order_date

All values are synthetic. Date range spans 2024-01-01 .. 2026-11-15 so that
同比 / 环比 / 去年同期 questions have real baselines.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import duckdb

DATA_DIR = Path(__file__).resolve().parent.parent / "wren_poc" / "data"
DB_PATH = DATA_DIR / "sales.duckdb"

CHANNELS = ["app", "小程序", "门店", "电商"]
REGIONS = ["华东", "华北", "华南", "西南"]
CATEGORIES = ["数码", "家居", "服饰", "食品"]
STATUSES = ["已完成", "已退款", "待发货"]
# 权重:已完成为主,退款率约 8%(支撑 refund_rate = 已退款金额占比)
STATUS_WEIGHTS = [0.85, 0.08, 0.07]

START_DATE = date(2024, 1, 1)
END_DATE = date(2026, 11, 15)
N_ROWS = 60_000
SEED = 42


def gen_rows() -> list[tuple]:
    """Generate deterministic synthetic order rows (date asc)."""
    rng = random.Random(SEED)
    span_days = (END_DATE - START_DATE).days
    # 缓慢增长的业务量:日均订单数随时间线性增长,制造同比/环比可感知的趋势
    rows: list[tuple] = []
    order_seq = 0
    for day_offset in range(span_days + 1):
        d = START_DATE + timedelta(days=day_offset)
        progress = day_offset / span_days
        daily_orders = int(40 + 60 * progress)  # 40 → 100 单/天
        for _ in range(daily_orders):
            order_seq += 1
            amount = round(rng.uniform(20, 2000), 2)
            rows.append(
                (
                    f"SO{order_seq:08d}",
                    rng.choices(CHANNELS, weights=[0.35, 0.3, 0.2, 0.15])[0],
                    rng.choices(REGIONS, weights=[0.4, 0.25, 0.2, 0.15])[0],
                    rng.choices(CATEGORIES, weights=[0.3, 0.25, 0.25, 0.2])[0],
                    amount,
                    round(amount * 1.13, 2),
                    rng.choices(STATUSES, weights=STATUS_WEIGHTS)[0],
                    d.isoformat(),
                )
            )
    return rows


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = gen_rows()
    con = duckdb.connect(str(DB_PATH))
    con.execute(
        """
        CREATE OR REPLACE TABLE main.orders (
            order_id        VARCHAR,
            channel         VARCHAR,
            region          VARCHAR,
            category        VARCHAR,
            amount          DOUBLE,
            amount_with_tax DOUBLE,
            order_status    VARCHAR,
            order_date      DATE
        )
        """
    )
    con.executemany("INSERT INTO main.orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    total = con.execute("SELECT COUNT(*), SUM(amount) FROM main.orders").fetchone()
    con.close()
    print(f"orders rows={total[0]} sales_amount={total[1]:.2f} -> {DB_PATH}")


if __name__ == "__main__":
    main()
