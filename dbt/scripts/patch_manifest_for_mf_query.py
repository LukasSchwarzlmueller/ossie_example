"""Patch target/semantic_manifest.json so `mf query` can actually run.

dbt-core 1.12's native OSI -> dbt conversion (metricflow.converters.osi_to_msi,
part of the separate `metricflow` package dbt-core depends on, not the
apache-ossie package) never sets `agg_time_dimension` anywhere - not in a
semantic model's `defaults`, not per-measure. MetricFlow requires this for
every query, even an ungrouped one, so as-compiled the manifest is NOT
actually queryable despite `dbt parse` succeeding cleanly. See NOTES.md
for how this was found.

Two independent fixes:

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

Does NOT fix `order_count` itself even once correctly attributed:
`COUNT(*)`-shaped OSI metrics generate invalid SQL (`SUM(CASE WHEN * IS
NOT NULL THEN 1 ELSE 0 END)`, which DuckDB rejects) regardless of this
patch - a deeper code-generation bug, not a missing/misplaced field.
Stick to `total_revenue`/`avg_order_value` for a working demo;
`order_count --explain` is its own "and here's a bug" moment.

Run after `dbt run` (needs real tables, not just `dbt parse`), before
`mf query`. Only needs re-running after a dbt command that recompiles
(`dbt run`/`parse`/`show`/`docs generate`) - those regenerate
target/semantic_manifest.json from scratch and silently wipe the patch;
`mf` commands themselves only read the file, so any number of `mf query`/
`mf list` calls in a row is fine without re-patching.
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

    MANIFEST_PATH.write_text(json.dumps(manifest))
    print(f"patched {MANIFEST_PATH.relative_to(MANIFEST_PATH.parent.parent)}")


if __name__ == "__main__":
    main()
