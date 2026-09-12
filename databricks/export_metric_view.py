"""Convert databricks/ossie/orders_customers.yaml to metric_view.yaml.

Replaces the model's `__catalog__.__schema__` source placeholder with
DATABRICKS_CATALOG/DATABRICKS_SCHEMA from .env before conversion - see
NOTES.md. Pass --warnings to see what didn't survive the conversion.
"""

import argparse
import os
import warnings

from ossie_databricks.ossie_to_metric_view import convert_ossie_to_metric_view

from common.env import REPO_ROOT, load_env_file

INPUT = REPO_ROOT / "databricks" / "ossie" / "orders_customers.yaml"
OUTPUT = REPO_ROOT / "databricks" / "metric_view.yaml"
PLACEHOLDER = "__catalog__.__schema__"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warnings", action="store_true", help="show conversion warnings (hidden by default)"
    )
    args = parser.parse_args()

    load_env_file()
    catalog = os.environ.get("DATABRICKS_CATALOG", "ossi")
    schema = os.environ.get("DATABRICKS_SCHEMA", "test")
    ossie_yaml = INPUT.read_text().replace(PLACEHOLDER, f"{catalog}.{schema}")

    with warnings.catch_warnings():
        if not args.warnings:
            warnings.simplefilter("ignore")
        view_yaml = convert_ossie_to_metric_view(ossie_yaml)
    OUTPUT.write_text(view_yaml)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} (qualified for {catalog}.{schema})")


if __name__ == "__main__":
    main()
