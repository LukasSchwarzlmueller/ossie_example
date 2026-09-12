"""Regenerate databricks/metric_view.yaml from the Ossie model.

Same conversion as `ossie-databricks export -i ... -o ...` -- just wrapped so the
live demo doesn't have to type the full command. Warnings (what the conversion
couldn't carry over -- see NOTES.md) are suppressed by default; pass --warnings
to show them.

`databricks/ossie/orders_customers.yaml`'s `source:` fields hold the literal
placeholder `__catalog__.__schema__` instead of a real catalog/schema - this
script replaces it with `DATABRICKS_CATALOG`/`DATABRICKS_SCHEMA` from `.env`
(defaults `ossi`/`test`) before conversion, so the exported Metric View is
already fully qualified. `deploy_to_databricks.py` reads the same two env
vars for where to create the underlying tables, so export and deploy can't
drift apart.

Usage:
    uv run python3 databricks/export_metric_view.py [--warnings]
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
