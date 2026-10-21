# Databricks (old Python converter)

Kept for reference. Upstream removed the Python Databricks converter (#531), so
`apache-ossie-databricks` is pinned to an older commit in `pyproject.toml`.
Use `databricks/` instead.

## Run

```bash
uv run databricks_python_deprecated/export_metric_view.py
uv run databricks_python_deprecated/deploy_to_databricks.py   # needs DATABRICKS_* in .env
```

## Findings

- Same Metric View content as the Java converter; only YAML quoting differs.
- `roundtrip_databricks/` and `powerbi_databricks/` still depend on this converter.

## Fixes needed

- None.
