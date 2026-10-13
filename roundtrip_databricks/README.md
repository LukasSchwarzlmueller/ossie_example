# Databricks round trip

Metric View -> Ossie -> Metric View, to check that nothing is lost.

## Run

```bash
uv run databricks/export_metric_view.py
uv run roundtrip_databricks/run_roundtrip.py
```

## Findings

- The content survives: the round-tripped `metric_view.yaml` parses to the same data as the original.
- What Ossie has no field for (`rely.at_most_one_match`) is kept in `custom_extensions[DATABRICKS]` and restored.
- The script still reports `Round trip MISMATCH`. It compares bytes, and the input now comes from the Java converter (quoted strings) while the round trip uses the old Python one (unquoted).

## Fixes needed

- None to the converter. The script's byte comparison is out of date.
