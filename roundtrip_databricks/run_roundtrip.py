"""Not part of the talk - a side check that the Java converter's Metric View
-> Ossie -> Metric View round trip is lossless. Anything
Ossie has no native field for is preserved in a DATABRICKS extension
instead of being dropped. Uses the joined view in databricks_powerbi/.
"""

import difflib

import yaml

from common.databricks_converter import metric_view_to_ossie, ossie_to_metric_view
from common.env import REPO_ROOT

ROUNDTRIP_DIR = REPO_ROOT / "roundtrip_databricks"
ORIGINAL_MV = REPO_ROOT / "databricks_powerbi" / "metric_view.yaml"
ROUNDTRIPPED_OSSIE = ROUNDTRIP_DIR / "ossie" / "orders_customers.yaml"
ROUNDTRIPPED_MV = ROUNDTRIP_DIR / "metric_view.yaml"


def content(metric_view: str) -> dict:
    """The parsed view. The import regroups dimensions by dataset, so their order is not compared."""
    view = yaml.safe_load(metric_view)
    view["dimensions"] = sorted(view.get("dimensions", []), key=lambda d: d["name"])
    return view


def main() -> None:
    original_mv = ORIGINAL_MV.read_text()

    print("Step 1: Metric View -> Ossie (Java converter, import)")
    roundtripped_ossie, _ = metric_view_to_ossie(original_mv)

    print("Step 2: Ossie -> Metric View again (Java converter, export)")
    roundtripped_mv, _ = ossie_to_metric_view(roundtripped_ossie)

    ROUNDTRIPPED_OSSIE.parent.mkdir(parents=True, exist_ok=True)
    ROUNDTRIPPED_OSSIE.write_text(roundtripped_ossie)
    ROUNDTRIPPED_MV.write_text(roundtripped_mv)
    print(f"Wrote {ROUNDTRIPPED_OSSIE.relative_to(REPO_ROOT)}, {ROUNDTRIPPED_MV.relative_to(REPO_ROOT)}")

    if content(original_mv) == content(roundtripped_mv):
        print("\nRound trip OK: original and round-tripped metric_view.yaml have the same content.")
    else:
        diff = "".join(difflib.unified_diff(
            original_mv.splitlines(keepends=True),
            roundtripped_mv.splitlines(keepends=True),
            "original metric_view.yaml",
            "round-tripped metric_view.yaml",
        ))
        raise SystemExit(f"\nRound trip MISMATCH:\n\n{diff}")


if __name__ == "__main__":
    main()
