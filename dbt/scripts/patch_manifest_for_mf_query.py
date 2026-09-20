"""Patch target/semantic_manifest.json so `mf query` can actually run.

Works around 4 apache-ossie-dbt converter bugs: missing agg_time_dimension,
order_count misattributed to the wrong semantic model, an empty time spine,
and COUNT(*) emitted as `expr: '*'` - see NOTES.md for each.

Re-run after every export_metric_view.py or dbt run - both regenerate the
file this patches from scratch.
"""

import json
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent.parent / "target" / "semantic_manifest.json"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())

    # Fix 1: agg_time_dimension, picked from whichever dimension is time-typed.
    for semantic_model in manifest["semantic_models"]:
        if semantic_model.get("defaults"):
            continue
        time_dims = [d["name"] for d in semantic_model.get("dimensions", []) if d.get("type") == "time"]
        if time_dims:
            semantic_model["defaults"] = {"agg_time_dimension": time_dims[0]}

    # Fix 2: order_count belongs to orders, not customers.
    for metric in manifest["metrics"]:
        if metric["name"] == "order_count":
            metric["type_params"]["metric_aggregation_params"]["semantic_model"] = "orders"

    # Fix 3: this converter never fills in a time spine.
    if not manifest["project_configuration"]["time_spine_table_configurations"]:
        manifest["project_configuration"]["time_spine_table_configurations"] = [
            {
                "location": '"ossie_demo"."main"."metricflow_time_spine"',
                "column_name": "date_day",
                "grain": "day",
            }
        ]

    # Fix 4: COUNT(*) comes out as expr '*', which MetricFlow wraps as
    # SUM(CASE WHEN * IS NOT NULL ...) - invalid SQL. '1' is never null, so it
    # counts every row.
    for metric in manifest["metrics"]:
        params = metric["type_params"]
        if params.get("expr") == "*" and params["metric_aggregation_params"]["agg"] == "count":
            params["expr"] = "1"

    MANIFEST_PATH.write_text(json.dumps(manifest))
    print(f"patched {MANIFEST_PATH.relative_to(MANIFEST_PATH.parent.parent)}")


if __name__ == "__main__":
    main()
