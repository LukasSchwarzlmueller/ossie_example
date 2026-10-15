# Ossie -> Power BI -> Ossie round trip

Two scripts, same input (`ossie/orders_customers.yaml`, a copy of the
Microsoft model):

| Script | What it does | Needs |
|---|---|---|
| `run_roundtrip.py` | converts locally only, Ossie -> `model.bim` -> Ossie | nothing beyond `uv sync` |
| `run_fabric_roundtrip.py` | uploads the model to a real Fabric workspace and pulls it back down before converting to Ossie | Fabric workspace + `az` login |

Run both from the repo root.

## Local round trip

```bash
uv run roundtrip_powerbi/run_roundtrip.py              # --tmdl also writes the TMDL folder (needs TOM)
```

Output in `out/`. See the script's docstring for the four steps.

## Fabric round trip

```
ossie/orders_customers.yaml
  1. -> out_fabric/model.bim                 Ossie -> Power BI (TMSL)
  2. -> out_fabric/model_uploaded.bim        Fabric fixes (see below)
  3. -> semantic model in the workspace      Fabric REST API: create, or update if it exists
  4. -> out_fabric/model_from_fabric.bim     Fabric REST API: getDefinition (TMSL)
  5. -> out_fabric/ossie_back/orders_customers.yaml   Power BI -> Ossie
```

It then prints the diff between the starting Ossie file and the one that came
back from Fabric.

### One-time setup

**1. Workspace and lakehouse.** You need a Fabric workspace on a Fabric/Premium
capacity, with a lakehouse named `ossie` (schemas enabled). Get the IDs from the
lakehouse URL `app.powerbi.com/groups/<workspace-id>/lakehouses/<lakehouse-id>`
and put them in `.env`:

```
FABRIC_WORKSPACE_ID=<workspace-id>
FABRIC_LAKEHOUSE_ID=<lakehouse-id>
FABRIC_FOLDER_ID=<folder-id>      # optional, folder the model is created in
```

To find a folder ID, list the workspace folders (`$FTOKEN` from step 3):

```bash
curl -s -H "Authorization: Bearer $FTOKEN" \
  https://api.fabric.microsoft.com/v1/workspaces/$FABRIC_WORKSPACE_ID/folders | python -m json.tool
```

**2. Demo tables.** The model is Direct Lake on `dbo.customers` / `dbo.orders`.
Upload and the roundtrip work without them, but the model shows no data. To
create them, open a Fabric notebook attached to the `ossie` lakehouse and run
this (the same data as `dbt/models/*.sql`):

```sql
%%sql
CREATE TABLE IF NOT EXISTS dbo.customers AS
SELECT * FROM VALUES
  (1, 'Alice Anders', 'enterprise'),
  (2, 'Bob Baker', 'smb'),
  (3, 'Carol Chen', 'enterprise')
AS t(customer_id, customer_name, customer_segment);

CREATE TABLE IF NOT EXISTS dbo.orders AS
SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date,
       CAST(order_amount AS DECIMAL(10,2)) AS order_amount
FROM VALUES
  (101, 1, '2026-01-05', 250.00),
  (102, 1, '2026-02-10', 90.50),
  (103, 2, '2026-02-11', 40.00),
  (104, 3, '2026-03-01', 610.25)
AS t(order_id, customer_id, order_date, order_amount);
```

**3. Login.** The script gets its token in this order:

1. `FABRIC_TOKEN` env var, if set
2. `az account get-access-token` (Linux `az`)
3. the Windows `az.cmd` via `powershell.exe` (WSL)

On WSL, tenants with a "device must be managed" Conditional Access policy
(error `AADSTS530033`) block the Linux `az` login, because WSL isn't the
managed device. Log in with the Windows CLI instead, in a **Windows**
PowerShell window, not one started from WSL, where the login window hangs:

```powershell
winget install -e --id Microsoft.AzureCLI        # once
az login --tenant <tenant> --allow-no-subscriptions
```

The subscription choice doesn't matter: the token is per account and tenant.
After that the script finds the token on its own. To get one by hand from WSL:

```bash
FTOKEN=$(powershell.exe -NoProfile -Command "cd C:\; & 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd' account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv" | tr -d '\r')
```

As a last resort, open app.powerbi.com, press F12, run `copy(powerBIAccessToken)`
in the console, and set the result as `FABRIC_TOKEN`. That gives a Power BI-scoped
token, valid for about an hour.

### Run

```bash
uv run roundtrip_powerbi/run_fabric_roundtrip.py              # --warnings shows what the converters drop
```

The first run creates the semantic model (named after the Ossie model,
`sales_demo`). Later runs update the same model in place.

### Fabric fixes (step 2)

Fabric rejects two things the converter emits, so the script patches them
before upload. `model.bim` stays the unmodified converter output, and
`model_uploaded.bim` is what Fabric receives:

- **`defaultPowerBIDataSourceVersion: powerBI_V3`**: Fabric only imports
  V3 models ("Import from JSON supported for V3 models only").
- **No calculated columns on Direct Lake tables.** `customers.customer_name`
  is `UPPER(customers[customer_name])` in the Ossie model. It is replaced by the
  physical column, so the expression is lost, and this shows up in the diff.

Fabric also leaves the model `name` out of the `model.bim` it returns, because
the name lives on the item. The script restores it from the uploaded model, so
it doesn't come back as `semantic_model`.

### What the diff shows

Compared with the local round trip, Fabric adds only the two fixes above (and
the real OneLake IDs in the model metadata). Everything else is the converter
pair's own behavior and appears in the local run too:

| Difference | Why |
|---|---|
| `label`s, measure `datatype`s gone | Power BI has nowhere to put them |
| ANSI_SQL / Snowflake / Databricks dialects gone, only DAX left | a Power BI model only holds DAX |
| new `custom_extensions` (`POWER_BI`) | Power BI-only details (partitions, relationship name, expressions) stashed so a second conversion back can restore them |
| relationship renamed | the converter derives the name from the columns; the original is kept in the stash |
| `customer_name` expression lost | Direct Lake restriction (Fabric fix above) |

Tables, relationship, the three metrics and the `ai_context` (descriptions,
synonyms, instructions) all survive.

## Demo run-of-show

Before the talk: log in on Windows, check that the two tables exist, do a dry
run, and keep `out_fabric/` as a fallback in case the network or Fabric is slow.

1. Show `ossie/orders_customers.yaml`: 2 tables, 1 relationship, 3 metrics,
   several dialects per expression.
2. Run `uv run roundtrip_powerbi/run_fabric_roundtrip.py`.
3. Open the semantic model in Fabric: Direct Lake, the measures and the
   relationship, plus one quick visual (Total Revenue by Customer Segment).
4. Walk through the diff using the three groups from the table above:
   Power BI can't hold it, only DAX survives, or it's a Fabric restriction.
5. Takeaway: the semantics survive a trip through the real service, and
   vendor-specific details are kept in `custom_extensions` instead of being lost.
