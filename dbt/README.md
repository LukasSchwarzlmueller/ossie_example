# dbt

Ossie -> dbt `semantic_manifest.json`, queried with MetricFlow on local DuckDB.

## Run

```bash
cd dbt
uv run dbt run
uv run scripts/export_metric_view.py
uv run scripts/patch_manifest_for_mf_query.py
uv run mf query --metrics total_revenue,avg_order_value,order_count --group-by customer_id__customer_segment
```

Re-run the patch step after every `dbt` command or export; both regenerate the file it edits.

## Findings

- dbt-core's own Ossie loader silently loads nothing from this model (wrong version, `.yaml` instead of `.json`), so the `apache-ossie-dbt` converter is used instead.
- The converter never sets `agg_time_dimension`, so nothing is queryable as produced.
- Ossie has no notion of a time spine, so the converter emits none.
- Two count bugs are fixed upstream (#432, #495): `COUNT(*)` came out as `expr: '*'`, and `order_count` landed on `customers`.

## Fixes needed

- `patch_manifest_for_mf_query.py` adds `agg_time_dimension` and copies the time spine declared in `models/metricflow_time_spine.yml`.
- The model says `COUNT(orders.*)`: a bare `COUNT(*)` with two datasets is dropped by the converter.
- `customers.customer_id` is kept as a field, otherwise `customers` gets no primary entity.
