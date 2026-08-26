"""Deploy the demo tables + a real, SQL-queryable Semantic View to Snowflake.

NOT part of the live demo (conversion-only, by design) - this is for
trying the deploy step separately, once you have Snowflake access set up.

Verified against a real account: creates its own warehouse, database, and
schema; creates + populates the tables; and creates a native Semantic View
(`CREATE SEMANTIC VIEW`, via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`) with
all 3 metrics working, queryable with plain SQL:
    SELECT * FROM SEMANTIC_VIEW(
      <db>.<schema>.sales_demo
      METRICS total_revenue, order_count, avg_order_value
      DIMENSIONS customer_segment
    )

`_prepare_semantic_model` below fixes two real gaps in `ossie-snowflake`'s
raw output that this procedure needs - see NOTES.md for how each was
found, and for a separate deploy path (Snowflake's native Ossie-file
upload) that doesn't work yet.

Needs `pip install snowflake-connector-python` / `uv add
snowflake-connector-python` first - not added to this project's
dependencies since it's outside the demo's scope.

Creates its own warehouse/database/schema (DATABASE/SCHEMA/WAREHOUSE
constants below - edit if you'd rather point at existing ones). Auth
comes from the environment - copy .env.example to .env and fill in real
values (.env is gitignored, never commit it). This script loads .env
itself, so just:
    uv run python3 snowflake/deploy_to_snowflake.py
"""

import os
from pathlib import Path

import snowflake.connector
import yaml

REPO_ROOT = Path(__file__).parent.parent
DATABASE = "OSSIE_DEMO"
SCHEMA = "PUBLIC"
WAREHOUSE = "OSSIE_COMPUTE_WH"  # deliberately not "<DATABASE>_WH" - too easy to misread as the database
SEMANTIC_MODEL_FILE = "semantic_model.yaml"
# `ossie-snowflake` doesn't attribute metrics to a table; this demo's metrics
# all aggregate order-level facts, so they all belong under this one.
METRICS_TABLE = "orders"


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


def _prepare_semantic_model(semantic_model_yaml: str, database: str, schema: str) -> str:
    """Fix up ossie-snowflake's raw output for SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML.

    Two real gaps: base_table still points at the placeholder source path,
    and metrics need nesting inside their owning table - see NOTES.md.
    """
    doc = yaml.safe_load(semantic_model_yaml)
    for table in doc.get("tables", []):
        table["base_table"]["database"] = database
        table["base_table"]["schema"] = schema

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
    _load_env_file(REPO_ROOT / ".env")

    account = os.environ.get("SNOWFLAKE_ACCOUNT")
    user = os.environ.get("SNOWFLAKE_USER")
    password = os.environ.get("SNOWFLAKE_PASSWORD")
    if not all([account, user, password]):
        raise SystemExit(
            "SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / SNOWFLAKE_PASSWORD not fully set - check .env"
        )

    semantic_model_path = REPO_ROOT / "snowflake" / SEMANTIC_MODEL_FILE
    if not semantic_model_path.exists():
        raise SystemExit(
            f"snowflake/{SEMANTIC_MODEL_FILE} not found - run "
            "'uv run python3 snowflake/export_semantic_model.py' first."
        )

    role = os.environ.get("SNOWFLAKE_ROLE")  # optional; falls back to your default role

    # No warehouse yet - CREATE WAREHOUSE is a metadata operation and doesn't need
    # an active one. Connect bare, create/activate WAREHOUSE, then proceed.
    conn = snowflake.connector.connect(account=account, user=user, password=password, role=role)
    cur = conn.cursor()

    print(f"Creating warehouse {WAREHOUSE} if missing...")
    cur.execute(
        f"CREATE WAREHOUSE IF NOT EXISTS {WAREHOUSE} "
        "WAREHOUSE_SIZE=XSMALL AUTO_SUSPEND=60 AUTO_RESUME=TRUE INITIALLY_SUSPENDED=TRUE"
    )
    cur.execute(f"USE WAREHOUSE {WAREHOUSE}")

    print(f"Creating database/schema {DATABASE}.{SCHEMA} if missing...")
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {DATABASE}.{SCHEMA}")

    print("Creating + populating tables (same rows as models/*.sql locally)...")
    cur.execute(f"""
        CREATE OR REPLACE TABLE {DATABASE}.{SCHEMA}.customers AS
        SELECT * FROM (VALUES
            (1, 'Alice Anders', 'enterprise'),
            (2, 'Bob Baker', 'smb'),
            (3, 'Carol Chen', 'enterprise')
        ) AS t(customer_id, customer_name, customer_segment)
    """)
    cur.execute(f"""
        CREATE OR REPLACE TABLE {DATABASE}.{SCHEMA}.orders AS
        SELECT * FROM (VALUES
            (101, 1, DATE'2026-01-05', 250.00),
            (102, 1, DATE'2026-02-10', 90.50),
            (103, 2, DATE'2026-02-11', 40.00),
            (104, 3, DATE'2026-03-01', 610.25)
        ) AS t(order_id, customer_id, order_date, order_amount)
    """)

    prepared_yaml = _prepare_semantic_model(semantic_model_path.read_text(), DATABASE, SCHEMA)
    print(f"Creating native Semantic View in {DATABASE}.{SCHEMA} "
          f"(base_table qualified, metrics nested under '{METRICS_TABLE}')...")
    cur.execute(f"""
        CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(
          '{DATABASE}.{SCHEMA}',
          $$
{prepared_yaml}
          $$
        )
    """)
    print(f"  {cur.fetchone()[0]}")

    print("Done. Query it with:")
    print(f"  SELECT * FROM SEMANTIC_VIEW(")
    print(f"    {DATABASE}.{SCHEMA}.sales_demo")
    print("    METRICS total_revenue, order_count, avg_order_value")
    print("    DIMENSIONS customer_segment")
    print("  )")


if __name__ == "__main__":
    main()
