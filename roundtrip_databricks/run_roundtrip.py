"""Not part of the talk - a side check that ossie-databricks' Metric View
-> Ossie -> Metric View round trip is lossless (byte-for-byte). Anything
Ossie has no native field for is preserved via
`custom_extensions[DATABRICKS]` instead of being dropped. Run
export_metric_view.py first.
"""

import difflib
import warnings

from ossie_databricks.metric_view_to_ossie import convert_metric_view_to_ossie
from ossie_databricks.ossie_to_metric_view import convert_ossie_to_metric_view

from common.env import REPO_ROOT

ROUNDTRIP_DIR = REPO_ROOT / "roundtrip_databricks"
ORIGINAL_MV = REPO_ROOT / "databricks" / "metric_view.yaml"
ROUNDTRIPPED_OSSIE = ROUNDTRIP_DIR / "ossie" / "orders_customers.yaml"
ROUNDTRIPPED_MV = ROUNDTRIP_DIR / "metric_view.yaml"


def main() -> None:
    if not ORIGINAL_MV.exists():
        raise SystemExit(
            "databricks/metric_view.yaml not found - run "
            "'uv run databricks/export_metric_view.py' first."
        )
    original_mv = ORIGINAL_MV.read_text()

    print("Step 1: Metric View -> Ossie (convert_metric_view_to_ossie)")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        roundtripped_ossie = convert_metric_view_to_ossie(original_mv)

    print("Step 2: Ossie -> Metric View again (convert_ossie_to_metric_view)")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        roundtripped_mv = convert_ossie_to_metric_view(roundtripped_ossie)

    ROUNDTRIPPED_OSSIE.parent.mkdir(parents=True, exist_ok=True)
    ROUNDTRIPPED_OSSIE.write_text(roundtripped_ossie)
    ROUNDTRIPPED_MV.write_text(roundtripped_mv)
    print(f"Wrote {ROUNDTRIPPED_OSSIE.relative_to(REPO_ROOT)}, {ROUNDTRIPPED_MV.relative_to(REPO_ROOT)}")

    if original_mv == roundtripped_mv:
        print("\nRound trip OK: original and round-tripped metric_view.yaml are byte-for-byte identical.")
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
