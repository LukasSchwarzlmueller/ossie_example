"""Convert databricks/ossie/orders_customers.yaml to databricks/metric_views/<dataset>.yaml.

Uses the Python converter from apache/ossie-converters, which writes one metric view per dataset.
Replaces the model's `__catalog__.__schema__` source placeholder with
DATABRICKS_CATALOG/DATABRICKS_SCHEMA from .env before conversion - see NOTES.md. Pass --warnings to
see what the converter reports.
"""

import argparse
import os
import shutil

from common.databricks_converter import ossie_to_metric_views
from common.env import REPO_ROOT, load_env_file

INPUT = REPO_ROOT / "databricks" / "ossie" / "orders_customers.yaml"
OUTPUT = REPO_ROOT / "databricks" / "metric_views"
PLACEHOLDER = "__catalog__.__schema__"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warnings", action="store_true", help="show converter warnings")
    args = parser.parse_args()

    load_env_file()
    catalog = os.environ.get("DATABRICKS_CATALOG", "ossi")
    schema = os.environ.get("DATABRICKS_SCHEMA", "test")
    ossie_yaml = INPUT.read_text().replace(PLACEHOLDER, f"{catalog}.{schema}")

    views, messages = ossie_to_metric_views(ossie_yaml, catalog, schema)
    shutil.rmtree(OUTPUT, ignore_errors=True)
    OUTPUT.mkdir()
    for dataset, view in views.items():
        (OUTPUT / f"{dataset}.yaml").write_text(view)
    if args.warnings and messages:
        print("\n".join(messages))
    print(f"Wrote {len(views)} metric views to {OUTPUT.relative_to(REPO_ROOT)}/ (qualified for {catalog}.{schema})")


if __name__ == "__main__":
    main()
