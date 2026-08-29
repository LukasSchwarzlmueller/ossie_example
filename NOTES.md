# Background notes

Why the repo looks the way it does, and how each finding below was
verified. Deep-dive companion to README.md — read that first for how to
actually run things.

## dbt: native support is real, but stricter than the Ossie spec itself

`dbt-core==1.12.3` has a real native OSI loader (`dbt/parser/osi.py`) —
confirmed by reading the source. It's *not* the separate `apache-ossie-dbt`
converter package (an offline `semantic_manifest.json` <-> Ossie YAML
translator) — that package isn't even a dependency of this project and
isn't used for ingestion. dbt-core depends on `metricflow` directly and
vendors its own pydantic-v1 copy of the OSI schema, separate from the
`apache-ossie` package.

Four things the native loader needs that `apache-ossie`'s own types don't
guarantee:

1. **`.json`, not `.yaml`** — the loader globs `osi-paths/**/*.json` only.
   Renaming the file to `.yaml` produces no error: `dbt parse` succeeds,
   `dbt list --resource-type metric` silently returns zero metrics.
   Invisible to the loader, not rejected by it.
2. **`version` must be exactly `"0.1.0"` or `"0.1.1"`**
   (`dbt.constants.SUPPORTED_OSI_VERSIONS`) — `apache-ossie`'s own
   `OSIDocument.version` is an unvalidated `str`; dbt is what enforces this.
3. **`dimension.is_time` is required**, not optional as in `apache-ossie`'s
   `OSIDimension` — real schema drift between dbt's vendored copy and the
   current package.
4. **`dataset.source` must resolve to an existing dbt model's relation**
   (`database.schema.table`, case-insensitive).

Also needs a `metricflow_time_spine` model (`order_date` is a time
dimension — standard dbt semantic-layer requirement, not Ossie-specific).

**File extension is dbt's constraint alone.** `databricks/ossie/orders_customers.yaml`
and `snowflake/ossie/orders_customers.yaml` both accept either extension —
`ossie-databricks`/`ossie-snowflake` parse with plain `yaml.load()`/
`yaml.safe_load()`, and JSON is valid YAML syntax. Verified by converting
identical content as both `.json` and `.yaml` and diffing the output
(identical). Only `dbt/ossie/orders_customers.json` genuinely has to stay
`.json`.

## Databricks: one structural conflict with dbt, otherwise clean

Converting the same model with `ossie-databricks export` hits two
conflicts with what dbt needs:

1. **Version is gated the other way.** `ossie-databricks` only accepts
   `"0.2.0.dev0"`; dbt only accepts `0.1.0`/`0.1.1`. No single value
   satisfies both.
2. **Metric Views need globally unique dimension names; dbt/MetricFlow
   needs matching entity names across a relationship.** `orders.customer_id`
   (the FK) and `customers.customer_id` (the PK, needed so dbt can build an
   entity from it — see `metricflow/converters/osi_to_msi.py`'s entity
   classification) both become dimensions named `customer_id` once
   Databricks flattens every dataset into one namespace — a hard collision.
   dbt's join inference requires the opposite: both sides must share that
   exact name. Genuinely unsatisfiable from one file — traced by reading
   the entity classification code, not by guessing.

So `databricks/ossie/orders_customers.yaml` differs from dbt's copy in
exactly two places (`scripts/diff_summary.py`): `version`, and
`customer_id` dropped from `customers.fields` (kept in `primary_key`,
enough for Databricks to derive `rely.at_most_one_match` on the join).
Everything else — descriptions, labels, `is_time`, the relationship, all 3
metrics — is identical.

Has to live outside `dbt/ossie/`: dbt's loader globs every `*.json`
recursively, so a second file there breaks `dbt parse` on its version tag.

**Conversion itself is clean** — no bugs found in
`ossie_databricks.ossie_to_metric_view`. `export_metric_view.py --warnings`
surfaces three kinds of change, not bugs:

1. `dimension.is_time` — dropped, cosmetic (Metric Views have no
   equivalent flag).
2. `primary_key`/`unique_keys` — repurposed into `rely.at_most_one_match`
   on the relevant join, not lost.
3. Dataset-level `description` — dropped, real loss (Metric Views only
   have one top-level `comment`, filled from the model description).

**Deploy verified against a real workspace** (`databricks/deploy_to_databricks.py`):
tables + `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML`, all
succeeded. Queried it for real: `SELECT customer_segment,
MEASURE(total_revenue), MEASURE(avg_order_value) FROM ... GROUP BY
customer_segment` → `enterprise` $950.75/$316.92 avg, `smb` $40.00/$40.00.

Two real bugs found and fixed in the script itself along the way:
- `run()` never checked for errors, so it printed a false "Done" after all
  three statements had actually failed (first hit from a wrong hardcoded
  `CATALOG`). Fixed to surface the real error and stop on the first
  failure.
- The script's own query hint used invalid syntax (`MEASURES x, y` as a
  clause). The correct form, confirmed live, is `MEASURE(name)` inside the
  `SELECT` list.

**A `synonyms`/expression discrepancy turned out to be a stale view, not a
Databricks bug.** First deploy attempt showed `total_revenue`'s synonyms
persisting but `order_amount`'s and `avg_order_value`'s missing after the
fact (checked via `SHOW CREATE TABLE`, which is also how you inspect a
Metric View's stored YAML - `SHOW CREATE VIEW` is not valid Databricks SQL
syntax, `PARSE_SYNTAX_ERROR` confirmed live). Red flag: the same stored
YAML also had `customer_name`'s `expr` as bare `customers.customer_name`
with no `LOWER(...)`, even though the local `metric_view.yaml` already had
`LOWER(customer_name)` - a SQL function does not silently vanish on
`SHOW CREATE TABLE`, so the deployed view predated the current export.

The actual, real bug that caused this: `databricks/ossie/orders_customers.yaml`'s
`DATABRICKS`-dialect expression for `customer_name` was `LOWER(customer_name)`
- a bare, unqualified column reference inside a function call, on a field
that lives in the joined `customers` dataset while `orders` is the Metric
View's fact/source. `ossie_to_metric_view.py`'s `_convert_field` only
auto-qualifies a *simple* identifier expression (`is_simple_identifier`);
for anything more complex it can't safely rewrite the SQL and just warns
- `uv run python3 databricks/export_metric_view.py --warnings` prints
`[field 'customer_name'] complex expression on a joined table; emitted
as-is, verify qualification` - and passes it through unchanged. Databricks
then rejected the redeploy outright: `[UNRESOLVED_COLUMN.WITH_SUGGESTION]
... cannot be resolved`. Fixed by qualifying it in the source model:
`LOWER(customers.customer_name)`. The exporter still emits the same
warning after the fix (it can't tell qualified from unqualified, just
"not a bare identifier"), but the emitted `expr` is now correct.

After the fix, a completely fresh deploy round-trips everything
correctly - `SHOW CREATE TABLE` on the freshly created view shows
`order_amount`'s, `total_revenue`'s, and `avg_order_value`'s synonyms
all present, and `customer_name`'s `expr` as
`LOWER(customers.customer_name)`. No Databricks-side synonym bug exists;
the earlier finding was purely a stale-view artifact.

## Snowflake: two viable paths, one working, one currently metrics-incapable

Two genuinely different ways to get an Ossie model into Snowflake:

### Path A — `ossie-snowflake` (Python) + `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`

What `deploy_to_snowflake.py` actually uses. Convert with `ossie-snowflake`
(produces `semantic_model.yaml`, Snowflake's *native* Semantic View
format), then create the object directly from that YAML via this stored
procedure — a native, SQL-queryable `CREATE SEMANTIC VIEW`, no stage or
Cortex Analyst call needed.

Two real gaps between what the converter emits and what this procedure
needs, both handled by `_prepare_semantic_model`:

1. **`base_table` needs qualifying.** The converter bakes in the
   placeholder source path (`OSSIE_DEMO.MAIN`, from `ossie_demo.main.orders`)
   rather than where tables actually get created. Same class of bug as
   Databricks' `LOCAL_QUALIFIER`, just structural here (separate
   `database`/`schema`/`table` keys) instead of a string replace.
2. **Metrics must be nested inside their owning table, not one top-level
   list.** `ossie-snowflake` emits `metrics:` as a sibling of
   `tables:`/`relationships:`. Snowflake's native schema rejects that
   outright — every combination tried (`SUM`, `COUNT(*)`, `AVG()`, under
   both `ANSI_SQL` and `SNOWFLAKE` dialect tags) failed identically:
   `Unsupported expression in the definition of derived metric <NAME>`.
   Confirmed by comparing against Snowflake's own AI-suggested-metric
   output, which nests metrics per-table. Fixed by moving this demo's 3
   metrics (all order-level) under `orders`. `ossie-snowflake` doesn't
   attribute individual metrics to a table, so `METRICS_TABLE = "orders"`
   in `deploy_to_snowflake.py` is a real, flagged limitation — a model with
   metrics spanning multiple tables would need the converter to start
   emitting per-table metrics itself.

Verified end to end on a real trial account: warehouse/database/schema all
created by the script (no pre-existing resources needed, unlike
Databricks), tables created, Semantic View created, and queried for real —
`enterprise` $950.75/3 orders/$316.92 avg, `smb` $40.00/1/$40.00, matching
every other target exactly, `order_count`'s `COUNT(*)` included (Snowflake's
native metric handling doesn't share dbt's `COUNT(*)` codegen bug).

`customer_id` in `customers.fields`: not needed for this path. Tested
directly — took the Databricks-shaped file (`customer_id` absent)
unmodified, deployed it through this exact procedure, queried it
successfully. `snowflake/ossie/orders_customers.yaml` and
`databricks/ossie/orders_customers.yaml` are structurally identical as a
result (only their explanatory comments differ).

### Path B — Snowsight Workspaces' native "Ossie" upload

A separate, newer feature: upload a raw Ossie YAML file directly through
the UI (`SYSTEM$CREATE_SEMANTIC_VIEW_FROM_OSSIE_YAML` under the hood, no
Python conversion step). Gets you the structural half of a model
(tables/dimensions/facts/relationships) for free — but as tested,
**cannot currently import metrics at all**, regardless of aggregate
function or dialect (same "Unsupported expression..." error as Path A's
metrics bug, but here there's no workaround — metrics simply don't come
through). Also has its own constraints, distinct from the Python
converters:

- `ai_context` must be a plain string, not an object with `synonyms` — a
  third, independent interpretation of that field.
- Only `version: 0.1.1` is accepted (agrees with dbt, not the Python
  `apache-ossie-*` packages' `0.2.0.dev0`).
- Source paths need manual qualifying, same reason as Path A.

Workspaces separately offers a "Suggest metrics" AI-assist button —
unrelated to Ossie import; it inspects the table structure and proposes
its own metric (confirmed: suggested `total_revenue` with a description
bearing no resemblance to our source file, and never suggested
`order_count`, which our model also defines).

The resulting native Semantic View object from Path B is still fully
SQL-queryable and doesn't need pre-defined metrics — they can be supplied
ad hoc in the query itself: `SEMANTIC_VIEW(view METRICS expr AS name
DIMENSIONS dim)`. Confirmed with real numbers, matching everywhere else.
Not used as this repo's actual deploy path (Path A gets metrics through
cleanly, Path B doesn't), but worth knowing it exists.

## `dbt parse` succeeding does not mean the metrics are queryable

Actually tried to query a metric value with `mf query` (the
`dbt-metricflow` package's local CLI — talks straight to the warehouse, no
dbt Cloud needed; `dbt sl query` is a different, Cloud-only command that
doesn't exist in a plain `dbt-core` install). Every query — even an
ungrouped one, even `total_revenue`, the simplest metric — failed manifest
validation with `Invalid aggregation time dimension configuration`.

Root cause: dbt's native OSI conversion
(`metricflow/converters/osi_to_msi.py`) never sets `agg_time_dimension`
anywhere — not in a semantic model's `defaults`, not per-measure (it
doesn't even populate `measures`; aggregation lives inline on each
metric's `metric_aggregation_params` instead, a valid but less common
MetricFlow shape — confirmed valid because `mf query` parses that
structure fine and fails on something else entirely). MetricFlow requires
an aggregation time dimension for *every* query regardless of grouping, so
nothing is queryable as-compiled, even though `dbt parse`/`dbt list` look
completely healthy.

Second, independent bug: `order_count` (`COUNT(*)`) gets attached to the
wrong semantic model (`customers` instead of `orders`) — the converter
seems to resolve a metric's owning dataset by finding a real column name
in its SQL expression, and a bare `COUNT(*)` has none, so it falls back to
the wrong one. Visible directly in `dbt/target/manifest.json`:
`metric.order_count`'s `depends_on.nodes` points at
`semantic_model.customers`, while `total_revenue`/`avg_order_value`
correctly point at `semantic_model.orders`. Also visible in the local docs
UI under `order_count`'s "Depends On" tab.

`dbt/scripts/patch_manifest_for_mf_query.py` works around both by editing
the compiled `dbt/target/semantic_manifest.json` directly: sets
`orders.defaults.agg_time_dimension = "order_date"`, and fixes
`order_count`'s owning semantic model to `orders`. Verified live: after
patching, `mf query --metrics total_revenue --group-by
customer_id__customer_segment` (MetricFlow wants the fully qualified
`entity__dimension` name for a joined dimension, not the bare column name)
returns real numbers — `enterprise` $950.75/$316.92 avg, `smb`
$40.00/$40.00 — matching Databricks and Snowflake exactly.

**Does not fix `order_count` itself.** Even patched to point at the right
semantic model, `order_count` still fails at query time:
`COUNT(*)`-shaped OSI metrics compile to `SUM(CASE WHEN * IS NOT NULL THEN
1 ELSE 0 END)`, which DuckDB rejects outright (`Binder Error: STAR
expression is only allowed as the root element of an expression`) —
confirmed by actually running `mf query --metrics order_count` post-patch.
A deeper code-generation bug, not a missing field — the patch script can't
paper over it. Stick to `total_revenue`/`avg_order_value` for a working
demo.

**The patch doesn't stick.** It edits a generated file
(`target/semantic_manifest.json`), and *any* dbt command that recompiles
regenerates that file from scratch, silently reverting the patch.
Confirmed for `dbt run`, `dbt parse`, `dbt docs generate` — and, less
obviously, `dbt show` too. Re-run `patch_manifest_for_mf_query.py`
immediately before every `mf query`/`mf list` call, not just once after
the first `dbt run`.

## dbt's local docs UI: real limitations, checked against the actual templates

Not going on the general "free docs UI is limited" claim — extracted and
read the Angular templates dbt-core ships (`dbt/task/docs/index.html`) to
see exactly what renders:

- **Models** (`customers`, `orders`, `metricflow_time_spine`): full
  compiled SQL, columns, description. Fine.
- **Semantic Models**: Details, Description, Entities (name/type/expr),
  Depends On. Confirmed by reading the template that **Dimensions and
  Measures are not rendered at all** — the entire list is missing from the
  UI, not just the SQL. Cross-checked against `target/semantic_manifest.json`,
  which does have a real `dimensions` list — the data exists, the UI just
  doesn't show it.
- **Metrics**: Details, Description, Depends On. No expression/SQL shown.

For the actual dimension/measure/expression detail, go straight to
`dbt/ossie/orders_customers.json` or `dbt/target/semantic_manifest.json` —
the docs UI isn't the right tool for that.

**DAG / lineage graph:** none of `customers.sql`, `orders.sql`, or
`metricflow_time_spine.sql` use `ref()`/`source()` — they're all literal
`VALUES`/`range()` SQL. So at the model level, all three are genuinely
isolated nodes with zero lineage edges to each other. The connected part
of the graph is one level up, through the semantic layer:
`metric.total_revenue` -> `semantic_model.orders` -> `model.orders`. Click
into "Metrics" or "Semantic Models" in the sidebar, not "Models" — and
`order_count`'s chain visibly points at `semantic_model.customers` instead
of `orders`, the misattribution bug above, visible live in the UI.

## Misc

- **`.user.yml`**: created by dbt-core's anonymous usage-tracking
  (`dbt/tracking.py`), not by anything in this repo. `User(cookie_dir)` is
  initialized with `cookie_dir = profiles_dir`, so running commands with
  `DBT_PROFILES_DIR=.` writes `.user.yml` wherever the current directory
  happened to be at the time. Already covered by `.gitignore`'s
  `.user.yml` pattern regardless of location; harmless, just a random
  anonymous UUID.
