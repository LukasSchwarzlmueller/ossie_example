# Microsoft Fabric / Power BI

Ossie -> Direct Lake semantic model, as TMSL (`model.bim`) or TMDL.

## Run

Run from the repo root.

```bash
uv run microsoft/export_semantic_model.py                 # model.bim
uv run microsoft/export_semantic_model.py --tmdl-folder   # model/, needs .NET and TOM
uv run microsoft/package_for_fabric.py                    # wraps model/ for Fabric git sync
```

Or upload `model.bim` to a Lakehouse and run `upload_bim_to_fabric.ipynb`.

## Findings

- No conversion bugs. All three metrics become DAX measures on `orders`, and the relationship carries over.
- Dropped with a warning: display labels and measure datatypes.
- TMDL output is only the model definition, not a complete Fabric item.

## Fixes needed

- None in the converter.
- The model keeps `customers.customer_id`, adds `DAX` dialects, and tags each metric with a `POWER_BI` extension naming its table.
- `package_for_fabric.py` adds the `.platform` and `definition.pbism` files Fabric expects.
