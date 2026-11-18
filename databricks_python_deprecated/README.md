# Databricks (old Python converter)

Kept for reference. Upstream removed the Python Databricks converter (#531), so
`apache-ossie-databricks` is pinned to an older commit in `pyproject.toml`.
Use `databricks/` instead. This converter accepts `0.2.0.dev0` models only, so the model in this
folder stays on that version while the rest of the repo is on `0.3.0.dev0`.

## Run

```bash
uv run databricks_python_deprecated/export_metric_view.py
uv run databricks_python_deprecated/deploy_to_databricks.py   # needs DATABRICKS_* in .env
```

## Findings

- Same Metric View content as the Java converter; only YAML quoting differs.

## Fixes needed

- None.
