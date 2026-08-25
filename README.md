# Apache Ossie -> dbt & Databricks

Converts one [Apache Ossie](https://ossie.apache.org/) semantic model into
two targets: a native dbt Core 1.12 project, and a Databricks Unity Catalog
Metric View. Both targets are driven by the same source model
(`customers` + `orders`, 1:n on `customer_id`; metrics `total_revenue`,
`order_count`, `avg_order_value`) — see `NOTES.md` for the two structural
differences between the dbt and Databricks copies of that model, and why
they're unavoidable.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — manages the Python version (3.14,
  pinned in `.python-version`) and all dependencies, nothing to install
  manually.
- For the Databricks section: access to a real Databricks workspace with
  an existing catalog/schema and a running SQL warehouse. Not needed for
  the dbt section, which runs entirely locally against DuckDB.

```bash
uv sync
```

## dbt

The model: `dbt/ossie/orders_customers.json`.

Load it and confirm dbt recognizes the metrics:

```bash
cd dbt
DBT_PROFILES_DIR=. uv run dbt parse
DBT_PROFILES_DIR=. uv run dbt --quiet list --resource-type metric
cd ..
```

Query real metric values with one command (builds the tables, works
around the known bugs below, then runs a real `mf query`):

```bash
uv run python3 dbt/run_demo_query.py
```

```
customer_id__customer_segment      total_revenue    avg_order_value
-------------------------------  ---------------  -----------------
enterprise                                950.75            316.917
smb                                        40                40
```

To query other metrics or dimensions yourself, run the same steps by hand:

```bash
cd dbt
DBT_PROFILES_DIR=. uv run dbt run
uv run python3 scripts/patch_manifest_for_mf_query.py   # re-run before EVERY query, see below
DBT_PROFILES_DIR=. uv run mf list metrics                # shows each metric's valid group-bys
DBT_PROFILES_DIR=. uv run mf query --metrics total_revenue --group-by customer_id__customer_segment
```

### Known issues (dbt)

dbt-core 1.12's native OSI -> MetricFlow conversion
(`metricflow/converters/osi_to_msi.py`, vendored inside dbt-core, not part
of Ossie itself) has two bugs. Both are invisible at `dbt parse`/`dbt run`
time — the compiled manifest just isn't queryable as produced:

1. **No `agg_time_dimension` is ever set**, which MetricFlow requires for
   every query, even ungrouped ones.
2. **`order_count` is attached to the wrong semantic model**
   (`customers` instead of `orders`) — the converter picks a metric's
   owning dataset by finding a real column name in its SQL, and bare
   `COUNT(*)` has none.

`dbt/scripts/patch_manifest_for_mf_query.py` works around both by editing
the compiled `dbt/target/semantic_manifest.json` directly after it's
generated. It does **not** fix `order_count` fully: even patched,
`COUNT(*)`-shaped metrics compile to SQL DuckDB rejects (`STAR expression
is only allowed as the root element`) — a separate code-generation bug.
Query `total_revenue`/`avg_order_value` instead.

**The patch doesn't stick.** It edits a generated file, and *any* dbt
command that recompiles — `dbt run`, `dbt parse`, `dbt show`, `dbt docs
generate` — regenerates that file from scratch and silently reverts it.
Re-run `patch_manifest_for_mf_query.py` immediately before every
`mf query`/`mf list` call, not just once after `dbt run`.

## Databricks

The model: `databricks/ossie/orders_customers.yaml` (same shape as the dbt
one, minus two required adjustments — see NOTES.md).

### 1. Convert to a Metric View

Pure offline conversion, no workspace needed:

```bash
uv run python3 databricks/export_metric_view.py
cat databricks/metric_view.yaml
```

Add `--warnings` to see what didn't survive the conversion (some fields
are dropped, others repurposed — see NOTES.md for details).

### 2. Deploy to a real workspace (optional)

```bash
cp .env.example .env   # fill in DATABRICKS_HOST / DATABRICKS_TOKEN / DATABRICKS_WAREHOUSE_ID
uv run python3 databricks/deploy_to_databricks.py
```

| `.env` variable | Required | Notes |
|---|---|---|
| `DATABRICKS_HOST` | yes | your workspace URL |
| `DATABRICKS_TOKEN` | yes | personal access token |
| `DATABRICKS_WAREHOUSE_ID` | yes | SQL warehouse to run against |
| `DATABRICKS_METRIC_VIEW_NAME` | no | defaults to `sales_demo_metrics`; set this if you're sharing a catalog/schema with other people so your deploy doesn't overwrite theirs |

`.env` is gitignored and loaded by the script itself — no `--env-file`
flag needed, and never commit it.

`CATALOG`/`SCHEMA` (default `ossi`/`test`) are constants at the top of
`databricks/deploy_to_databricks.py` — edit them to match your workspace;
they must already exist, the script doesn't create them. The
`customers`/`orders` tables are shared and safe to re-run (same synthetic
data for everyone); only the Metric View name needs to be unique per
person.

Query the result with `MEASURE(name)` in the `SELECT` list — Metric Views
have no `MEASURES` clause:

```sql
SELECT customer_segment, MEASURE(total_revenue), MEASURE(avg_order_value)
FROM <catalog>.<schema>.<view_name>
GROUP BY customer_segment
```

## dbt vs Databricks: what had to differ

Same underlying model, two loaders with genuinely incompatible
requirements — not stylistic differences, each one breaks the other
target if applied:

| | dbt | Databricks |
|---|---|---|
| Source file format | `.json` only — the native loader globs `osi-paths/**/*.json`, a `.yaml` file is silently invisible to it | Either — parsed as plain YAML (JSON is valid YAML), `.yaml` used here to match Ossie's own docs |
| `version` field | `"0.1.0"` or `"0.1.1"` only | `"0.2.0.dev0"` only — no single value satisfies both |
| `customers.customer_id` field | Must be present — dbt's join inference needs matching entity names on both sides of the relationship | Must be dropped from `fields` (kept only in `primary_key`) — Metric Views need globally unique dimension names across the flattened namespace, and `orders.customer_id`/`customers.customer_id` would collide |
| `dimension.is_time` | Required (dbt's vendored schema, stricter than Ossie's own, which makes it optional) | No equivalent field — silently dropped, cosmetic only |
| Dataset-level `description` | Dropped (no per-source comment field) | Same — dropped for the same reason |
| Conversion bugs | 2 real upstream bugs in dbt-core's native OSI->MetricFlow converter (missing `agg_time_dimension`, `order_count` misattributed) — needs `patch_manifest_for_mf_query.py` before every query | None found — conversion is clean, verified against a real workspace end to end |
| Query syntax | `mf query --metrics x --group-by entity__dim` | `SELECT dim, MEASURE(x) FROM view GROUP BY dim` |
| Verified queryable | `total_revenue`/`avg_order_value` only (`order_count` fails on invalid generated SQL, patch or not) | All 3 metrics, deployed and queried against a real workspace |

The two source files differ in exactly two places as a result (see
`scripts/diff_summary.py`): the `version` tag, and `customer_id` present
vs. dropped. Everything else about the model — descriptions, labels,
relationships, all 3 metrics — is identical between them.

## Layout

- `dbt/ossie/orders_customers.json` — the Ossie model, dbt-native shape.
- `dbt/run_demo_query.py` — one-command dbt run + patch + `mf query`.
- `dbt/scripts/patch_manifest_for_mf_query.py` — the bug workaround, see
  "Known issues (dbt)" above.
- `databricks/ossie/orders_customers.yaml` — the same model, adapted for
  Databricks.
- `databricks/export_metric_view.py` — runs the conversion, writes
  `databricks/metric_view.yaml`.
- `databricks/deploy_to_databricks.py` — deploys tables + Metric View to a
  real workspace.

## Further reading

`NOTES.md` has the full background: why the dbt and Databricks model
copies differ, how each bug above was found, and other gotchas hit along
the way (dbt's local docs UI limitations, DAG lineage quirks, etc).
