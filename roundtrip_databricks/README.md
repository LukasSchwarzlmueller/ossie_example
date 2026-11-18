# Databricks round trip

Metric View -> Ossie -> Metric View, to check that nothing is lost.

## Run

```bash
uv run databricks/export_metric_view.py
uv run roundtrip_databricks/run_roundtrip.py
```

## Findings

- The content survives: the round-tripped `metric_view.yaml` parses to the same data as the original.
- What Ossie has no field for (`rely.at_most_one_match`) is kept in a `DATABRICKS` extension and restored.
- Both directions use the Java converter. The import regroups dimensions by dataset, so the script compares parsed content and ignores dimension order.

## Fixes needed

- None.
