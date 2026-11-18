# Databricks

Ossie -> Unity Catalog Metric Views, using upstream's Python converter.

## Run

```bash
uv run databricks/export_metric_view.py    # add --warnings to see what is dropped
uv run databricks/deploy_to_databricks.py  # needs DATABRICKS_* in .env
```

```sql
SELECT order_date, MEASURE(total_revenue), MEASURE(avg_order_value), MEASURE(order_count)
FROM <catalog>.<schema>.<view_name>_orders
GROUP BY ALL
```

## Findings

- The converter writes one Metric View per dataset and no joins, so `orders` and `customers` are separate views and revenue by `customer_segment` cannot be queried from one view.
- Only dataset-scoped metrics become measures, so the metrics in this model's copy live on `orders`.
- The converter names a view after its dataset, which would replace the table it reads. The deploy script creates `<view_name>_<dataset>` instead.
- The converter loads Ossie's validator from a checkout. `src/common/databricks_converter.py` clones the pinned commit into `.ossie-core/` on first use.

## Fixes needed

- Metrics moved to `datasets[orders].metrics`, and the `customer_name` Databricks expression no longer qualifies its column with the dataset name.
- The export replaces the `__catalog__.__schema__` placeholder before converting.
