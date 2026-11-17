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

- One conversion bug: the converter wrote relationship columns into the join as field names (`customers.customer_key`) instead of the columns those fields read (`customers.customer_id`), so Databricks rejected the view. Fixed locally, see below.
- A Metric View flattens the joined tables into one namespace, so dimension names must be unique across all of them. `orders.customer_id` and `customers.customer_id` collide, so the join key cannot have the same field name on both sides.
- That is the opposite of what dbt needs, which is why the two model copies differ.
- Dropped with a warning: dataset descriptions, and primary keys as columns (they only set `rely.at_most_one_match` on the join).
- `COUNT(orders.*)` is written back as `COUNT(*)`.

## Fixes needed

- Converter: `databricks/patches/join-columns-resolve-fields.patch`, which `build_converter.sh` applies on top of the pinned commit. It maps each relationship column to its field's expression when building the join, so the join is `using: [customer_id]` again. Not upstream yet.
- The model names the `customers` key field `customer_key` (expression `customer_id`), and uses it in `primary_key` and the relationship's `to_columns`. It used to leave the key out of `customers.fields`, which the spec no longer allows: keys and relationship columns must be declared fields (apache/ossie#486). With the patched converter the join comes out as `using: [customer_id]`.
- Metric columns are qualified (`SUM(orders.order_amount)`), as the spec now requires; the converter writes them back unqualified, which is correct in a Metric View.
- The export replaces the `__catalog__.__schema__` placeholder before converting.
