"""Patch target/semantic_manifest.json so `mf query` can actually run.

dbt-core 1.12's native OSI -> dbt conversion (metricflow.converters.osi_to_msi,
vendored inside dbt-core, not the apache-ossie package) never sets
`agg_time_dimension` anywhere - not on a semantic model's `defaults`, not on
any measure. MetricFlow requires this for every query, even an ungrouped
one, so as-compiled the manifest is NOT actually queryable despite `dbt
parse` succeeding cleanly. See NOTES.md for how this was found.

This script works around just enough of that gap to demo a real, working
`mf query` locally: it sets `orders.defaults.agg_time_dimension` to
`order_date` (the model's only time dimension) and fixes `order_count`
being misattributed to the `customers` semantic model instead of `orders`
(a second, independent bug in the same converter - it can't find a real
column name in a bare `COUNT(*)` expression and falls back to the wrong
dataset).

It does NOT fix `order_count` itself: `COUNT(*)`-shaped OSI metrics
generate invalid SQL (`SUM(CASE WHEN * IS NOT NULL THEN 1 ELSE 0 END)`,
which DuckDB rejects) regardless of this patch - that's a deeper
code-generation bug, not a missing field. Stick to `total_revenue` and
`avg_order_value` for the "look, it really works" part of the demo;
`order_count --explain` is its own "and here's a bug" moment.

Run after `dbt run` (needs real tables, not just `dbt parse`), before
`mf query`. Re-run after every `dbt run`/`dbt parse`, since either
regenerates target/semantic_manifest.json from scratch.
"""

import json
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent.parent / "target" / "semantic_manifest.json"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())

    for semantic_model in manifest["semantic_models"]:
        if semantic_model["name"] == "orders":
            semantic_model["defaults"] = {"agg_time_dimension": "order_date"}

    for metric in manifest["metrics"]:
        if metric["name"] == "order_count":
            metric["type_params"]["metric_aggregation_params"]["semantic_model"] = "orders"

    MANIFEST_PATH.write_text(json.dumps(manifest))
    print(f"patched {MANIFEST_PATH.relative_to(MANIFEST_PATH.parent.parent)}")


if __name__ == "__main__":
    main()
