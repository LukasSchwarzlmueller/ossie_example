"""Deploy the demo tables + Metric View to a real Databricks workspace.

Needs DATABRICKS_CATALOG/DATABRICKS_SCHEMA to already exist (run
export_metric_view.py first, which qualifies metric_view.yaml for the same
catalog/schema) and a running SQL warehouse. Auth + warehouse ID come from
.env - see .env.example.
"""

import os

from databricks.sdk import WorkspaceClient

from common.env import REPO_ROOT, load_env_file


def run(w: WorkspaceClient, warehouse_id: str, statement: str):
    result = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="30s",
    )
    error = result.status.error if result.status else None
    if error is not None:
        raise SystemExit(f"error ({error.error_code}): {error.message}\n\nStatement was:\n{statement}")
    return result


def main() -> None:
    load_env_file()
    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not warehouse_id:
        raise SystemExit("DATABRICKS_WAREHOUSE_ID not set - is it in .env?")
    view_name = os.environ.get("DATABRICKS_METRIC_VIEW_NAME") or "sales_demo_metrics"
    catalog = os.environ.get("DATABRICKS_CATALOG", "ossi")
    schema = os.environ.get("DATABRICKS_SCHEMA", "test")

    w = WorkspaceClient()  # picks up auth from env / ~/.databrickscfg
    qualified = f"{catalog}.{schema}"

    print("Creating + populating tables (same rows as models/*.sql locally)...")
    run(
        w,
        warehouse_id,
        f"""
        CREATE OR REPLACE TABLE {qualified}.customers AS
        SELECT * FROM (VALUES
            (1, 'Alice Anders', 'enterprise'),
            (2, 'Bob Baker', 'smb'),
            (3, 'Carol Chen', 'enterprise')
        ) AS t(customer_id, customer_name, customer_segment)
        """,
    )
    run(
        w,
        warehouse_id,
        f"""
        CREATE OR REPLACE TABLE {qualified}.orders AS
        SELECT * FROM (VALUES
            (101, 1, DATE'2026-01-05', 250.00),
            (102, 1, DATE'2026-02-10', 90.50),
            (103, 2, DATE'2026-02-11', 40.00),
            (104, 3, DATE'2026-03-01', 610.25)
        ) AS t(order_id, customer_id, order_date, order_amount)
        """,
    )

    metric_view_path = REPO_ROOT / "databricks" / "metric_view.yaml"
    metric_view_yaml = metric_view_path.read_text()
    if f"source: {qualified}." not in metric_view_yaml:
        raise SystemExit(
            f"databricks/metric_view.yaml isn't qualified for {qualified} - "
            "run 'uv run python3 databricks/export_metric_view.py' first "
            "(it reads the same DATABRICKS_CATALOG/DATABRICKS_SCHEMA from .env)."
        )

    print(f"Creating Metric View {qualified}.{view_name}...")
    run(
        w,
        warehouse_id,
        f"""
        CREATE OR REPLACE VIEW {qualified}.{view_name}
        WITH METRICS
        LANGUAGE YAML
        AS $$
{metric_view_yaml}
        $$
        """,
    )

    print("Verifying what actually persisted (SHOW CREATE TABLE)...")
    show_result = run(w, warehouse_id, f"SHOW CREATE TABLE {qualified}.{view_name}")
    created_view_sql = show_result.result.data_array[0][0]
    if "synonyms:" not in created_view_sql:
        print("  WARNING: 'synonyms:' not found anywhere in the persisted view - see NOTES.md")
        print(created_view_sql)
    else:
        print("  synonyms persisted correctly.")

    print("Done. Query it with:")
    print("  SELECT customer_segment, MEASURE(total_revenue), MEASURE(avg_order_value)")
    print(f"  FROM {qualified}.{view_name}")
    print("  GROUP BY customer_segment")


if __name__ == "__main__":
    main()
