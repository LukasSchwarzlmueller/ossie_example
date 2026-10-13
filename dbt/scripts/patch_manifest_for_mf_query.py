"""Patch target/semantic_manifest.json so `mf query` can actually run.

Adds the two things the converter's output lacks: agg_time_dimension, which
apache-ossie-dbt never sets (a converter bug), and the time spine, which
Ossie has no notion of and dbt declares in models/metricflow_time_spine.yml -
see NOTES.md for each.

Re-run after every export_metric_view.py or dbt run - both regenerate the
file this patches from scratch.
"""

import json
from pathlib import Path

TARGET = Path(__file__).parent.parent / "target"
MANIFEST_PATH = TARGET / "semantic_manifest.json"
DBT_MANIFEST_PATH = TARGET / "manifest.json"  # dbt's own manifest, untouched by export_metric_view.py


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())

    # Fix 1: agg_time_dimension, picked from whichever dimension is time-typed.
    for semantic_model in manifest["semantic_models"]:
        if semantic_model.get("defaults"):
            continue
        time_dims = [d["name"] for d in semantic_model.get("dimensions", []) if d.get("type") == "time"]
        if time_dims:
            semantic_model["defaults"] = {"agg_time_dimension": time_dims[0]}

    # Fix 2: the time spine, copied from every dbt model that declares one.
    if not manifest["project_configuration"].get("time_spines"):
        time_spines = []
        for node in json.loads(DBT_MANIFEST_PATH.read_text())["nodes"].values():
            spine = node.get("time_spine")
            if not spine:
                continue
            column = spine["standard_granularity_column"]
            time_spines.append(
                {
                    "node_relation": {
                        "alias": node["alias"],
                        "schema_name": node["schema"],
                        "database": node["database"],
                        "relation_name": node["relation_name"],
                    },
                    "primary_column": {
                        "name": column,
                        "time_granularity": node["columns"][column]["granularity"],
                    },
                    "custom_granularities": spine.get("custom_granularities", []),
                }
            )
        if not time_spines:
            raise SystemExit("no dbt model declares a time_spine - see models/metricflow_time_spine.yml")
        manifest["project_configuration"]["time_spines"] = time_spines

    MANIFEST_PATH.write_text(json.dumps(manifest))
    print(f"patched {MANIFEST_PATH.relative_to(MANIFEST_PATH.parent.parent)}")


if __name__ == "__main__":
    main()
