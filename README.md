# Apache Ossie -> dbt, Databricks & Snowflake

Converts one [Apache Ossie](https://ossie.apache.org/) semantic model into
three targets: a dbt Core 1.12 project (via the separate `apache-ossie-dbt`
converter package, not dbt-core's own native OSI loader - see below), a
Databricks Unity Catalog Metric View, and a Snowflake Cortex Analyst
semantic model. All three are driven by the same source model
(`customers` + `orders`, 1:n on `customer_id`; metrics `total_revenue`,
`order_count`, `avg_order_value`) — see `NOTES.md` for exactly how the
three copies of that model differ, and why.

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

The model: `dbt/ossie/orders_customers.yaml` (near-identical to the
Databricks copy, `version: 0.2.0.dev0`, one field differs - see below).
dbt-core's own native OSI loader rejects
this outright - it only accepts `version: "0.1.0"`/`"0.1.1"` - silently
finding zero semantic models/metrics rather than erroring, so this repo
uses the separate `apache-ossie-dbt` converter package instead (added to
the root `pyproject.toml`), which converts the Ossie YAML directly into
`semantic_manifest.json`. See `NOTES.md` for the full story.

```bash
cd dbt
uv run dbt run                                     # builds the tables
uv run scripts/export_metric_view.py               # converts orders_customers.yaml via apache-ossie-dbt, overwrites target/semantic_manifest.json
uv run scripts/patch_manifest_for_mf_query.py       # works around the known bugs below - only needs re-running after export_metric_view.py or dbt recompiles, see below
uv run mf query --metrics total_revenue,avg_order_value --group-by customer_id__customer_segment
cd ..
```

```
customer_id__customer_segment      total_revenue    avg_order_value
-------------------------------  ---------------  -----------------
smb                                        40                40
enterprise                                950.75            316.917
```

To query other metrics/dimensions, use `mf list metrics`/`mf query`
directly as above - just re-run the patch step first if you've re-run
`export_metric_view.py` or any dbt command since.

### Known issues (dbt)

`apache-ossie-dbt`'s own converter has three real bugs, invisible until
you actually try `mf query`. (Getting there needs a small detour first:
`ossie-dbt`'s own CLI currently crashes on every input - a Pydantic v1/v2
mismatch in the package's own code - so `export_metric_view.py` calls the
converter directly instead of going through it. Read that as "broken right
now," not a structural finding.)

1. **No `agg_time_dimension` is ever set**, which MetricFlow requires for
   every query, even ungrouped ones. Same bug as dbt-core's own native
   OSI loader - a completely separate codebase, independently confirmed.
2. **`order_count` is attached to the wrong semantic model**
   (`customers` instead of `orders`) - the converter picks a metric's
   owning dataset by finding a real column name in its SQL, and bare
   `COUNT(*)` has none. Same bug, same root cause, as dbt-core's native
   loader.
3. **No time spine is ever configured** - this converter has no access to
   the dbt project it'll run inside, so it can't look up the real
   `metricflow_time_spine` model the way dbt-core's native loader can.

A fourth issue looked like a bug and turned out to be a real conflict:
`customers` came out with zero entities despite declaring a `primary_key`
in the source, because this converter only turns a `primary_key` column
into an entity if it's *also* declared as a field on the same dataset -
and `customer_id` had been dropped from `customers.fields` for
Databricks' sake (see below). Fixed by adding it back as a field on
`dbt/ossie/orders_customers.yaml` specifically, which is why that file is
no longer identical to the Databricks copy - one field, opposite
requirements, not a bug in either converter.

`dbt/scripts/patch_manifest_for_mf_query.py` works around the three real
bugs by editing the compiled `dbt/target/semantic_manifest.json` directly
after `export_metric_view.py` generates it. It does **not** fix
`order_count` fully: even patched, `COUNT(*)`-shaped metrics compile to
SQL DuckDB rejects (`STAR expression is only allowed as the root
element`) - a separate code-generation bug, same as dbt-core's native
loader hits. Query `total_revenue`/`avg_order_value` instead.

**The patch doesn't stick across a recompile.** It edits a generated
file, and *any* dbt command that recompiles, or re-running
`export_metric_view.py`, regenerates that file from scratch and silently
reverts it. Re-run `patch_manifest_for_mf_query.py` right before your
next `mf` call.

## Databricks

The model: `databricks/ossie/orders_customers.yaml` (same shape as the dbt
one, minus two required adjustments — see NOTES.md).

### 1. Convert to a Metric View

Pure offline conversion, no workspace needed:

```bash
uv run databricks/export_metric_view.py
cat databricks/metric_view.yaml
```

Add `--warnings` to see what didn't survive the conversion (some fields
are dropped, others repurposed — see NOTES.md for details).

### 2. Deploy to a real workspace (optional)

```bash
cp .env.example .env   # fill in DATABRICKS_HOST / DATABRICKS_TOKEN / DATABRICKS_WAREHOUSE_ID
uv run databricks/deploy_to_databricks.py
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
SELECT customer_segment, MEASURE(total_revenue), MEASURE(avg_order_value), MEASURE(order_count)
FROM <catalog>.<schema>.<view_name>
GROUP BY ALL
```

## Snowflake

The model: `snowflake/ossie/orders_customers.yaml` — structurally
identical to the Databricks copy (same `version`, same fields; only the
explanatory comments differ). See NOTES.md for two real requirements that
only surfaced once actually deployed, not during local conversion
(`data_type` on every field, correct `base_table` qualification), and for
a genuinely separate, currently metrics-incapable deploy path (Snowsight's
native Ossie-file upload) that's worth knowing about but isn't what this
repo uses.

### 1. Convert to a semantic model

Pure offline conversion, no Snowflake account needed:

```bash
uv run snowflake/export_semantic_model.py
cat snowflake/semantic_model.yaml
```

Add `--warnings` to see what didn't survive (just `label` on 4 fields —
Cortex Analyst's format has no display-name equivalent, purely cosmetic).

### 2. Deploy to a real Snowflake account (optional)

Verified against a real account (2026-08-26) — creates its own warehouse,
database, and schema (no pre-existing resources needed, unlike
Databricks), creates + populates the tables, then creates a real, native,
**SQL-queryable Semantic View** (`CREATE SEMANTIC VIEW`, via the
`SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` stored procedure) — all 3 metrics
included, no AI/Cortex Analyst required to query it.

```bash
uv add snowflake-connector-python   # not a project dependency yet
cp .env.example .env   # fill in SNOWFLAKE_ACCOUNT / USER / PASSWORD
uv run snowflake/deploy_to_snowflake.py
```

Creates `OSSIE_DEMO.PUBLIC.customers`/`orders` and
`OSSIE_DEMO.PUBLIC.sales_demo` (the Semantic View) — `DATABASE`/`SCHEMA`/
`WAREHOUSE` constants at the top of the script, edit to point at existing
resources if you'd rather. Query it with plain SQL:

```sql
SELECT * FROM SEMANTIC_VIEW(
  OSSIE_DEMO.PUBLIC.sales_demo
  METRICS total_revenue, avg_order_value, order_count
  DIMENSIONS customer_segment
)
```

Confirmed real numbers back, matching every other target in this repo
exactly: `enterprise` $950.75 / 3 orders / $316.92 avg, `smb` $40.00 / 1 /
$40.00.

Getting there took two real fixes to `ossie-snowflake`'s raw converter
output (see NOTES.md for the full story — including an earlier, abandoned
attempt via Snowflake's *native* Ossie-YAML importer, which currently
can't import metrics at all regardless of syntax, a real and separate
limitation from what's fixed here):
1. `base_table` needs qualifying from the placeholder source path to
   where the tables actually get created.
2. **Metrics need to be nested inside their owning table, not one
   top-level list** — `ossie-snowflake` emits the latter, which Snowflake's
   native schema rejects outright (`Unsupported expression in the
   definition of derived metric <NAME>`, regardless of aggregate function
   or dialect). This demo's 3 metrics all aggregate order-level facts, so
   `deploy_to_snowflake.py`'s `_prepare_semantic_model` moves them all
   under `orders` — a model with metrics spanning multiple tables would
   need real per-metric table attribution the converter doesn't provide.

## Databricks vs Snowflake: what had to differ

`dbt/ossie/orders_customers.yaml` started as a byte-identical copy of
`databricks/ossie/orders_customers.yaml` - this repo doesn't use dbt-core's
own native OSI loader (it would want `version: "0.1.0"`/`"0.1.1"`, neither
of which this file has - see "Known issues (dbt)" above), it converts a
Databricks-shaped file through the separate `apache-ossie-dbt` package
instead. It differs by exactly one field now: `customers.customer_id`,
present here, dropped from the Databricks copy - see "Known issues (dbt)"
above for why (this converter needs it present, Databricks needs it
absent, opposite requirements on the same field). The remaining
source-file differences in this repo are between Databricks and
Snowflake:

| | Databricks | Snowflake |
|---|---|---|
| `customers.customer_id` field | Must be dropped from `fields` (kept only in `primary_key`) — Metric Views need globally unique dimension names across a flattened namespace, and `orders.customer_id`/`customers.customer_id` would collide | Tolerates either — confirmed by deploying the Databricks-shaped (absent) file as-is and querying it successfully |
| `data_type`/`datatype` | Never read at all (harmless either way) | **Required on every Dimension and Fact** — the local converter silently omits it with no warning when absent; only surfaces as a live validation failure |
| `dimension.is_time` | No equivalent field — silently dropped, cosmetic only | Preserved — becomes a `time_dimensions` entry instead of a plain `dimensions` one |
| Dataset-level `description` | Dropped — no per-source comment field | Preserved — each table keeps its own `description` |
| `label` | Becomes `display_name` | Dropped — no display-name equivalent |
| Conversion bugs | None found — conversion is clean, verified against a real workspace end to end | None in the *local* conversion step, but the raw output isn't directly deployable — needs `_prepare_semantic_model`'s two fixes (`base_table` qualifying, metrics re-nested per-table) before `CREATE SEMANTIC VIEW` accepts it; local converter gives zero warning about either |
| Query syntax | `SELECT dim, MEASURE(x) FROM view GROUP BY dim` | `SELECT * FROM SEMANTIC_VIEW(view METRICS x DIMENSIONS dim)` — plain SQL, no AI needed (Cortex Analyst NL querying is also available, separately) |

`snowflake/ossie/orders_customers.yaml` and
`databricks/ossie/orders_customers.yaml` are structurally identical (only
their explanatory comments differ). `dbt/ossie/orders_customers.yaml`
differs from both by exactly the one `customer_id` field described above;
everything else - descriptions, labels, relationships, all 3 metrics - is
identical across all three files.

## Layout

- `dbt/ossie/orders_customers.yaml` — the same model as Databricks/Snowflake, differing by one field (`customer_id` on `customers`) — see "Known issues (dbt)" above.
- `dbt/scripts/export_metric_view.py` — converts it via `apache-ossie-dbt`,
  overwrites `dbt/target/semantic_manifest.json`.
- `dbt/scripts/patch_manifest_for_mf_query.py` — the bug workaround, see
  "Known issues (dbt)" above.
- `databricks/ossie/orders_customers.yaml` — the same model, adapted for
  Databricks.
- `databricks/export_metric_view.py` — runs the conversion, writes
  `databricks/metric_view.yaml`.
- `databricks/deploy_to_databricks.py` — deploys tables + Metric View to a
  real workspace.
- `snowflake/ossie/orders_customers.yaml` — the same model again,
  structurally identical to the Databricks copy.
- `snowflake/export_semantic_model.py` — runs the conversion, writes
  `snowflake/semantic_model.yaml`.
- `snowflake/deploy_to_snowflake.py` — deploys tables + creates a native,
  SQL-queryable Semantic View. Verified against a real account — see
  "2. Deploy..." above.

## Further reading

`NOTES.md` has the full background: why the model copies differ, how each
bug above was found, and other gotchas hit along the way (naming drift
inside `apache-ossie-dbt` itself, a second Snowflake deploy path that
doesn't work yet, etc).
