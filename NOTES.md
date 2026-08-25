# Background notes

Why the repo looks the way it does, what was found along the way, and how
each finding was verified. This is the deep-dive companion to README.md —
read that first for how to actually run things.

## dbt: native support is real, but not what it first looks like

`dbt-core==1.12.3` has a real native OSI loader (`dbt/parser/osi.py`) —
confirmed by reading the source, not just docs. It's *not* the same thing
as the separate `apache-ossie-dbt` converter package (an offline
`semantic_manifest.json` <-> Ossie YAML translator) — this repo doesn't
use that package at all. dbt-core already depends on `metricflow` directly
(`Requires-Dist: metricflow<1.0,>=0.211.0`), and vendors its own
pydantic-v1 copy of the OSI schema inside it, separate from the
`apache-ossie` package.

Four things the native loader needs that a document valid against
`apache-ossie`'s current (`0.2.0.dev0`) types doesn't guarantee:

1. **`.json`, not `.yaml`** — the loader only globs `osi-paths/**/*.json`.
   Verified empirically: renaming `dbt/ossie/orders_customers.json` to
   `.yaml` produces no error at all — `dbt parse` succeeds cleanly, but
   `dbt list --resource-type metric` silently returns zero metrics. The
   file becomes invisible to the loader, not rejected by it.
2. **`version` must be exactly `"0.1.0"` or `"0.1.1"`**
   (`dbt.constants.SUPPORTED_OSI_VERSIONS`) — apache-ossie's own
   `OSIDocument.version` is just an unvalidated `str`, so this isn't
   enforced anywhere upstream; dbt is the one enforcing it.
3. **`dimension.is_time` is required**, not optional as in
   `ossie.models.OSIDimension` — a real, if minor, schema drift between
   dbt's vendored copy and the current `apache-ossie` package.
4. **`dataset.source` must resolve to an existing dbt model's relation**
   (`database.schema.table`, matched case-insensitively) — an OSI dataset
   attaches semantics to a table a dbt model already produces.

Also needed: a `metricflow_time_spine` model, since `order_date` is a time
dimension — a standard dbt semantic-layer requirement, not Ossie-specific.

## Databricks: a genuinely different, incompatible set of constraints

Converting the *same* `dbt/ossie/orders_customers.json` with
`ossie-databricks export` hits two hard, structural conflicts with what
dbt needs — not just cosmetic differences:

1. **Version is gated the other way.** `ossie-databricks` only accepts
   `version: "0.2.0.dev0"` and rejects `"0.1.1"` outright. dbt only accepts
   `0.1.0`/`0.1.1`. Same field, mutually exclusive requirements — there is
   no single value that satisfies both tools.
2. **Metric Views need globally unique dimension names; dbt/MetricFlow
   needs matching entity names across a relationship.** `orders.customer_id`
   (the FK) and `customers.customer_id` (the PK, declared as a field so
   dbt can build a PRIMARY entity from it — see `metricflow/converters/osi_to_msi.py`,
   which classifies entities by matching `dataset.primary_key` against a
   declared field's *name*) both end up as fields named `customer_id`.
   Databricks flattens every dataset's fields into one dimension namespace
   and refuses to guess which `customer_id` wins. dbt's join inference, on
   the other hand, *requires* both sides of the relationship to share that
   exact entity name — renaming either side to dodge the collision breaks
   the dbt join instead. Genuinely can't satisfy both from one file; traced
   this by reading `metricflow/converters/osi_to_msi.py`'s entity
   classification, not by guessing.

So `databricks/ossie/orders_customers.yaml` differs from the dbt version in
exactly two places (confirmed live via `scripts/diff_summary.py`): the
version tag, and `customers.customer_id` dropped from `fields` (kept in
`primary_key`, which is enough for Databricks to still derive
`rely.at_most_one_match` on the join correctly). Everything else —
descriptions, labels, `is_time` flags, the relationship, all 3 metrics —
is identical between the two files. `diff` the two files — that diff *is*
the demo-worthy part, not an implementation detail to hide.

It has to live outside `dbt/ossie/`, not just next to the dbt file: dbt's
native loader globs every `*.json` under `osi-paths` recursively, so
having both files in `dbt/ossie/` makes `dbt parse` also try to load the
Databricks one and fail on its version tag. Found this by actually running
it after moving both into the same folder for a "one demo directory"
cleanliness pass — another real gotcha, not a hypothetical one.

### File extension: only one side actually requires JSON

`dbt/ossie/orders_customers.json` **must** stay `.json` (see above — dbt's
loader filters by extension before parsing). `databricks/ossie/orders_customers.yaml`
has no such constraint: `ossie-databricks export` parses with plain
`yaml.load()` (see `_common.py`'s `load_yaml`), and JSON is valid YAML
syntax, so it accepts either extension with byte-identical output —
verified by converting the same content as both `.json` and `.yaml` and
diffing the resulting Metric View YAML (identical). It was originally
`.json` in this repo purely because it started as a copy of the dbt
version; renamed to `.yaml` to match Ossie's own docs, since nothing
required it to stay JSON.

## `dbt parse` succeeding does not mean the metrics are queryable

Actually tried to query a metric value with `mf query` (the
`dbt-metricflow` package's local CLI - it talks straight to the warehouse,
no dbt Cloud needed; `dbt sl query` is a different, Cloud-only command
that doesn't even exist in a plain `dbt-core` install). Every query - even
an ungrouped one, even for `total_revenue`, the simplest metric - failed
manifest validation with `Invalid aggregation time dimension
configuration`.

Root cause: dbt's native OSI conversion (`metricflow/converters/osi_to_msi.py`)
never sets `agg_time_dimension` anywhere - not in a semantic model's
`defaults`, not per-measure (it doesn't even populate `measures` at all;
aggregation lives inline on each metric's `metric_aggregation_params`
instead, a valid but less common MetricFlow shape - confirmed valid
because `mf query` parses that structure fine and fails on something else
entirely). MetricFlow requires an aggregation time dimension for *every*
query regardless of grouping, so nothing is queryable as-compiled, even
though `dbt parse` and `dbt list` both look completely healthy.

Along the way, found a second, independent bug: `order_count`
(`COUNT(*)`) gets attached to the wrong semantic model (`customers`
instead of `orders`) - the converter seems to resolve a metric's owning
dataset by finding a real column name in its SQL expression, and a bare
`COUNT(*)` has none, so it falls back to the wrong one. Visible directly
in `dbt/target/manifest.json`: `metric.order_count`'s `depends_on.nodes`
points at `semantic_model.customers`, while `total_revenue` and
`avg_order_value` correctly point at `semantic_model.orders`. Also
visible in the local docs UI (`dbt docs serve`) under the `order_count`
metric's "Depends On" tab.

`dbt/scripts/patch_manifest_for_mf_query.py` works around both by editing
the compiled `dbt/target/semantic_manifest.json` directly: sets
`orders.defaults.agg_time_dimension = "order_date"`, and fixes
`order_count`'s owning semantic model to `orders`. Verified live: after
patching, `mf query --metrics total_revenue --group-by
customer_id__customer_segment` (note: MetricFlow wants the fully
qualified `entity__dimension` name for a joined dimension, not the bare
column name - `customer_segment` alone fails resolution with a suggestion
list) returns real numbers - `enterprise` $950.75 / $316.92 avg,
`smb` $40.00 / $40.00 - matching the numbers independently verified on
the Databricks side.

**Does not fix `order_count` itself.** Even patched to point at the right
semantic model, `order_count` still fails at query time:
`COUNT(*)`-shaped OSI metrics compile to `SUM(CASE WHEN * IS NOT NULL
THEN 1 ELSE 0 END)`, which DuckDB rejects outright (`Binder Error: STAR
expression is only allowed as the root element of an expression`) -
confirmed by actually running `mf query --metrics order_count` post-patch
and getting that exact error. A deeper code-generation bug, not a missing
field - the patch script can't paper over it. Stick to
`total_revenue`/`avg_order_value` for a working demo.

**The patch doesn't stick.** It edits a generated file
(`target/semantic_manifest.json`), and *any* dbt command that recompiles
regenerates that file from scratch, silently reverting the patch.
Confirmed for `dbt run`, `dbt parse`, and `dbt docs generate` - and, less
obviously, `dbt show` too (`mf list metrics` failed right after running
`dbt show --select orders` for an unrelated raw-table check, because
`dbt show` recompiles as a side effect). Re-run
`patch_manifest_for_mf_query.py` immediately before every
`mf query`/`mf list` call, not just once after the first `dbt run`.

## dbt's local docs UI: real limitations, checked against the actual templates

Not just going on the general "free docs UI is limited" claim - actually
extracted and read the Angular templates dbt-core ships
(`dbt/task/docs/index.html`, the bundled single-page app) to see exactly
what renders:

- **Models** (`customers`, `orders`, `metricflow_time_spine`): full
  compiled SQL, columns, description. Fine.
- **Semantic Models**: Details, Description, **Entities** (name/type/expr)
  and Depends On. Confirmed by reading the template
  (`semantic_model.html`) that **Dimensions and Measures are not rendered
  at all** - not just the SQL, the entire list is missing from the UI.
  Cross-checked against `target/semantic_manifest.json`, which does have
  a real `dimensions` list (`order_date`, `order_amount` for `orders`) -
  the data exists, the UI just doesn't show it.
- **Metrics**: Details, Description, Depends On. No expression/SQL shown.

For the actual dimension/measure/expression detail, go straight to
`dbt/ossie/orders_customers.json` (the source) or
`dbt/target/semantic_manifest.json` (the compiled form) - the docs UI
isn't the right tool for that.

**DAG / lineage graph:** none of `customers.sql`, `orders.sql`, or
`metricflow_time_spine.sql` use `ref()`/`source()` - they're all literal
`VALUES`/`range()` SQL (confirmed by reading the files). So at the model
level, all three are genuinely isolated nodes with zero lineage edges to
each other - clicking into any one of them (not just
`metricflow_time_spine`) shows just that single node. The connected part
of the graph is one level up, through the semantic layer, confirmed via
`manifest.json`'s `depends_on`: `metric.total_revenue` ->
`semantic_model.orders` -> `model.orders`. Click into "Metrics" or
"Semantic Models" in the sidebar, not "Models", to see an actual chain -
and `order_count`'s chain visibly points at `semantic_model.customers`
instead of `orders`, which is the misattribution bug above, visible
live in the UI.

## Databricks side: clean conversion, verified real deploy

Unlike dbt, no bugs found in the Ossie -> Metric View conversion itself
(`ossie_databricks.ossie_to_metric_view`). Running
`databricks/export_metric_view.py --warnings` surfaces six warnings, three
kinds:

1. **`dimension.is_time` (on `order_date`, `customer_segment`) - dropped,
   cosmetic.** Metric Views have no "this is the time dimension" flag;
   the field still appears as a normal dimension, just without that
   marker.
2. **`primary_key`/`unique_keys` (on both datasets) - not lost,
   repurposed.** A Metric View doesn't store a source table's key
   directly, but the converter uses it to set `rely.at_most_one_match:
   true` on a join - visible on the `customers` join in
   `metric_view.yaml`. Only meaningful for a dataset actually joined *in*
   (not the fact table), so the `orders` warning is a bit of a false
   alarm - it fires whenever a `primary_key` is declared, whether or not
   it ends up used.
3. **`description` (on `customers`, `orders`) - dropped, real loss.** A
   Metric View has exactly one `comment` field, at the top level of the
   whole view (filled from the *model's* description). Per-dataset
   descriptions have nowhere to go and simply disappear.

**Deploy verified against a real workspace** (`databricks/deploy_to_databricks.py`,
run against a live Azure Databricks workspace): `CREATE OR REPLACE TABLE`
for `customers`/`orders`, then `CREATE OR REPLACE VIEW ... WITH METRICS
LANGUAGE YAML` for the Metric View, all `SUCCEEDED`. Then queried it for
real: `SELECT customer_segment, MEASURE(total_revenue),
MEASURE(avg_order_value) FROM ... GROUP BY customer_segment` returned
`enterprise` $950.75 / $316.92 avg, `smb` $40.00 / $40.00 - matching the
dbt-side numbers exactly.

Two real bugs found and fixed in `deploy_to_databricks.py` itself (not in
the Ossie/Databricks tooling) while doing this:

- `run()` never checked `result.status.error` or stopped on failure, so
  the script printed a false "Done" after all three statements had
  actually failed (first hit when `CATALOG` was wrong - hardcoded as
  `"ossie"`, the real workspace catalog is `"ossi"`). Fixed to print the
  real error and `raise SystemExit` on the first failure.
- The script's own "query it with" hint used invalid syntax (`MEASURES x,
  y` / `GROUP BY` as a separate clause) - Metric Views have no `MEASURES`
  clause. The correct form, confirmed against the live workspace, is
  `MEASURE(name)` inside the `SELECT` list. Fixed the hint and the
  docstring's stale "untested" claim.

## Misc

- **`.user.yml`**: created by dbt-core's anonymous usage-tracking
  (`dbt/tracking.py`), not by anything in this repo. `User(cookie_dir)` is
  initialized with `cookie_dir = profiles_dir`, so running commands with
  `DBT_PROFILES_DIR=.` writes `.user.yml` wherever the current directory
  happened to be at the time - which is why one first appeared at the
  repo root (a command run before the `cd dbt` convention was settled)
  rather than inside `dbt/`. Already covered by `.gitignore`'s `.user.yml`
  pattern regardless of location; harmless, just a random anonymous UUID.
