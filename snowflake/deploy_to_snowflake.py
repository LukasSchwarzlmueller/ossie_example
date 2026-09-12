"""Deploy the demo tables + a real, SQL-queryable Semantic View to Snowflake.


Creates its own warehouse/database/schema (SNOWFLAKE_DATABASE/SCHEMA from
.env - run export_semantic_model.py first, which qualifies
semantic_model.yaml for the same place). Needs `uv add
snowflake-connector-python` first - not a project dependency by default.
"""

import os

import snowflake.connector
import yaml

from common.env import REPO_ROOT, load_env_file

WAREHOUSE = "OSSIE_COMPUTE_WH"
SEMANTIC_MODEL_FILE = "semantic_model.yaml"
METRICS_TABLE = "orders"  # ossie-snowflake doesn't attribute metrics to a table; all 3 are order-level


def _nest_metrics_per_table(semantic_model_yaml: str) -> str:
    """Nest ossie-snowflake's top-level metrics under their owning table - see NOTES.md."""
    doc = yaml.safe_load(semantic_model_yaml)

    metrics = doc.pop("metrics", None)
    if metrics:
        for table in doc["tables"]:
            if table["name"] == METRICS_TABLE:
                table["metrics"] = metrics
                break
        else:
            raise ValueError(f"METRICS_TABLE {METRICS_TABLE!r} not found among tables")

    return yaml.dump(doc, sort_keys=False)


def main() -> None:
    load_env_file()
    account = os.environ.get("SNOWFLAKE_ACCOUNT")
    user = os.environ.get("SNOWFLAKE_USER")
    password = os.environ.get("SNOWFLAKE_PASSWORD")
    if not all([account, user, password]):
        raise SystemExit(
            "SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / SNOWFLAKE_PASSWORD not fully set - check .env"
        )
    database = os.environ.get("SNOWFLAKE_DATABASE", "OSSIE_DEMO")
    schema = os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC")

    semantic_model_path = REPO_ROOT / "snowflake" / SEMANTIC_MODEL_FILE
    if not semantic_model_path.exists():
        raise SystemExit(
            f"snowflake/{SEMANTIC_MODEL_FILE} not found - run "
            "'uv run python3 snowflake/export_semantic_model.py' first."
        )
    semantic_model_yaml = semantic_model_path.read_text()
    if f"database: {database}" not in semantic_model_yaml:
        raise SystemExit(
            f"snowflake/{SEMANTIC_MODEL_FILE} isn't qualified for {database}.{schema} - "
            "run 'uv run python3 snowflake/export_semantic_model.py' first "
            "(it reads the same SNOWFLAKE_DATABASE/SNOWFLAKE_SCHEMA from .env)."
        )

    role = os.environ.get("SNOWFLAKE_ROLE")  # optional; falls back to your default role

    conn = snowflake.connector.connect(account=account, user=user, password=password, role=role)
    cur = conn.cursor()

    print(f"Creating warehouse {WAREHOUSE} if missing...")
    cur.execute(
        f"CREATE WAREHOUSE IF NOT EXISTS {WAREHOUSE} "
        "WAREHOUSE_SIZE=XSMALL AUTO_SUSPEND=60 AUTO_RESUME=TRUE INITIALLY_SUSPENDED=TRUE"
    )
    cur.execute(f"USE WAREHOUSE {WAREHOUSE}")

    print(f"Creating database/schema {database}.{schema} if missing...")
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {database}.{schema}")

    print("Creating + populating tables (same rows as models/*.sql locally)...")
    cur.execute(f"""
        CREATE OR REPLACE TABLE {database}.{schema}.customers AS
        SELECT * FROM (VALUES
            (1, 'Alice Anders', 'enterprise'),
            (2, 'Bob Baker', 'smb'),
            (3, 'Carol Chen', 'enterprise')
        ) AS t(customer_id, customer_name, customer_segment)
    """)
    cur.execute(f"""
        CREATE OR REPLACE TABLE {database}.{schema}.orders AS
        SELECT * FROM (VALUES
            (101, 1, DATE'2026-01-05', 250.00),
            (102, 1, DATE'2026-02-10', 90.50),
            (103, 2, DATE'2026-02-11', 40.00),
            (104, 3, DATE'2026-03-01', 610.25)
        ) AS t(order_id, customer_id, order_date, order_amount)
    """)

    prepared_yaml = _nest_metrics_per_table(semantic_model_yaml)
    print(f"Creating native Semantic View in {database}.{schema} "
          f"(metrics nested under '{METRICS_TABLE}')...")
    cur.execute(f"""
        CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(
          '{database}.{schema}',
          $$
{prepared_yaml}
          $$
        )
    """)
    print(f"  {cur.fetchone()[0]}")

    print("Done. Query it with:")
    print("  SELECT * FROM SEMANTIC_VIEW(")
    print(f"    {database}.{schema}.sales_demo")
    print("    METRICS total_revenue, order_count, avg_order_value")
    print("    DIMENSIONS customer_segment")
    print("  )")


if __name__ == "__main__":
    main()
