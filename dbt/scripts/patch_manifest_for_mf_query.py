"""Patch target/semantic_manifest.json so `mf query` can actually run.

This patches the output of `apache-ossie-dbt`'s own standalone converter
(`ossie_dbt.ossie_to_msi.OssieToMSIConverter`, written by `export_metric_view.py`
in this folder) - not dbt-core's own vendored native OSI loader
(`metricflow.converters.osi_to_msi`, a completely separate codebase dbt-core
runs on `dbt parse`/`dbt run` directly, and rejects this file's version
`0.2.0.dev0` outright, silently finding zero metrics rather than erroring).
Independently, this converter has the same two bugs NOTES.md documents for
that other one, plus a third of its own:

1. Missing `agg_time_dimension` - general, not tied to this demo's model.
   For any semantic model missing `defaults`, find a dimension the
   compiled manifest itself marks `type: "time"` and use that. Works for
   whatever semantic models/dimensions happen to be in the project.
2. `order_count` misattributed to the `customers` semantic model instead
   of `orders` - the converter resolves a metric's owning dataset by
   finding a real column name in its SQL, and a bare `COUNT(*)` has none.
   This one CANNOT be honestly generalized: there's no way to derive
   "which table this metric belongs to" from an expression that gives no
   clues. Stays a named, model-specific correction - rewrite this part by
   hand for a different model's version of the same bug.
3. Missing `time_spine_table_configurations` - empty in this converter's
   output no matter what, because it converts an Ossie YAML in isolation
   and has no access to the dbt project's actual `metricflow_time_spine`
   model, unlike dbt-core's native loader, which runs inside the project
   and can look that model up itself. Filled in here by hand, pointing at
   this project's real `metricflow_time_spine` table.

A fourth bug was here too: `customers` came out with zero `entities`,
even though `primary_key: [customer_id]` is declared on it. Turned out to
be narrower than "the converter ignores primary_key" - it only turns a
primary_key column into an entity if that column is *also* declared as a
field on the same dataset, and `customer_id` had been deliberately dropped
from `customers.fields` for Databricks' sake (see NOTES.md - Metric Views
need globally unique dimension names, and `orders.customer_id`/
`customers.customer_id` would otherwise collide). Fixed by adding
`customer_id` back as a field on `customers` in `../ossie/orders_customers.yaml`
- this file is no longer byte-identical to `databricks/ossie/orders_customers.yaml`
as a result, one real, structural conflict between what Databricks needs
absent and what this converter needs present, not a bug in either.

Does NOT fix `order_count` itself even once correctly attributed:
`COUNT(*)`-shaped OSI metrics generate invalid SQL (`SUM(CASE WHEN * IS
NOT NULL THEN 1 ELSE 0 END)`, which DuckDB rejects) regardless of this
patch - a deeper code-generation bug, not a missing/misplaced field.
Stick to `total_revenue`/`avg_order_value` for a working demo;
`order_count --explain` is its own "and here's a bug" moment.

Run after `export_metric_view.py` (needs real tables from `dbt run` too),
before `mf query`. Re-run after re-running `export_metric_view.py`, which
overwrites target/semantic_manifest.json from scratch each time.
"""

import json
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent.parent / "target" / "semantic_manifest.json"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())

    # Fix 1: general - any semantic model missing a time default gets one,
    # picked from whichever of its dimensions the manifest marks as time-typed.
    for semantic_model in manifest["semantic_models"]:
        if semantic_model.get("defaults"):
            continue
        time_dims = [d["name"] for d in semantic_model.get("dimensions", []) if d.get("type") == "time"]
        if time_dims:
            semantic_model["defaults"] = {"agg_time_dimension": time_dims[0]}

    # Fix 2: specific to this demo's order_count bug - see module docstring.
    for metric in manifest["metrics"]:
        if metric["name"] == "order_count":
            metric["type_params"]["metric_aggregation_params"]["semantic_model"] = "orders"

    # Fix 3: this converter never fills in a time spine at all - see module docstring.
    if not manifest["project_configuration"]["time_spine_table_configurations"]:
        manifest["project_configuration"]["time_spine_table_configurations"] = [
            {
                "location": '"ossie_demo"."main"."metricflow_time_spine"',
                "column_name": "date_day",
                "grain": "day",
            }
        ]

    MANIFEST_PATH.write_text(json.dumps(manifest))
    print(f"patched {MANIFEST_PATH.relative_to(MANIFEST_PATH.parent.parent)}")


if __name__ == "__main__":
    main()
