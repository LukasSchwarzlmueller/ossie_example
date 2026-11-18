# Power BI -> Databricks Metric View

Converts the Fabric export in `sample/` (Direct Lake) into Databricks Metric Views via Apache
Ossie, from either format:

```bash
uv run powerbi_databricks/export_metric_view.py              # TMSL and TMDL
uv run powerbi_databricks/export_metric_view.py --from tmdl  # or --from tmsl; --warnings to see what's dropped
```

| Way in | Input |
|---|---|
| TMSL | `sample/TMSL/model.bim` |
| TMDL | `sample/TMDL/definition/` - read via Microsoft TOM (needs the `tom` extra, `.tom/assemblies` and .NET), because `ossie-microsoft` has no folder input |

Catalog/schema come from `DATABRICKS_CATALOG` / `DATABRICKS_SCHEMA` (defaults `ossi` / `test`).
Both ways give the same result: one Metric View per table, **no join and no measures**.

One fix-up is needed before the Databricks export accepts the model: `dbo.orders` is not a 3-part
name, so the source becomes `<catalog>.<schema>.<tmsl|tmdl>_orders`.

**Measures are left out for now.** Power BI measures are DAX, `ossie-databricks` needs SQL, and
neither converter translates between them, so all 3 (`Total Revenue`, `Order Count`,
`Avg Order Value`) are dropped with a warning (`--warnings`); the export still exits 0.

Tables are prefixed with the input format, so both ways can live in one schema: `tmsl_orders`,
`tmsl_customers`, `tmdl_orders`, `tmdl_customers`.

## What the Power BI -> Ossie step needed

- **TMSL:** nothing special, `convert_semantic_model_to_ossie(json.loads(model.bim))`.
- **TMDL:** `ossie-microsoft` has no folder input (its CLI reads only a `.bim`, its library takes a
  single TMDL document as text). `read_tmdl()` in the script reads the folder with Microsoft TOM
  and hands the resulting TMSL to the same converter function. It uses two private helpers
  (`_load_tom`, `_assembly_directory`) of `ossie_microsoft.tom`, which may change without notice,
  and needs the `tom` extra, the TOM assemblies in `.tom/assemblies` and a .NET runtime.
- **Not used:** the converter's own single-document TMDL path. It fails when the database has no
  name, which is the case for this Fabric export (`tom.py` only recognizes `database <name>`).
- **Sample data:** the OneLake workspace and lakehouse IDs in `sample/` were replaced with
  placeholders. The Ossie output carries the whole `DirectLake - raw` M expression in its
  `nonportable_extensions`, so publishing an unsanitized export would publish those IDs.

## Deploy to Databricks

```bash
uv run powerbi_databricks/deploy_to_databricks.py --dry-run   # print the SQL only
uv run powerbi_databricks/deploy_to_databricks.py             # run it (same .env as ../databricks/)
```

Creates the prefixed tables (same demo rows as `databricks/deploy_to_databricks.py`) and one Metric
View per way and table, such as `tmsl_sales_demo_metrics_orders` and
`tmsl_sales_demo_metrics_customers` (`DATABRICKS_METRIC_VIEW_NAME` replaces `sales_demo_metrics`).
Run the export first.
