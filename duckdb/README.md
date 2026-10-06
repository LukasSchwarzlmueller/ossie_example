# Apache Ossie -> DuckDB (query, not convert)

Every other target in this repo converts the model into something a platform
already understands. This one does not convert anything: the
[`ossie` DuckDB community extension](https://duckdb.org/community_extensions/extensions/ossie)
reads the Ossie YAML, compiles the request to SQL itself, and answers it.

```bash
uv run duckdb/query_metrics.py          # build the demo tables, then query
uv run duckdb/query_metrics.py --sql    # print the generated SQL instead
```

```
loaded sales_demo (0.2.0.dev0): 2 datasets, 7 fields, 1 relationship(s), 3 metrics

customer_segment    total_revenue   avg_order_value   order_count
smb                         40.00            40.000             1
enterprise                 950.75           316.917             3
```

Same figures as dbt, Databricks and Snowflake produce for the same model, which
is the point of checking it.

## The version pin is not optional

Community extensions are built per DuckDB version, and at the time of writing
`ossie` exists for **v1.5.5 only**. Every other version 404s on download:

```
HTTP Error: Failed to download extension "ossie" at URL
".../v1.5.6/linux_amd64/ossie.duckdb_extension.gz" (HTTP 404)
```

The repo pins `duckdb==1.5.5` already (via `dbt-duckdb`), so this works as-is.
Upgrading DuckDB breaks it until a matching build is published.

## What the model needed

`ossie/orders_customers.yaml` is the same `sales_demo` model as the other
targets, with three differences, all required by this extension.

**1. It requires a `semantic_model:` array the spec no longer has.** The flat
shape used by every other model in this repo is rejected outright:

```
ossie_load: document has no 'semantic_model' array
```

That wrapper is not merely out of fashion, it is gone. `OssieDocument` in the
current core package has `name`, `datasets`, `relationships` and `metrics` at
the root and nothing else, and `semantic_model` does not appear anywhere in
`apache-ossie` at all. Microsoft's converter rejects the wrapper for exactly
that reason (`Legacy 'semantic_model' wrappers are not supported; place model
properties at the document root`).

This repo used that wrapper too, until commit `d3bc6e8` ("update ossie
version", 20 September) flattened every model when the spec dropped it. So the
file in `duckdb/ossie/` is effectively a reversion to the shape everything here
had a few weeks ago.

Which makes this less a disagreement between implementations than a version
skew: the extension is built against a spec revision that has since been
removed, and the file it needs is one the rest of the ecosystem now refuses.

**2. Metric columns must be qualified as `dataset.field`.** `SUM(order_amount)`
is enough everywhere else, but here:

```
ossie_load: metric "total_revenue" references "order_amount"; a metric must
qualify every column as dataset.field so its grain is unambiguous
```

The prefix names the table the metric aggregates over, and that table becomes
the `FROM` clause. Without it `order_amount` is just a name, and summing over
`orders`, over `customers`, or over the joined result are three different
numbers.

`COUNT(*)` shows this sharply, because it names no column at all:

```
order_count alone            REFUSED: "has an aggregate with no column reference,
                             so there is no dataset to aggregate over"
order_count + total_revenue  OK: SELECT count_star(), sum(orders.order_amount)
                                 FROM main.orders
```

So `order_count` has no grain of its own and borrows one from whatever else is
in the query. The same metric is answerable or not depending on what you ask
for alongside it. (Microsoft's converter refuses the same expression for the
same reason: `'COUNT(*)' needs exactly one dataset to count rows of`.)

The good news is that the qualified form is accepted everywhere else, so this
does not fork the model as much as it first appears. Fed `SUM(orders.order_amount)`:

| Target | Result |
|---|---|
| DuckDB extension | required, this is the only accepted form |
| Databricks | accepted, silently rewritten back to `SUM(order_amount)`, which is correct since a Metric View references its source table's columns bare |
| Microsoft | accepted, translated to `SUM('orders'[order_amount])` |
| Snowflake | accepted, passed through unchanged |

So qualifying metric columns is the more portable choice, not the less. What
does not travel is `COUNT(*)`, which DuckDB refuses on its own and Microsoft
refuses outright, for the same reason in both cases.

**3. `ANSI_SQL` only, and no calculated fields.** The extension reads only
`ANSI_SQL` dialects, so the `SNOWFLAKE`/`DATABRICKS` variants of
`customer_name` carry nothing here, and `customer_name` is a plain column
reference rather than `UPPER(customer_name)`.

## The SQL it writes

```sql
SELECT customers.customer_segment AS "customers.customer_segment",
       sum(orders.order_amount)   AS total_revenue,
       avg(orders.order_amount)   AS avg_order_value,
       count_star()               AS order_count
FROM main.orders AS orders
INNER JOIN main.customers AS customers
  ON ((orders.customer_id = customers.customer_id))
GROUP BY customers.customer_segment
```

Note the `INNER JOIN`. The extension documents that every join is emitted as
`INNER`, so a customer with no orders would drop out of a result that a
`LEFT JOIN` would have kept. It does not matter for this demo, where every
customer has at least one order, and it would matter for a real model.

## Other functions

Beyond `ossie_load`, `ossie_query` and `ossie_compile`, the extension exposes
the parsed model for inspection:

| Function | Returns |
|---|---|
| `ossie_datasets()` | name, source, primary key, description |
| `ossie_fields()` | dataset, name, datatype, expression, synonyms |
| `ossie_metrics()` | name, datatype, expression, description |
| `ossie_relationships()` | from, to, columns, and the **derived cardinality** |

`ossie_relationships()` reports `many_to_one` for `orders_to_customers`, worked
out from the `primary_key` rather than declared in the model, which is the same
inference Databricks and Snowflake each do in their own way.

## Documented limits

From the extension's own page: one semantic model per file, table-backed
sources only, all joins `INNER`, and metrics that span multiple grains are
refused rather than answered.

## Opening the database in the DuckDB CLI

`--db` writes a database file that the DuckDB command line can open, so you can
query the tables and the model without Python. Four things trip people up.

**Use the exact filename.** `duckdb demo` creates a new, empty database called
`demo` in the current directory. The data is in `duckdb/demo.duckdb`:

```bash
cd /path/to/ossie_example    # the repo root
duckdb duckdb/demo.duckdb
```

Start from the repo root. The model path in `ossie_load` is relative to the
directory you launch from.

**Only one process can hold the file open.** While the CLI is running, the
Python script and any other DuckDB session get `Could not set lock on file`.
Exit the CLI with `.exit` before running `query_metrics.py --db` again.

**The model has to be loaded every session.** Only the tables and the saved
results persist. Each new session needs:

```sql
LOAD ossie;
SELECT * FROM ossie_load('duckdb/ossie/orders_customers.yaml');
```

**The CLI must be DuckDB 1.5.5.** The `ossie` extension only has a build for
that version, so a 1.5.6 CLI fails with `Extension ".../v1.5.6/.../ossie.duckdb_extension"
not found`. Run `duckdb --version` to check. If you need both versions, keep the
1.5.5 binary somewhere on its own and call it by full path.

Plain SQL on the tables needs none of this, so a newer CLI is fine for looking at the data.

**Saving an answer.** A query result can be stored as a table, and it then
works in any session with no extension:

```sql
CREATE OR REPLACE TABLE segment_report AS
SELECT * FROM ossie_query(
  ['total_revenue', 'avg_order_value', 'order_count'],
  ['customers.customer_segment']);
```

The table is a snapshot. It does not update when `orders` changes, and a fresh
session cannot re-run `ossie_query` against it, so rebuild the table after
changing the data or the model.
