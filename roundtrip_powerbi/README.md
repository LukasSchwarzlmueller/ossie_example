# Power BI round trip: demo

Ossie -> Fabric semantic model -> Ossie, through a real Fabric workspace.

## Before the demo

1. `.env` has `FABRIC_WORKSPACE_ID`, `FABRIC_LAKEHOUSE_ID` and optionally
   `FABRIC_FOLDER_ID` (from the lakehouse URL `app.powerbi.com/groups/<workspace>/lakehouses/<lakehouse>`).
2. The `ossie` lakehouse has `dbo.customers` and `dbo.orders`, so the model
   shows data. The data is in `dbt/models/*.sql`.
3. Log in from a **Windows** PowerShell window. On WSL, the Linux `az` is blocked
   by Conditional Access (error 530033):
   ```powershell
   az login --tenant <tenant> --allow-no-subscriptions
   ```
4. Do a dry run and keep `out_fabric/` as a fallback.

## Demo

1. **Start:** show `ossie/orders_customers.yaml`: 2 tables, 1 relationship,
   3 metrics, several SQL dialects per expression.
2. **Run:**
   ```bash
   uv run roundtrip_powerbi/run_fabric_roundtrip.py
   ```
   It converts to `model.bim`, uploads to Fabric, downloads it again,
   converts back to Ossie and prints a diff. It writes two files to show:
   - `out_fabric/model.bim`, the model that goes into Fabric
   - `out_fabric/orders_customers.yaml`, the Ossie file that comes back
3. **Fabric:** open the `sales_demo` semantic model: Direct Lake, the measures
   and the relationship, plus one visual (Total Revenue by Customer Segment).
4. **Diff:** group the differences into three kinds:
   - Power BI can't hold it: `label`s and measure `datatype`s
   - only DAX survives: the SQL dialects are gone
   - Fabric restriction: Direct Lake allows no calculated columns, so `customer_name` loses `UPPER(...)`
5. **Takeaway:** tables, relationship, metrics and AI context survive the round trip
   through the real service. Vendor-specific details are kept in `custom_extensions`.

Without Fabric: `uv run roundtrip_powerbi/run_roundtrip.py` does the same round trip locally.
