# Power BI round trip

Ossie -> Power BI -> Ossie -> Power BI, with every intermediate file in `out/`.

## Run

Run from the repo root.

```bash
uv run roundtrip_powerbi/run_roundtrip.py   # add --tmdl for a TMDL folder (needs TOM), --warnings for drops
```

## Findings

- The two `model.bim` files have the same content, so the Power BI side is stable.
- The Ossie file does not come back the same. Lost: every non-DAX dialect, display labels, measure datatypes, and the catalog part of `source`.
- Gained: `POWER_BI` custom extensions holding partitions, format strings and the relationship name.

## Fixes needed

- None. The differences are expected, so the script reports them without failing.
