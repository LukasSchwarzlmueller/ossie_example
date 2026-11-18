# Databricks Metric View -> Ossie -> Power BI (live demo)

The talk demo: a Metric View in Databricks, converted through Ossie into a Power BI semantic
model, optionally uploaded to Fabric. The summary shows per measure, column and relationship
what arrives as is (green), what is lost (red) or wrong (yellow), and what a fix in Ossie gets back.

| File | What it does |
|---|---|
| `metric_view.yaml` | the Metric View: a join, synonyms, and three measures: SUM, filtered, window. `__catalog__.__schema__` comes from `.env` |
| `fixes.yaml` | DAX for the measures that don't translate from SQL |
| `setup_databricks.py` | creates `customers` / `orders` and the Metric View in Databricks, then queries every measure once |
| `run_trip.py` | Metric View -> Ossie -> fixes -> Power BI (-> Fabric) and the summary |
| `../src/common/metric_view_rescue.py` | repairs the official converter's Ossie file: tables, relationship, formulas |
| `output/` | written by `run_trip.py`: `ossie_converter.yaml` (the official converter's result), `ossie.yaml` (rescued), `ossie_fixed.yaml`, `model_raw.bim`, `model.bim` |

The official Python converter runs first. It wraps a Metric View as one table with no join, so a rescue
step repairs that Ossie file: it keeps the converter's names, descriptions and synonyms, and restores the
tables, relationship and formulas from the Metric View YAML. No JDK is needed. The rescue stops with an
error on what it cannot map: nested or `one_to_many` joins, join conditions other than equal columns,
wildcards, SQL query sources, and dimensions that read more than one table.

## Before the talk

```bash
uv run databricks_to_powerbi/setup_databricks.py            # Databricks: tables + Metric View
uv run databricks_to_powerbi/run_trip.py                    # real: pull from Databricks, upload to Fabric
uv run databricks_to_powerbi/run_trip.py --no-upload        # real Databricks, skip Fabric
uv run databricks_to_powerbi/run_trip.py --dry-run          # offline: no Databricks, no Fabric
```

- `setup_databricks.py --dry-run` prints the SQL without connecting.
- A real run reads the Metric View back from Databricks (`SHOW CREATE TABLE`), so it converts
  what Unity Catalog actually stores. `--dry-run` reads the local `metric_view.yaml` instead and
  writes `output/model_fabric.bim` (the model as it would be uploaded) without sending it.
- The Fabric upload needs `FABRIC_WORKSPACE_ID` / `FABRIC_LAKEHOUSE_ID` in `.env`. The lakehouse
  needs `dbo.customers` and `dbo.orders` (the same `ossie` lakehouse as `roundtrip_powerbi/`).
  The fixed model is uploaded (`--raw` for the unfixed one).
- Log in from a **Windows** PowerShell window. On WSL, the Linux `az` is blocked by Conditional
  Access (error 530033):
  ```powershell
  az login --tenant <FABRIC_TENANT> --allow-no-subscriptions   # FABRIC_TENANT from .env
  az account show --query user.name -o tsv   # must be the account with access to the workspace
  ```
  `run_trip.py` asks `az` for a fresh token on every run (same `get_token()` as
  `roundtrip_powerbi/`), so one login on the day of the talk is enough. If the run says
  `does not exist in MSAL token cache`, log in again. `FABRIC_TOKEN` in `.env` skips `az`, but a
  pasted token only lasts about 60-90 minutes.
- Run `--dry-run` last: a real run clears `output/` and only the dry run writes `model_fabric.bim`.
- Keep `output/` and screenshots of Databricks and Fabric as a fallback.

## Demo (~3 min)

1. **Databricks:** the Metric View in Catalog Explorer: the join and the three measures.
2. **Run:** `uv run databricks_to_powerbi/run_trip.py --step` (`--dry-run` as the offline fallback).
   `--step` waits for Enter before each summary line, so every line gets its sentence.
   The summary is in plain words (simple sum / count rows / business logic / time logic ->
   arrives / arrives empty / wrong), then what was fixed by hand. `--details` shows SQL,
   DAX and the converter's reasons instead.
3. **Fabric / Power BI:** the model with the relationship and the DAX measures.

## What the summary shows

The output first lists the steps (read from Databricks, the official converter's Databricks -> Ossie,
the rescue of its Ossie file, Ossie -> Power BI, upload), then "What arrives in
Power BI?": one line per measure and one for the model, each with one short line on why. Then
"Fixed in the Ossie file": what was added for this model by hand in `fixes.yaml` (DAX for the
measures, column types). The last line counts the measures that have DAX. It does not check their
numbers, so compare them in Fabric.

Not in the talk summary, only with `--details`: metadata. Descriptions arrive; display names
and formats are lost; synonyms land only as an `OssieAIContext` annotation, not as Power BI
synonyms (linguistic schema). The fix pass also maps the Databricks `format` to a Power BI
`formatString`.

As is (`model_raw.bim`):
- `total_revenue` (`SUM`) arrives as DAX.
- `enterprise_revenue` (`FILTER`) becomes `BLANK()`.
- `revenue_running_total` (window measure) arrives as a plain `SUM`: a wrong number, and the only
  warning is that the DATABRICKS nonportable_extensions were dropped.
- The relationship arrives through the rescue. The Metric View calls the customers key `customer_key`
  because its dimension names must be unique, and the rescue gives the field its real column name back, so
  Power BI gets `orders[customer_id] -> customers[customer_id]`. Databricks is not changed.
- No column types: a Metric View has none, so the Ossie fields have no `datatype` and the columns
  no `dataType`. Fabric refuses such a Direct Lake model (`RequiredOptionsMissing` /
  `allowPurgeData`), so the raw model (`--raw`) can't be uploaded.
- The Microsoft converter exits 0 either way.

Fixed (`model.bim`), all in the Ossie file between the rescue and the Microsoft converter, which stays unchanged:
- DAX from `fixes.yaml` as a second dialect (the intended Ossie way): the two measures work in
  Power BI, Databricks keeps reading the SQL
- column types from `fixes.yaml` (`datatypes`) as Ossie `datatype` on each field
- `enterprise_revenue` uses `KEEPFILTERS`: a plain `CALCULATE` filter replaces the segment
  filter, so `smb` would show the enterprise total instead of empty (Databricks: `NULL`)

After the upload, `run_trip.py` refreshes the model (Direct Lake framing); before that, queries
fail with "Cannot find table".

Reuses `Fabric`, `get_token` and `fabric_glue` from `roundtrip_powerbi/run_fabric_roundtrip.py`.
Tested live (2026-11-13, with the Java import): Metric View in Databricks, upload + refresh in Fabric;
the three measures return the same numbers in Fabric as in Databricks. The converter + rescue flow has not been
uploaded yet; its `model.bim` differs from that run only in the customers key name.
