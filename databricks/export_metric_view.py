"""Regenerate databricks/metric_view.yaml from the Ossie model.

Same conversion as `ossie-databricks export -i ... -o ...` -- just wrapped so the
live demo doesn't have to type the full command. Warnings (what the conversion
couldn't carry over -- see NOTES.md) are suppressed by default; pass --warnings
to show them.

Usage:
    uv run python3 databricks/export_metric_view.py [--warnings]
"""

import argparse
import warnings
from pathlib import Path

from ossie_databricks.ossie_to_metric_view import convert_ossie_to_metric_view

REPO_ROOT = Path(__file__).parent.parent
INPUT = REPO_ROOT / "databricks" / "ossie" / "orders_customers.yaml"
OUTPUT = REPO_ROOT / "databricks" / "metric_view.yaml"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warnings", action="store_true", help="show conversion warnings (hidden by default)"
    )
    args = parser.parse_args()

    with warnings.catch_warnings():
        if not args.warnings:
            warnings.simplefilter("ignore")
        view_yaml = convert_ossie_to_metric_view(INPUT.read_text())
    OUTPUT.write_text(view_yaml)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
