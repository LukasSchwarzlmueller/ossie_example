# Apache Ossie -> dbt, Databricks, Snowflake & Microsoft Fabric

One [Apache Ossie](https://ossie.apache.org/) semantic model, converted into
the native format of several platforms, to see what survives and what needs
fixing. The model is the same everywhere: `customers` and `orders` (1:n on
`customer_id`), with the metrics `total_revenue`, `order_count` and
`avg_order_value`.

## Targets

Each folder has a short README: how to run it, what was found, and which
fixes it needed.

| Folder | What it does | Needs | Result |
|---|---|---|---|
| [dbt/](dbt/README.md) | Ossie -> dbt semantic manifest, queried with MetricFlow | nothing, runs locally on DuckDB | works with a small patch step |
| [databricks/](databricks/README.md) | Ossie -> Unity Catalog Metric View | JDK 21+, Maven; a workspace to deploy | clean |
| [snowflake/](snowflake/README.md) | Ossie -> Snowflake semantic view | an account to deploy | works with one deploy-time fix |
| [microsoft/](microsoft/README.md) | Ossie -> Power BI / Fabric semantic model (Direct Lake) | .NET and TOM for TMDL; a workspace to deploy | clean |
| [duckdb/](duckdb/README.md) | queries the Ossie file directly, no conversion | nothing, runs locally | works with a differently shaped model |
| [powerbi_databricks/](powerbi_databricks/README.md) | Power BI model -> Ossie -> Metric View | .NET and TOM for TMDL | dimensions and joins only, DAX measures are dropped |
| [roundtrip_databricks/](roundtrip_databricks/README.md) | Metric View -> Ossie -> Metric View | the Databricks export | content survives |
| [roundtrip_powerbi/](roundtrip_powerbi/README.md) | Ossie -> Power BI -> Ossie -> Power BI | nothing | Power BI side stable, Ossie side loses detail |
| [databricks_python_deprecated/](databricks_python_deprecated/README.md) | the old Python Databricks converter | nothing | kept for reference |

## Setup

Needs [`uv`](https://docs.astral.sh/uv/), which manages the Python version
and all dependencies.

```bash
uv sync
cp .env.example .env   # only for deploying to Databricks, Snowflake or Fabric
```

`.env.example` documents every variable. The exports run without it and
fall back to default names.

Anything TMDL needs a .NET runtime and Microsoft's TOM assemblies in
`.tom/assemblies`, restored with `converters/microsoft/scripts/restore_tom.py`
from the [apache/ossie](https://github.com/apache/ossie) repo. The TMSL
(`model.bim`) paths need neither.

## Quick start

The dbt target needs no account:

```bash
cd dbt
uv run dbt run
uv run scripts/export_metric_view.py
uv run scripts/patch_manifest_for_mf_query.py
uv run mf query --metrics total_revenue,avg_order_value,order_count --group-by customer_id__customer_segment
```

```
customer_id__customer_segment      total_revenue    avg_order_value    order_count
-------------------------------  ---------------  -----------------  -------------
smb                                        40                40                  1
enterprise                                950.75            316.917              3
```

Databricks, Snowflake and DuckDB return the same numbers.

## The model

- Each target has its own copy in `<target>/ossie/orders_customers.yaml`. The
  copies are near-identical; the few fields that differ are explained in each
  folder's README and in `NOTES.md`.
- `source:` holds a placeholder, `__catalog__.__schema__`. Each export script
  replaces it with the catalog and schema from `.env` before converting, so
  export and deploy cannot target different places.

## Layout

- `<target>/export_*.py`: offline conversion, writes the target's native file.
- `<target>/deploy_to_*.py`: deploys against a real workspace or account.
- `src/common/`: shared `.env` loading and the Java converter wrapper.
- `pyproject.toml`: pins the `apache-ossie-*` packages to one upstream commit.

## Further reading

`NOTES.md` has the full background: every bug found, how it was found, and
why the model copies differ.
