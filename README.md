# Apache Ossie -> dbt, Databricks, Snowflake & Microsoft Fabric

Converts one [Apache Ossie](https://ossie.apache.org/) semantic model into
four targets: a dbt Core project, a Databricks Unity Catalog Metric View,
a Snowflake Cortex Analyst semantic model and a Power BI / Microsoft Fabric
semantic model (Direct Lake). Same source model everywhere (`customers` +
`orders`, 1:n on `customer_id`; metrics `total_revenue`, `order_count`,
`avg_order_value`) - see `NOTES.md` for how and why the four copies of that
model differ, and for the full story behind every fix mentioned below.

It also goes the other way once: an existing Power BI semantic model,
exported from Fabric, converted through Ossie into a Databricks Metric View
([Power BI -> Databricks](#power-bi---databricks)).

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) - manages the Python version and all
  dependencies.
- For Databricks/Snowflake/Fabric: real workspace/account access. Not
  needed for dbt, which runs entirely locally against DuckDB.
- For anything TMDL (Microsoft `--tmdl`/`--tmdl-folder`, Power BI ->
  Databricks `--from tmdl`): a .NET runtime and Microsoft's TOM assemblies
  in `.tom/assemblies`, restored with `converters/microsoft/scripts/restore_tom.py`
  from the [apache/ossie](https://github.com/apache/ossie) repo. The TMSL
  (`model.bim`) paths need neither.

```bash
uv sync
```

## dbt

```bash
cd dbt
uv run dbt run                                     # builds the tables
uv run scripts/export_metric_view.py               # Ossie -> semantic_manifest.json
uv run scripts/patch_manifest_for_mf_query.py       # works around 4 converter bugs, see NOTES.md
uv run mf query --metrics total_revenue,avg_order_value,order_count --group-by customer_id__customer_segment
cd ..
```

```
customer_id__customer_segment      total_revenue    avg_order_value    order_count
-------------------------------  ---------------  -----------------  -------------
smb                                        40                40                  1
enterprise                                950.75            316.917              3
```

`apache-ossie-dbt`'s converter has 4 real bugs, patched by the script
above (see NOTES.md for how each was found):
- no `agg_time_dimension` is ever set
- `order_count` attaches to the wrong semantic model
- no time spine is ever configured
- `COUNT(*)` is emitted as `expr: '*'`, which compiles to invalid SQL

Re-run the patch step before any further `mf` call after re-running
`export_metric_view.py` or any `dbt` command - it edits a generated file
that gets silently overwritten.

## Databricks

```bash
uv run databricks/export_metric_view.py
cat databricks/metric_view.yaml
```

Add `--warnings` to see what didn't survive the conversion. No conversion
bugs found here - the model just drops `customers.customer_id` as a field
(kept only in `primary_key`), since Metric Views need globally unique
dimension names across the flattened namespace; dbt's copy needs it
present instead (see NOTES.md).

To deploy to a real workspace:

```bash
cp .env.example .env   # fill in DATABRICKS_HOST / DATABRICKS_TOKEN / DATABRICKS_WAREHOUSE_ID
uv run databricks/export_metric_view.py    # re-run if DATABRICKS_CATALOG/SCHEMA change
uv run databricks/deploy_to_databricks.py
```

| `.env` variable | Required | Notes |
|---|---|---|
| `DATABRICKS_HOST` | yes | your workspace URL |
| `DATABRICKS_TOKEN` | yes | personal access token |
| `DATABRICKS_WAREHOUSE_ID` | yes | SQL warehouse to run against |
| `DATABRICKS_CATALOG` / `DATABRICKS_SCHEMA` | no | default `ossi`/`test`; must already exist |
| `DATABRICKS_METRIC_VIEW_NAME` | no | defaults to `sales_demo_metrics`; set if sharing a catalog/schema with others |

The Ossie model's `source:` fields hold a placeholder
(`__catalog__.__schema__`) - `export_metric_view.py` replaces it with
`DATABRICKS_CATALOG`/`DATABRICKS_SCHEMA` before conversion, so the exported
file is already qualified; `deploy_to_databricks.py` reads the same two
vars so export and deploy can't target different places.

```sql
SELECT customer_segment, MEASURE(total_revenue), MEASURE(avg_order_value), MEASURE(order_count)
FROM <catalog>.<schema>.<view_name>
GROUP BY ALL
```

## Snowflake

```bash
uv run snowflake/export_semantic_model.py
cat snowflake/semantic_model.yaml
```

To deploy to a real account (creates its own warehouse/database/schema):

```bash
uv add snowflake-connector-python   # not a project dependency yet
cp .env.example .env   # fill in SNOWFLAKE_ACCOUNT / USER / PASSWORD
uv run snowflake/export_semantic_model.py    # re-run if SNOWFLAKE_DATABASE/SCHEMA change
uv run snowflake/deploy_to_snowflake.py
```

Same placeholder-qualification pattern as Databricks, via
`SNOWFLAKE_DATABASE`/`SNOWFLAKE_SCHEMA`. One extra deploy-time fix:
`ossie-snowflake` emits all metrics as one top-level list, but Snowflake's
`CREATE SEMANTIC VIEW` requires them nested under their owning table -
`deploy_to_snowflake.py`'s `_nest_metrics_per_table` does that (see
NOTES.md). Tolerates `customers.customer_id` either way (unlike
Databricks), but needs `data_type`/`datatype` set on every field - silently
omitted otherwise, only surfacing as a live validation failure.

```sql
SELECT * FROM SEMANTIC_VIEW(
  OSSIE_DEMO.PUBLIC.sales_demo
  METRICS total_revenue, avg_order_value, order_count
  DIMENSIONS customer_segment
)
```

## Microsoft Fabric / Power BI

```bash
uv run microsoft/export_semantic_model.py                 # model.bim (TMSL)
uv run microsoft/export_semantic_model.py --tmdl          # model.tmdl, single file (needs TOM)
uv run microsoft/export_semantic_model.py --tmdl-folder   # model/, split per table (needs TOM)
```

Run from the repo root (TOM looks for `.tom/assemblies` relative to the
current directory, or `OSSIE_MICROSOFT_TOM_ASSEMBLIES`). Add `--warnings`
to see what's dropped: display `label`s and measure `datatype`s, neither of
which Power BI has a place for.

The result is a Direct Lake model: both tables read `<FABRIC_SCHEMA>.customers`
/ `.orders` from a Lakehouse, all three metrics become DAX measures on
`orders`, and the `orders -> customers` relationship carries over.

| `.env` variable | Required | Notes |
|---|---|---|
| `FABRIC_WORKSPACE_ID` / `FABRIC_LAKEHOUSE_ID` | no | from the Lakehouse URL `app.powerbi.com/groups/<workspace>/lakehouses/<lakehouse>`; unset gives placeholder OneLake ids |
| `FABRIC_LAKEHOUSE` | no | defaults to `ossie`; replaces the `__catalog__` part of the placeholder |
| `FABRIC_SCHEMA` | no | defaults to `dbo`; must match the schema the tables live under |

Two ways into a workspace:

- **Notebook upload** - upload `microsoft/model.bim` to the Lakehouse's
  **Files**, attach `microsoft/upload_bim_to_fabric.ipynb` to that
  Lakehouse and run it. It creates the semantic model via
  `semantic-link-labs`, or updates it if it already exists.
- **Git integration** - `export_semantic_model.py --tmdl-folder`, then
  `uv run microsoft/package_for_fabric.py` wraps `microsoft/model/` into a
  `<name>.SemanticModel/` item folder (adds `.platform` and
  `definition.pbism`) for a Fabric git-synced workspace. Pass
  `--logical-id <id>` on later runs to update the same item instead of
  creating a new one.

The Microsoft copy of the Ossie model differs from the others in three
ways: it keeps `customers.customer_id` (Power BI needs both ends of a
relationship as columns), adds `DAX` dialects next to the SQL ones, and
tags each metric with a `POWER_BI` custom extension naming the table the
measure lives on. See NOTES.md.

## Power BI -> Databricks

The reverse direction: a Power BI model exported from Fabric (in
`powerbi_databricks/sample/`, both as TMSL and as TMDL) converted through
Ossie into a Databricks Metric View.

```bash
uv run powerbi_databricks/export_metric_view.py --from tmsl   # or --from tmdl (needs TOM); default: both
uv run powerbi_databricks/deploy_to_databricks.py --dry-run   # same .env as databricks/
```

Dimensions and the join come through; **the measures don't** - Power BI
measures are DAX only, and nothing translates DAX to SQL, so all three are
dropped with a warning. Details in
[powerbi_databricks/README.md](powerbi_databricks/README.md).

## Layout

- `dbt/ossie/`, `databricks/ossie/`, `snowflake/ossie/`, `microsoft/ossie/` - the Ossie model, one copy per target (near-identical - see NOTES.md for the handful of fields that differ and why).
- `<target>/export_*.py` - offline conversion, writes the target-native file.
- `<target>/deploy_to_*.py` / `dbt run` + `mf query` - deploys/queries against the real thing.
- `microsoft/package_for_fabric.py`, `microsoft/upload_bim_to_fabric.ipynb` - the two ways to get the exported model into a Fabric workspace.
- `powerbi_databricks/` - the reverse path, Power BI semantic model -> Databricks Metric View, with its own README.
- `roundtrip_databricks/run_roundtrip.py` - not part of the talk; a side check that the Databricks export/import pair is lossless.
- `common/env.py` - shared `.env` loading, used by every export/deploy script.

## Further reading

`NOTES.md` has the full background: every bug found, how it was found, and
why the model copies differ.
