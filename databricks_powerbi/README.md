# Databricks Metric View -> Apache Ossie -> Power BI (live demo)

`metric_view.yaml` is a copy of `databricks/metric_view.yaml` plus one filtered measure
(`enterprise_revenue`). It is kept separate because `databricks/metric_view.yaml` is generated
by `databricks/export_metric_view.py` and checked byte-for-byte by `roundtrip_databricks/`.

```bash
J=.ossie-converters/databricks/java/target/ossie-databricks-converter-0.1.0-SNAPSHOT.jar
java -jar $J import databricks_powerbi/metric_view.yaml -o databricks_powerbi/db_ossie.yaml
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
