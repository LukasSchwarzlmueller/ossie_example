"""Deploy the demo tables + Metric View to a real Databricks workspace.

NOT part of the live demo (conversion-only, by design) - this is for
trying the deploy step separately, once you have workspace access set up.

Verified against a real workspace (2026-08-25): the `CREATE ... WITH METRICS
LANGUAGE YAML` DDL and the `SELECT dim, MEASURE(metric) FROM view GROUP BY
dim` query form both work as written below. Docs:
  https://docs.databricks.com/aws/en/metric-views/

Needs CATALOG/SCHEMA below to already exist (edit them to match your
workspace) and a running SQL warehouse. Auth + warehouse ID come from the
environment - copy .env.example to .env and fill in real values (.env is
gitignored, never commit it). This script loads .env itself, so just:
    uv run python3 databricks/deploy_to_databricks.py

If several people share the same CATALOG/SCHEMA (e.g. a workshop), set
DATABRICKS_METRIC_VIEW_NAME in .env to something unique per person so your
`CREATE OR REPLACE VIEW` doesn't clobber someone else's - the underlying
customers/orders tables stay shared (same synthetic data for everyone, so
collisions there are harmless).
"""

import os
from pathlib import Path

from databricks.sdk import WorkspaceClient

REPO_ROOT = Path(__file__).parent.parent
LOCAL_QUALIFIER = "ossie_demo.main."  # matches orders_customers.yaml's dataset `source` values
CATALOG = "ossi"
SCHEMA = "test"


def _load_env_file(path: Path) -> None:
    """Set env vars from a `KEY=value` file, without overriding ones already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def run(w: WorkspaceClient, warehouse_id: str, statement: str) -> None:
    result = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="30s",
    )
    state = result.status.state if result.status else None
    print(f"  status: {state}")
    error = result.status.error if result.status else None
    if error is not None:
        raise SystemExit(f"  error ({error.error_code}): {error.message}\n\nStatement was:\n{statement}")


def main() -> None:
    _load_env_file(REPO_ROOT / ".env")

    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not warehouse_id:
        raise SystemExit("DATABRICKS_WAREHOUSE_ID not set - is it in .env?")
    view_name = os.environ.get("DATABRICKS_METRIC_VIEW_NAME") or "sales_demo_metrics"

    w = WorkspaceClient()  # picks up auth from env / ~/.databrickscfg
    qualified = f"{CATALOG}.{SCHEMA}"

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

    metric_view_yaml = (REPO_ROOT / "databricks" / "metric_view.yaml").read_text()
    if LOCAL_QUALIFIER not in metric_view_yaml:
        raise SystemExit(
            f"databricks/metric_view.yaml doesn't contain '{LOCAL_QUALIFIER}' - "
            "run 'uv run python3 databricks/export_metric_view.py' first."
        )
    metric_view_yaml = metric_view_yaml.replace(LOCAL_QUALIFIER, f"{qualified}.")

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

    print("Done. Query it with:")
    print("  SELECT customer_segment, MEASURE(total_revenue), MEASURE(avg_order_value)")
    print(f"  FROM {qualified}.{view_name}")
    print("  GROUP BY customer_segment")


if __name__ == "__main__":
    main()
