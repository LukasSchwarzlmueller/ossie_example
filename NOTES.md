# Background notes

Why the repo looks the way it does, and how each finding below was
verified. Deep-dive companion to README.md — read that first for how to
actually run things.

## dbt: dbt-core's own native OSI loader rejects this repo's model; a separate converter package is used instead

`dbt-core==1.12.3` has a real native OSI loader (`dbt/parser/osi.py`) —
confirmed by reading the source. It requires exactly `version: "0.1.0"` or
`"0.1.1"` (`dbt.constants.SUPPORTED_OSI_VERSIONS`), `.json` not `.yaml`
(the loader globs `osi-paths/**/*.json` only — renaming to `.yaml`
produces no error, `dbt parse` succeeds, `dbt list --resource-type metric`
silently returns zero metrics, invisible to the loader, not rejected by
it), `dimension.is_time` required rather than optional, and
`dataset.source` resolving to an existing dbt model's relation
(`database.schema.table`, case-insensitive).

`dbt/ossie/orders_customers.yaml` in this repo is `version: 0.2.0.dev0`,
the same shape as the Databricks/Snowflake copies — dbt-core's native
loader rejects it exactly the way described above: `dbt run`/`dbt list`
both succeed, and both report zero semantic models and zero metrics, no
error anywhere. Confirmed live, not assumed.

Instead, this repo uses the separate `apache-ossie-dbt` converter package
(an offline `semantic_manifest.json` <-> Ossie YAML translator, added to
the root `pyproject.toml`/`uv.lock`, pinned to a specific git commit of
`apache/ossie`) via `dbt/scripts/export_metric_view.py`, which converts
the Ossie YAML directly and overwrites `dbt/target/semantic_manifest.json`
with the result, bypassing dbt-core's native parser entirely. See the
next section for what that took.

**Naming drift within the same upstream repo, found and then fixed.** The
git commit this project had pinned in `pyproject.toml`/`uv.lock`
(`88e0011...`) predates an internal rename inside `apache/ossie` itself:
`OSIDocument` -> `OssieDocument`, `ossie_dbt.osi_to_msi.OSIToMSIConverter`
-> `ossie_dbt.ossie_to_msi.OssieToMSIConverter`, CLI subcommand
`osi-to-msi` -> `ossie-to-msi`. Found by diffing a fresh `git clone` of the
same repo against what was actually installed - same package, same public
API shape, different names, because the rename landed on a later commit
than the one this project had locked.

Re-pinned every `apache-ossie-*`/`osi-omni`/`honeydew-osi` source in
`pyproject.toml` to a newer commit (`b5da5d6...`) to pick up the rename.
`uv` requires one single resolved version of `apache-ossie` across the
whole dependency graph, so this had to happen for every converter at once,
not just `apache-ossie-dbt` — a partial upgrade (e.g. just `apache-ossie`
+ `apache-ossie-dbt`) fails to resolve outright, since the other
converters' own dependency on `apache-ossie` conflicts with a different
pinned commit for the same package name. Discovered along the way: three
more packages were renamed in the same upstream rename and needed updating
in `[tool.uv.sources]` too - `apache-ossie-gsf` -> `apache-ossie-nvidia-gsf`
(`converters/gsf` -> `converters/nvidia`), `honeydew-osi` ->
`honeydew-ossie`, `osi-omni` -> `ossie-omni`. A blind `uv lock --upgrade`
to the latest commit on `main` fails outright before any of that: it also
tries to move `apache-ossie-gsf` to `converters/gsf`, a path that doesn't
exist any more at that commit.

One function-level rename outside the dbt converter, found by actually
re-running every export script after the upgrade rather than assuming it
still worked: `ossie_snowflake.converter.convert_osi_to_snowflake` ->
`convert_ossie_to_snowflake`, fixed in `snowflake/export_semantic_model.py`.
`databricks/export_metric_view.py` needed no changes - that converter
never imports typed classes from the `ossie` package at all, confirmed by
grepping its source, so it was never exposed to any of this renaming.

## Databricks: one structural conflict with dbt-core's native loader, otherwise clean

Converting the same model with `ossie-databricks export` reveals two
requirements that flatly conflict with what dbt-core's own native OSI
loader wants — not `apache-ossie-dbt`, the separate package this repo
actually uses for dbt, which enforces neither of these (see the dbt
sections above and in README.md):

1. **Version is gated the other way.** `ossie-databricks` only accepts
   `"0.2.0.dev0"`; dbt-core's native loader only accepts `0.1.0`/`0.1.1`.
   No single value satisfies both.
2. **Metric Views need globally unique dimension names; dbt-core's native
   loader needs matching entity names across a relationship.**
   `orders.customer_id` (the FK) and `customers.customer_id` (the PK,
   needed so dbt-core's native loader can build an entity from it — see
   `metricflow/converters/osi_to_msi.py`'s entity classification) both
   become dimensions named `customer_id` once Databricks flattens every
   dataset into one namespace — a hard collision. dbt-core's native join
   inference requires the opposite: both sides must share that exact
   name. Genuinely unsatisfiable from one file for that loader — traced by
   reading the entity classification code, not by guessing.

Because of this, `dbt/ossie/orders_customers.yaml` in this repo is not
reconciled with dbt-core's native loader at all — it's converted instead
through `apache-ossie-dbt`'s separate converter package. Pointed at
dbt-core's own native loader, this file silently yields zero metrics
rather than erroring (see "Known issues (dbt)" in README.md) — it was
never meant to satisfy that loader's constraints.

It's also *not* byte-identical to `databricks/ossie/orders_customers.yaml`
(it was, until a third dbt-side bug forced one field back in — see the
next section): `customers.fields` includes `customer_id` here, dropped
there. Two real, opposite requirements on the same field, not a bug in
either converter — Databricks needs it absent (unique dimension names
across the flattened namespace), this one needs it present (see below).

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

## apache-ossie-dbt's own converter has three real bugs, confirmed by running `mf query`

(Getting there at all needs a small detour first: `ossie-dbt ossie-to-msi
-i <any ossie yaml> -o out.json`, the package's own CLI, currently crashes
on every input with `AttributeError: 'PydanticSemanticManifest' object has
no attribute 'model_dump_json'` — a Pydantic v1/v2 mismatch in the CLI's
own code, confirmed against all three of this repo's model files. Read as
"broken right now," not a structural finding — plausibly a one-line fix
whenever someone notices. `dbt/scripts/export_metric_view.py` works around
it by calling `OssieToMSIConverter` directly and serializing with
`.json(by_alias=True, exclude_none=True, indent=2)` instead of the CLI's
`.model_dump_json(...)`.)

Once that's bypassed, three real bugs in the converter itself, confirmed
by running `mf query` against the result:

1. **`agg_time_dimension` missing everywhere** — not in a semantic
   model's `defaults`, not per-measure. MetricFlow requires this for
   every query regardless of grouping, so nothing is queryable as
   produced. Identical bug to dbt-core's own native OSI loader
   (`metricflow/converters/osi_to_msi.py`, a completely separate
   codebase) — same failure, independently confirmed in a second,
   unrelated implementation.
2. **`order_count` attached to the wrong semantic model** (`customers`
   instead of `orders`) — same root cause and same bug as dbt-core's
   native loader: the converter resolves a metric's owning dataset by
   finding a real column name in its SQL expression, and a bare
   `COUNT(*)` has none, so it falls back to the wrong one. Two
   independent codebases, same heuristic, same failure mode.
3. **`time_spine_table_configurations` always empty** — new, specific to
   this converter. It converts an Ossie YAML file in isolation, with no
   access to the dbt project it'll eventually run inside, so it has no
   way to look up the project's real `metricflow_time_spine` model the
   way dbt-core's native loader can (that one runs inside the project
   itself). Without this, `mf query` fails before even reaching the
   `agg_time_dimension` problem: `At least one time spine must be
   configured to use the semantic layer, but none were found.`
A fourth one looked like a bug at first and turned out to be a real
structural conflict instead: `customers` came out with zero `entities`,
despite the source YAML declaring `primary_key: [customer_id]` on it
(`No primary entity found in semantic_model.reference=...customers`).
Narrower than "the converter ignores `primary_key`": it only turns a
`primary_key` column into an entity if that column is *also* declared as
a field on the same dataset, confirmed by adding `customer_id` back as a
field and re-running the converter, which then produced the entity
correctly. `customer_id` had been deliberately dropped from
`customers.fields` for Databricks' sake (see above). Fixed by adding it
back as a field on `customers` in `dbt/ossie/orders_customers.yaml`
specifically, which is why that file is no longer byte-identical to the
Databricks copy: one real, opposite requirement on the same field, not a
bug in either converter.

`dbt/scripts/patch_manifest_for_mf_query.py` fixes all four directly on
the compiled `dbt/target/semantic_manifest.json`, run after
`export_metric_view.py` (which itself needs `dbt run` to have already
built the real tables). Verified live: `mf query --metrics
total_revenue,avg_order_value --group-by customer_id__customer_segment`
returns real numbers — `enterprise` $950.75/$316.917 avg, `smb`
$40.00/$40.00 — matching Databricks and Snowflake exactly.

**Still does not fix `order_count` itself**, same as dbt-core's native
loader: even correctly attributed, `COUNT(*)`-shaped metrics compile to
`SUM(CASE WHEN * IS NOT NULL THEN 1 ELSE 0 END)`, which DuckDB rejects
outright (`Binder Error: STAR expression is only allowed as the root
element of an expression`) — confirmed by actually running `mf query
--metrics order_count` post-patch. A MetricFlow query-engine
code-generation bug, identical regardless of which converter produced the
manifest. Stick to `total_revenue`/`avg_order_value` for a working demo.

**The patch doesn't stick.** It edits a generated file
(`target/semantic_manifest.json`), and *any* dbt command that recompiles,
or re-running `export_metric_view.py`, regenerates that file from
scratch, silently reverting the patch. Re-run
`patch_manifest_for_mf_query.py` immediately before every `mf query`/
`mf list` call.

## Misc

- **`.user.yml`**: created by dbt-core's anonymous usage-tracking
  (`dbt/tracking.py`), not by anything in this repo. `User(cookie_dir)` is
  initialized with `cookie_dir = profiles_dir`, so running commands with
  `DBT_PROFILES_DIR=.` writes `.user.yml` wherever the current directory
  happened to be at the time. Already covered by `.gitignore`'s
  `.user.yml` pattern regardless of location; harmless, just a random
  anonymous UUID.
