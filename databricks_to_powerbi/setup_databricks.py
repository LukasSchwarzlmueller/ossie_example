"""Set up the Databricks side of the trip: demo tables + the Metric View with the filtered measure.

Creates in DATABRICKS_CATALOG.DATABRICKS_SCHEMA (default ossi.test):
  - customers, orders  (same rows as databricks/deploy_to_databricks.py and dbt/models/*.sql)
  - the Metric View DATABRICKS_TRIP_VIEW_NAME (default sales_demo_trip) from metric_view.yaml

Then queries it, so you know every measure (filtered, window) is valid Databricks SQL.

    uv run databricks_to_powerbi/setup_databricks.py            # deploy
    uv run databricks_to_powerbi/setup_databricks.py --dry-run  # only print the SQL
    uv run databricks_to_powerbi/setup_databricks.py --view-only  # tables exist: only the Metric View

Needs DATABRICKS_HOST / DATABRICKS_TOKEN / DATABRICKS_WAREHOUSE_ID in .env (see .env.example).
"""

import argparse
import os

from common.env import REPO_ROOT, load_env_file

HERE = REPO_ROOT / "databricks_to_powerbi"
PLACEHOLDER = "__catalog__.__schema__"

CUSTOMERS = """CREATE OR REPLACE TABLE {q}.customers AS
SELECT * FROM (VALUES
    (1, 'Alice Anders', 'enterprise'),
    (2, 'Bob Baker', 'smb'),
    (3, 'Carol Chen', 'enterprise')
) AS t(customer_id, customer_name, customer_segment)"""
ORDERS = """CREATE OR REPLACE TABLE {q}.orders AS
SELECT * FROM (VALUES
    (101, 1, DATE'2026-01-05', 250.00),
    (102, 1, DATE'2026-02-10', 90.50),
    (103, 2, DATE'2026-02-11', 40.00),
    (104, 3, DATE'2026-03-01', 610.25)
) AS t(order_id, customer_id, order_date, order_amount)"""
VIEW = "CREATE OR REPLACE VIEW {q}.{view} WITH METRICS LANGUAGE YAML AS $$\n{yaml}\n$$"
CHECK = """SELECT customer_segment,
       MEASURE(total_revenue)      AS total_revenue,
       MEASURE(order_count)        AS order_count,
       MEASURE(enterprise_revenue) AS enterprise_revenue
FROM {q}.{view}
GROUP BY customer_segment
ORDER BY customer_segment"""
CHECK_WINDOW = """SELECT order_date, MEASURE(revenue_running_total) AS revenue_running_total
FROM {q}.{view}
GROUP BY order_date
ORDER BY order_date"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print the SQL, don't connect")
    parser.add_argument("--view-only", action="store_true",
                        help="tables already exist: only create the Metric View and query it")
    args = parser.parse_args()

    load_env_file()
    catalog = os.environ.get("DATABRICKS_CATALOG", "ossi")
    schema = os.environ.get("DATABRICKS_SCHEMA", "test")
    view = os.environ.get("DATABRICKS_TRIP_VIEW_NAME", "sales_demo_trip")
    q = f"{catalog}.{schema}"
    view_yaml = (HERE / "metric_view.yaml").read_text().replace(PLACEHOLDER, q)

    statements = [
        *([] if args.view_only else [("tables", CUSTOMERS.format(q=q)), ("", ORDERS.format(q=q))]),
        (f"Metric View {q}.{view}", VIEW.format(q=q, view=view, yaml=view_yaml)),
        ("check query", CHECK.format(q=q, view=view)),
        ("check query", CHECK_WINDOW.format(q=q, view=view)),
    ]

    if args.dry_run:
        for _, sql in statements:
            print(sql + ";\n")
        return

    from databricks.sdk import WorkspaceClient  # only needed for a real run

    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not warehouse_id:
        raise SystemExit("DATABRICKS_WAREHOUSE_ID not set - is it in .env?")
    w = WorkspaceClient()  # auth from env / ~/.databrickscfg

    for label, sql in statements:
        if label and label != "check query":
            print(f"Creating {label}...")
        result = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=warehouse_id, wait_timeout="30s"
        )
        if result.status and result.status.error:
            error = result.status.error
            raise SystemExit(f"error ({error.error_code}): {error.message}\n\nStatement was:\n{sql}")
        if label == "check query":
            columns = [c.name for c in result.manifest.schema.columns]
            print("\n  " + "  ".join(f"{c:>21}" for c in columns))
            for row in result.result.data_array or []:
                print("  " + "  ".join(f"{str(v):>21}" for v in row))
    print(f"\nDone. Open {q}.{view} in Catalog Explorer for the demo.")


if __name__ == "__main__":
    main()
