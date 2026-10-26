# Snowflake

Ossie -> Snowflake semantic view YAML.

## Run

```bash
uv run snowflake/export_semantic_model.py   # add --warnings to see what is dropped
uv run snowflake/deploy_to_snowflake.py     # needs SNOWFLAKE_* in .env; creates its own warehouse, database and schema
```

```sql
SELECT * FROM SEMANTIC_VIEW(
  OSSIE_DEMO.PUBLIC.sales_demo
  METRICS total_revenue, avg_order_value, order_count
  DIMENSIONS customer_segment
)
```

## Findings

- The converter emits all metrics as one top-level list; Snowflake rejects that.
- A field without `datatype` is silently left out and only fails at deploy.
- Dropped with a warning: display labels and `ai_context` instructions.
- Metric expressions are passed through unchanged, so `SUM(orders.order_amount)` and `COUNT(orders.*)` arrive qualified. Not yet deployed in that form; Snowflake's `COUNT(alias.*)` skips rows with a NULL in any column, unlike `COUNT(*)`.

## Fixes needed

- `deploy_to_snowflake.py` nests the metrics under `orders` before creating the view.
- Every field in the model has a `datatype`.
- `customers.customer_id` is a field again: the spec now requires keys and relationship columns to be declared fields (apache/ossie#486). It used to be left out, matching the Databricks copy.
- The export replaces the `__catalog__.__schema__` placeholder before converting.
