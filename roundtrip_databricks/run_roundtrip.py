"""Verify the Databricks Metric View <-> Ossie round trip is lossless.

NOT part of the live demo - a standalone check that `ossie-databricks`'s
export/import pair (`ossie_to_metric_view` / `metric_view_to_ossie`) is a
genuine, lossless round trip: Metric View -> Ossie -> Metric View again
reproduces the exact same YAML, byte for byte. Anything a Metric View has
that Ossie has no native field for (filter, window, format, rely,
cardinality, parameters, materialization) survives the trip via
`custom_extensions[DATABRICKS]`, not by being dropped.

Starts from the real `databricks/metric_view.yaml` - run
`export_metric_view.py` first. Writes the intermediate Ossie model and the
round-tripped Metric View here (`roundtrip_databricks/ossie/`,
`roundtrip_databricks/metric_view.yaml`) so you can inspect either side of
the trip; both are gitignored, regenerated each run.

Usage:
    uv run roundtrip_databricks/run_roundtrip.py
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
