"""Deploy the Power BI -> Metric View results to Databricks, one set per input format.

For each of tmsl/tmdl: tables <way>_customers / <way>_orders (same demo rows as
databricks/deploy_to_databricks.py) and Metric View <way>_<view name>, created from
powerbi_databricks/metric_view_from_<way>.yaml. Run export_metric_view.py first.

    uv run powerbi_databricks/deploy_to_databricks.py [--dry-run]    # --dry-run prints the SQL

Needs the same .env as databricks/deploy_to_databricks.py. The Metric Views have no measures
(DAX-only metrics are dropped), which Databricks may reject - not tested.
"""

import argparse
import os

from databricks.sdk import WorkspaceClient

from common.env import REPO_ROOT, load_env_file

HERE = REPO_ROOT / "powerbi_databricks"
CUSTOMERS = """CREATE OR REPLACE TABLE {q}.{way}_customers AS
SELECT * FROM (VALUES
    (1, 'Alice Anders', 'enterprise'),
    (2, 'Bob Baker', 'smb'),
    (3, 'Carol Chen', 'enterprise')
) AS t(customer_id, customer_name, customer_segment)"""
ORDERS = """CREATE OR REPLACE TABLE {q}.{way}_orders AS
SELECT * FROM (VALUES
    (101, 1, DATE'2026-01-05', 250.00),
    (102, 1, DATE'2026-02-10', 90.50),
    (103, 2, DATE'2026-02-11', 40.00),
    (104, 3, DATE'2026-03-01', 610.25)
) AS t(order_id, customer_id, order_date, order_amount)"""
VIEW = "CREATE OR REPLACE VIEW {q}.{way}_{view} WITH METRICS LANGUAGE YAML AS $$\n{yaml}\n$$"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print the SQL, don't connect")
    args = parser.parse_args()

    load_env_file()
    catalog = os.environ.get("DATABRICKS_CATALOG", "ossi")
    schema = os.environ.get("DATABRICKS_SCHEMA", "test")
    view = os.environ.get("DATABRICKS_METRIC_VIEW_NAME") or "sales_demo_metrics"
    q = f"{catalog}.{schema}"

    if not args.dry_run:
        warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
        if not warehouse_id:
            raise SystemExit("DATABRICKS_WAREHOUSE_ID not set - is it in .env?")
        w = WorkspaceClient()  # picks up auth from env / ~/.databrickscfg

    def run(statement: str) -> None:
        if args.dry_run:
            print(statement + ";\n")
            return
        result = w.statement_execution.execute_statement(
            statement=statement, warehouse_id=warehouse_id, wait_timeout="30s"
        )
        if result.status and result.status.error:
            error = result.status.error
            raise SystemExit(f"error ({error.error_code}): {error.message}\n\nStatement was:\n{statement}")

    for way in ("tmsl", "tmdl"):
        yaml_text = (HERE / f"metric_view_from_{way}.yaml").read_text()
        if f"source: {q}.{way}_" not in yaml_text:
            raise SystemExit(f"metric_view_from_{way}.yaml isn't qualified for {q} - run export_metric_view.py first")
        print(f"-- [{way}] tables {q}.{way}_customers / {way}_orders, Metric View {q}.{way}_{view}")
        run(CUSTOMERS.format(q=q, way=way))
        run(ORDERS.format(q=q, way=way))
        run(VIEW.format(q=q, way=way, view=view, yaml=yaml_text))


if __name__ == "__main__":
    main()
