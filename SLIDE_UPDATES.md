# Slide updates: Ossie upstream changes, October 2026

Branch `upstream-update-per-folder` (from `fabric-roundtrip`), all changes uncommitted.
Upstream state checked on 2026-10-26: `apache/ossie@c075743`, `apache/ossie-converters@8111496`.

## TL;DR

1. **The repo layout is unchanged:** every example folder keeps its own model copy. Each copy got
   only the edits the new spec requires.
2. **The spec now has name-resolution rules.** Metrics must name their table
   (`SUM(orders.order_amount)`), and keys and joins must use declared fields. Every copy follows both.
3. **Different dialects per platform still work exactly as before** (`DATABRICKS`, `SNOWFLAKE`,
   `DAX`, `ANSI_SQL`).
4. **OSSIE_SQL_2026 is now the spec's own dialect.** `databricks/` uses it as its example; the
   other copies stay on `ANSI_SQL`.
5. **DuckDB caught up:** the extension reads the current model shape on DuckDB 1.5.6+.
6. **New spec features that tools don't support yet:** the portable `sql:` form (only Microsoft
   reads it) and metrics defined on a dataset (no converter here).

Numbers are unchanged everywhere: enterprise 950.75 / 316.917 / 3, smb 40 / 40 / 1.

---

## 1. What changed upstream (timeline for a "moving target" slide)

| Date | Repo | Change | Effect on the demo |
|---|---|---|---|
| 10-21 | ossie (#523) | Converters moved to **apache/ossie-converters**; `apache/ossie` keeps spec + core library | Handled in the previous round |
| 10-21 | ossie (#591) | **Dataset-scoped metrics** (`datasets[].metrics`) next to model-level `metrics` | The spec's answer to "which table owns a measure". No converter supports it yet |
| 10-21 | converters (#6) | **DAX -> SQL on import** (`translate_dax=True`) for single-column aggregates | Available, not switched on in this repo |
| 10-22 | ossie (#486) | **Name resolution**: model-level metrics must write `dataset.field`; keys and relationship columns must be declared fields | All copies updated |
| 10-22 | converters (#52) | dbt: better aggregate handling | No change for our model |
| 10-24 | converters (#17) | Snowflake: drops a unique key that repeats the primary key | Not used in our model |
| 10-25 | ossie (#617) | **Spec decoupled from vendors**: dialect names are free text; optional top-level portable `sql:`; `dialects` optional | Not in the core version the converters pin yet |
| 10-26 | converters (#80) | Microsoft reads the portable `sql:` form | Only converter that does |
| Oct | DuckDB extension | `ossie` v0.3.0 for DuckDB 1.5.6 / 2.0.0 | Reads the flat model; the 1.5.5 build doesn't |

Still open upstream (unchanged): the dbt converter never sets `agg_time_dimension` (still
patched); the Snowflake converter emits metrics as one top-level list (still nested at deploy);
Metric View dimension names must be unique across joined tables.

---

## 2. Changes per example folder

| Folder | Change to the model copy | Effect on the output |
|---|---|---|
| all copies | `SUM(order_amount)` -> `SUM(orders.order_amount)`, same for `AVG` | dbt manifest and Power BI -> Databricks byte-identical; Snowflake now emits the qualified form |
| `databricks/` | `customers` key is now a **field `customer_key`** (expression `customer_id`), used in `primary_key` and `to_columns`; dialect `ANSI_SQL` -> **`OSSIE_SQL_2026`** | Join: `using: [customer_id]` -> `on: source.customer_id = customers.customer_key`; new dimension `customer_key`; otherwise byte-identical (the dialect rename changes nothing) |
| `databricks_python_deprecated/` | same `customer_key` field (still `ANSI_SQL`, since the old converter drops `OSSIE_SQL_2026` metrics) | Same join change |
| `snowflake/` | `customers.customer_id` is a **field again** | New dimension `customer_id` on `customers` |
| `duckdb/` | `semantic_model:` wrapper removed (flat, like the rest); DuckDB 1.5.5 -> 1.5.6 | Same numbers |
| `dbt/`, `microsoft/`, `roundtrip_powerbi/` | only the qualified metrics | Same as before |

Repo-wide: pins bumped to `ossie-converters@8111496` (on its own, every export stayed identical).
Not changed: `roundtrip_databricks/` (still the old Python converter, still prints its
`MISMATCH`, which comes only from quoting differences between the two converters) and
`powerbi_databricks/` (DAX measures still dropped).

---

## 3. Slide claims to change (old -> new)

| Topic | Old claim | New claim |
|---|---|---|
| Metric expressions | `SUM(order_amount)` works; only DuckDB needs it qualified | **The spec requires `SUM(orders.order_amount)`** for model-level metrics. Every target accepts it |
| Databricks workaround | Leave `customer_id` out of `customers.fields`, keep it only in `primary_key` | **No longer valid in the spec**: a key must be a declared field. Instead the `customers` key field is named `customer_key` |
| Databricks join | `using: [customer_id]` | `on: source.customer_id = customers.customer_key` |
| Snowflake copy | Identical to the Databricks one, no `customer_id` field | Has `customers.customer_id` as a field |
| DuckDB | Needs the old `semantic_model:` wrapper, only DuckDB 1.5.5 | **Flat model like every other copy**, DuckDB 1.5.6+ |
| Dialects | Fixed list of dialect names | **Free text since #617**; well-known names are listed in `extensions/dialects.md` |
| OSSIE_SQL_2026 | (not mentioned) | The only dialect whose meaning the spec defines; `ANSI_SQL` is now just a label |
| Versions | `apache/ossie@a5bdbbc` + `ossie-converters@853c529` | `ossie-converters@8111496`, DuckDB 1.5.6 |

---

## 4. Dialects: what's new

**Unchanged and still the core demo point: one field, a different dialect per platform.**

```yaml
- name: customer_name
  expression:
    dialects:
    - dialect: ANSI_SQL            # OSSIE_SQL_2026 in databricks/
      expression: "UPPER(customer_name)"
    - dialect: SNOWFLAKE
      expression: "INITCAP(customer_name)"
    - dialect: DATABRICKS
      expression: "LOWER(customers.customer_name)"
    - dialect: DAX
      expression: "UPPER(customers[customer_name])"
```

| Platform | Picks | Emits |
|---|---|---|
| Databricks Metric View | `DATABRICKS` | `LOWER(customers.customer_name)` |
| Snowflake semantic view | `SNOWFLAKE` | `INITCAP(customer_name)` |
| Power BI / Fabric | `DAX` | `UPPER(customers[customer_name])` |
| DuckDB, dbt | `ANSI_SQL` | `UPPER(customer_name)` |

**What OSSIE_SQL_2026 is:** Ossie's own expression language (`core-spec/expression_language.md`).
It's a subset of ANSI SQL:2003 for declaring fields and metrics: aggregates, `CASE WHEN`,
`DATEADD(day, 7, order_date)`, string and math functions, `FILTER (WHERE ...)`. It has no
`SELECT`, `JOIN`, `GROUP BY` or subqueries, because the semantic model supplies those. It's the
only dialect whose meaning the spec defines; every other dialect is opaque to Ossie.

**New: an optional top-level `sql:` key (#617)**, the "primary portable form":

```yaml
expression:
  sql: SUM(orders.order_amount)        # OSSIE_SQL_2026
  dialects:                            # optional now
  - dialect: DAX
    expression: SUM(orders[order_amount])
```

**What the tools read today** (tested with `total_revenue`):

| Tool | `dialect: OSSIE_SQL_2026` entry | new `sql:` key |
|---|---|---|
| Snowflake | ✅ | ❌ error `Missing expression` |
| Microsoft | ✅ | ✅ (the only one) |
| dbt | ✅ | ❌ rejected: the converters' core library is pinned before #617 |
| Databricks Java | ✅ | ❌ metric silently dropped |
| Databricks Python (deprecated) | ❌ metric dropped | ❌ |
| DuckDB extension | ✅ | ❌ error `no 'dialects' array` |

So the spec has a portable form, but the tools haven't caught up. The examples stay on `dialects`.

**Does `OSSIE_SQL_2026` change anything in this example?** No: output is identical with
`ANSI_SQL`. The benefit is only in what it says ("meant to work everywhere"). That's why only
`databricks/` uses it, as the example.

**Why the Power BI round trip stays on `ANSI_SQL`:** a Power BI column stores no dialect (only
`sourceColumn`), and the Microsoft converter writes every plain column back as `ANSI_SQL`
(hardcoded). With `OSSIE_SQL_2026` going in, every field would show up as relabelled in the diff.
That looks like a not-yet-implemented feature (no docs call it deliberate), so it's a candidate
upstream issue.

**Dialects don't survive a trip through one platform:** a platform keeps only the expression it
used. The other dialects only live in the Ossie file, which is an argument for keeping Ossie as
the source of truth.

**If the Databricks round trip moved to the Java converter:** its import labels plain SQL as
`OSSIE_SQL_2026` and keeps `DATABRICKS` only for Databricks-specific SQL (the old Python converter
labelled everything `DATABRICKS`). Tested:

| `DATABRICKS` expression | Label after Metric View -> Ossie (Java) |
|---|---|
| `LOWER(customers.customer_name)` | `OSSIE_SQL_2026` |
| `INITCAP(customers.customer_name)` | `DATABRICKS` |
| `concat_ws(' ', customers.customer_name, customers.customer_segment)` | `DATABRICKS` |
| `regexp_replace(customers.customer_name, ' .*', '')` | `DATABRICKS` |

---

## 5. Snippets for slides

**Name-resolution rule (from `spec.md`):**

> Field expressions use source columns. Keys, relationships and metrics use **fields**, and a
> model-level metric names the dataset: `SUM(orders.total_usd)`, never `SUM(total_usd)`.

**Databricks copy, the key as a field with its own name:**

```yaml
- name: customers
  primary_key: [customer_key]
  fields:
  - name: customer_key
    expression:
      dialects:
      - dialect: OSSIE_SQL_2026
        expression: customer_id        # same column, different field name
...
relationships:
- name: orders_to_customers
  from: orders
  to: customers
  from_columns: [customer_id]
  to_columns: [customer_key]
```

```yaml
# metric_view.yaml, before -> after
joins:
- name: customers
  using: [customer_id]                                   # before
  on: source.customer_id = customers.customer_key        # after
```

**Power BI still needs the table hint**, even with qualified metrics:

```yaml
custom_extensions:
- vendor_name: POWER_BI
  data: '{"table": "orders"}'
```

Tested without it: all three measures land on `customers` (`no home table recorded; the measure
is placed on 'customers'`). The converter doesn't use `orders.` in the expression. The numbers
would still be right, but the measures show up under the wrong table. Dataset-scoped metrics
(#591) would be the spec's way to say this, but no converter supports them yet.

---

## 6. Findings worth a slide ("interop is still rough")

1. **The new `sql:` form is readable by 1 of 5 tools** (table in section 4).
2. **Join key names: the tools disagree.** Databricks needs the two key field names to differ (one
   namespace). The dbt converter needs them to match (it names each entity after its own side, so
   `customer_id` -> `customer_key` gives MetricFlow no join path). The DuckDB extension joins on
   the key *field name* instead of its expression (a bug against the spec). That's why only the
   Databricks copies rename the key.
3. **There's still no row count every tool accepts.** A bare `COUNT(*)` is dropped by dbt and
   refused by Microsoft and DuckDB. `COUNT(orders.*)` works for dbt and Databricks (written back as
   `COUNT(*)`) and passes through to Snowflake, where `COUNT(alias.*)` skips rows that contain a
   NULL (not deployed yet). DuckDB still refuses it on its own. Microsoft uses the DAX version.
4. **"Which table owns a measure" has a spec answer, but no tool uses it.** Dataset-scoped metrics
   would replace the `POWER_BI` extension and Snowflake's nest-at-deploy step.
5. **Power BI hands back `ANSI_SQL` whatever went in** (section 4).
6. **DAX -> SQL exists now, but is deliberately narrow.** `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNTA`
   and `DISTINCTCOUNTNOBLANK` over one column are translated. `COUNTROWS`, `CALCULATE`, iterators
   and so on are refused rather than guessed. Not switched on in this repo.

---

## 7. Demo commands

Unchanged, apart from DuckDB now needing 1.5.6+ (the lock file has it):

```bash
uv run duckdb/query_metrics.py
```

The DuckDB CLI also needs 1.5.6 or newer to load the extension.

---

## 8. Open before the talk

- **Re-deploy Databricks and Snowflake.** Neither has been deployed with the new copies:
  `customer_key` join, qualified metrics, `COUNT(orders.*)` on Snowflake.
- **Run the Fabric round trip for real.** Only previewed offline; the model copy only changed in
  the qualified metrics.
- **Calculated columns in Fabric:** `NOTES.md` says Fabric accepted `customer_name` as a
  calculated column, while the Fabric round trip strips it because Direct Lake rejects it. Worth
  confirming which is right.
- **Upstream issues worth filing:** Power BI import labels plain columns `ANSI_SQL`; dbt entity
  naming across differently named keys; DuckDB extension joins on field names; the
  `ossie-converters` core pin predates `sql:`.
