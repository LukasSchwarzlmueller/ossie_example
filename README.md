# Apache Ossie -> dbt, Databricks & Snowflake

Converts one [Apache Ossie](https://ossie.apache.org/) semantic model into
three targets: a dbt Core project, a Databricks Unity Catalog Metric View,
and a Snowflake Cortex Analyst semantic model. Same source model
everywhere (`customers` + `orders`, 1:n on `customer_id`; metrics
`total_revenue`, `order_count`, `avg_order_value`) - see `NOTES.md` for how
and why the three copies of that model differ, and for the full story
behind every fix mentioned below.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) - manages the Python version and all
  dependencies.
- For Databricks/Snowflake: real workspace/account access. Not needed for
  dbt, which runs entirely locally against DuckDB.

```bash
uv sync
```

## dbt

```bash
cd dbt
uv run dbt run                                     # builds the tables
uv run scripts/export_metric_view.py               # Ossie -> semantic_manifest.json
uv run scripts/patch_manifest_for_mf_query.py       # works around 3 converter bugs, see NOTES.md
uv run mf query --metrics total_revenue,avg_order_value --group-by customer_id__customer_segment
cd ..
```

```
customer_id__customer_segment      total_revenue    avg_order_value
-------------------------------  ---------------  -----------------
smb                                        40                40
enterprise                                950.75            316.917
```

`apache-ossie-dbt`'s converter has 3 real bugs, patched by the script
above (see NOTES.md for how each was found):
- no `agg_time_dimension` is ever set
- `order_count` attaches to the wrong semantic model
- no time spine is ever configured

Re-run the patch step before any further `mf` call after re-running
`export_metric_view.py` or any `dbt` command - it edits a generated file
that gets silently overwritten. `order_count` is still not queryable even
patched (a separate DuckDB code-generation bug) - stick to
`total_revenue`/`avg_order_value`.

## Databricks

```bash
uv run databricks/export_metric_view.py
cat databricks/metric_view.yaml
```

Add `--warnings` to see what didn't survive the conversion. No conversion
bugs found here - the model just drops `customers.customer_id` as a field
(kept only in `primary_key`), since Metric Views need globally unique
dimension names across the flattened namespace; dbt's copy needs it
present instead (see NOTES.md).

To deploy to a real workspace:

```bash
cp .env.example .env   # fill in DATABRICKS_HOST / DATABRICKS_TOKEN / DATABRICKS_WAREHOUSE_ID
uv run databricks/export_metric_view.py    # re-run if DATABRICKS_CATALOG/SCHEMA change
uv run databricks/deploy_to_databricks.py
```

| `.env` variable | Required | Notes |
|---|---|---|
| `DATABRICKS_HOST` | yes | your workspace URL |
| `DATABRICKS_TOKEN` | yes | personal access token |
| `DATABRICKS_WAREHOUSE_ID` | yes | SQL warehouse to run against |
| `DATABRICKS_CATALOG` / `DATABRICKS_SCHEMA` | no | default `ossi`/`test`; must already exist |
| `DATABRICKS_METRIC_VIEW_NAME` | no | defaults to `sales_demo_metrics`; set if sharing a catalog/schema with others |

The Ossie model's `source:` fields hold a placeholder
(`__catalog__.__schema__`) - `export_metric_view.py` replaces it with
`DATABRICKS_CATALOG`/`DATABRICKS_SCHEMA` before conversion, so the exported
file is already qualified; `deploy_to_databricks.py` reads the same two
vars so export and deploy can't target different places.

```sql
SELECT customer_segment, MEASURE(total_revenue), MEASURE(avg_order_value), MEASURE(order_count)
FROM <catalog>.<schema>.<view_name>
GROUP BY ALL
```

## Snowflake

```bash
uv run snowflake/export_semantic_model.py
cat snowflake/semantic_model.yaml
```

To deploy to a real account (creates its own warehouse/database/schema):

```bash
uv add snowflake-connector-python   # not a project dependency yet
cp .env.example .env   # fill in SNOWFLAKE_ACCOUNT / USER / PASSWORD
uv run snowflake/export_semantic_model.py    # re-run if SNOWFLAKE_DATABASE/SCHEMA change
uv run snowflake/deploy_to_snowflake.py
```

Same placeholder-qualification pattern as Databricks, via
`SNOWFLAKE_DATABASE`/`SNOWFLAKE_SCHEMA`. One extra deploy-time fix:
`ossie-snowflake` emits all metrics as one top-level list, but Snowflake's
`CREATE SEMANTIC VIEW` requires them nested under their owning table -
`deploy_to_snowflake.py`'s `_nest_metrics_per_table` does that (see
NOTES.md). Tolerates `customers.customer_id` either way (unlike
Databricks), but needs `data_type`/`datatype` set on every field - silently
omitted otherwise, only surfacing as a live validation failure.

```sql
SELECT * FROM SEMANTIC_VIEW(
  OSSIE_DEMO.PUBLIC.sales_demo
  METRICS total_revenue, avg_order_value, order_count
  DIMENSIONS customer_segment
)
```

## Layout

- `dbt/ossie/`, `databricks/ossie/`, `snowflake/ossie/` - the Ossie model, one copy per target (near-identical - see NOTES.md for the handful of fields that differ and why).
- `<target>/export_*.py` - offline conversion, writes the target-native file.
- `<target>/deploy_to_*.py` / `dbt run` + `mf query` - deploys/queries against the real thing.
- `roundtrip_databricks/run_roundtrip.py` - not part of the talk; a side check that the Databricks export/import pair is lossless.
- `common/env.py` - shared `.env` loading, used by every export/deploy script.

## Further reading

`NOTES.md` has the full background: every bug found, how it was found, and
why the model copies differ.
