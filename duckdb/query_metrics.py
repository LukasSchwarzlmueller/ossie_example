"""Answer a semantic query directly against DuckDB, with no conversion step.

Unlike the other targets in this repo, nothing is exported here. The `ossie`
community extension reads duckdb/ossie/orders_customers.yaml and compiles the
request to SQL itself, so the model is the only artifact.

    uv run duckdb/query_metrics.py                 # build demo tables, then query
    uv run duckdb/query_metrics.py --sql           # print the generated SQL instead
    uv run duckdb/query_metrics.py --db demo.duckdb  # leave a file to open elsewhere

Needs duckdb==1.5.5 exactly: the community extension is built per DuckDB
version and only v1.5.5 has an `ossie` build (see README.md).
"""

import argparse
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
MODEL = HERE / "ossie" / "orders_customers.yaml"

METRICS = ["total_revenue", "avg_order_value", "order_count"]
DIMENSIONS = ["customers.customer_segment"]

CUSTOMERS = """
CREATE OR REPLACE TABLE customers AS SELECT * FROM (VALUES
    (1, 'Alice Anders', 'enterprise'),
    (2, 'Bob Baker', 'smb'),
    (3, 'Carol Chen', 'enterprise')
) AS t(customer_id, customer_name, customer_segment)
"""

ORDERS = """
CREATE OR REPLACE TABLE orders AS SELECT * FROM (VALUES
    (101, 1, DATE'2026-01-05', 250.00),
    (102, 1, DATE'2026-02-10', 90.50),
    (103, 2, DATE'2026-02-11', 40.00),
    (104, 3, DATE'2026-03-01', 610.25)
) AS t(order_id, customer_id, order_date, order_amount)
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sql", action="store_true", help="print the compiled SQL instead of running it"
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="persist to a database file instead of memory, so any DuckDB "
        "client can open it (gitignored; needs DuckDB 1.5.5 to LOAD ossie)",
    )
    args = parser.parse_args()

    con = duckdb.connect(args.db) if args.db else duckdb.connect()
    con.execute("INSTALL ossie FROM community;")
    con.execute("LOAD ossie;")
    con.execute(CUSTOMERS)
    con.execute(ORDERS)

    name, version, datasets, fields, rels, metrics = con.execute(
        "SELECT * FROM ossie_load(?)", [str(MODEL)]
    ).fetchone()
    print(
        f"loaded {name} ({version}): {datasets} datasets, {fields} fields, "
        f"{rels} relationship(s), {metrics} metrics"
    )

    if args.sql:
        sql = con.execute(
            "SELECT ossie_compile(?, ?, ?)", [METRICS, DIMENSIONS, []]
        ).fetchone()[0]
        print()
        print(sql)
        return

    rows = con.execute(
        "SELECT * FROM ossie_query(?, ?)", [METRICS, DIMENSIONS]
    ).fetchall()
    print()
    print(f"{'customer_segment':<18}{'total_revenue':>15}{'avg_order_value':>18}{'order_count':>14}")
    for segment, revenue, aov, count in rows:
        print(f"{segment:<18}{revenue:>15}{aov:>18.3f}{count:>14}")


if __name__ == "__main__":
    main()
