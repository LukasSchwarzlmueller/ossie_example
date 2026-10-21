# Databricks

Ossie -> Unity Catalog Metric View, using upstream's Java converter.

## Run

```bash
databricks/build_converter.sh              # once; needs JDK 21+, Maven, git
uv run databricks/export_metric_view.py    # add --warnings to see what is dropped
uv run databricks/deploy_to_databricks.py  # needs DATABRICKS_* in .env
```

To update the converter, change `CONVERTERS_REV` in `build_converter.sh`, or point
`OSSIE_DATABRICKS_JAR` at your own build.

```sql
SELECT customer_segment, MEASURE(total_revenue), MEASURE(avg_order_value), MEASURE(order_count)
FROM <catalog>.<schema>.<view_name>
GROUP BY ALL
```

## Findings

- No conversion bugs.
- A Metric View flattens the joined tables into one namespace, so dimension names must be unique across all of them. `orders.customer_id` and `customers.customer_id` collide, and the join key cannot be a field on both sides.
- That is the opposite of what dbt needs, which is why the two model copies differ.
- Dropped with a warning: dataset descriptions, and primary keys as columns (they only set `rely.at_most_one_match` on the join).
- `COUNT(orders.*)` is written back as `COUNT(*)`.

## Fixes needed

- None in the converter.
- The model leaves `customer_id` out of `customers.fields` and keeps it only in `primary_key`.
- The export replaces the `__catalog__.__schema__` placeholder before converting.
