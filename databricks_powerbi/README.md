# Databricks Metric View -> Apache Ossie -> Power BI (live demo)

`metric_view.yaml` is a joined Metric View with one filtered measure (`enterprise_revenue`). It needs
the Java converter (`databricks/build_converter.sh`) and is also the input of `roundtrip_databricks/`.

```bash
uv run python -m common.databricks_converter databricks_powerbi/metric_view.yaml -o databricks_powerbi/db_ossie.yaml
uv run ossie-microsoft export -i databricks_powerbi/db_ossie.yaml -o databricks_powerbi/db_model.bim
```

`db_ossie.yaml` and `db_model.bim` are committed as fallback outputs (offline run, 2026-11-03).

Result in `db_model.bim`:
- `total_revenue` -> `SUM('orders'[order_amount])`, `avg_order_value` -> `AVERAGE('orders'[order_amount])`
- `order_count` (`COUNT(*)`) and `enterprise_revenue` (`SUM ... FILTER (WHERE ...)`) -> `BLANK()`,
  original SQL kept as annotations
- relationship `orders_to_customers` skipped: `'customers'[customer_id]` is not in the model
  (the metric view names the joined key `customer_key`)
- export exits 0 with "14 construct(s) could not be converted faithfully"

Not tested: the filtered measure on a live Databricks workspace, or opening `db_model.bim` in
Power BI Desktop / Fabric (the Direct Lake source uses placeholder ids).
