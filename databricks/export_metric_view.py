"""Convert databricks/ossie/orders_customers.yaml to metric_view.yaml.

Uses the Java converter from apache/ossie-converters, pinned to its last commit
(see build_converter.sh). Replaces the model's `__catalog__.__schema__` source placeholder
with DATABRICKS_CATALOG/DATABRICKS_SCHEMA from .env before conversion - see
NOTES.md. Pass --warnings to see what the converter reports.

Needs JDK 21+ and the converter jar: run databricks/build_converter.sh once, or
point OSSIE_DATABRICKS_JAR at your own build - see README.md.
"""

import argparse
import os

from common.databricks_converter import ossie_to_metric_view
from common.env import REPO_ROOT, load_env_file

INPUT = REPO_ROOT / "databricks" / "ossie" / "orders_customers.yaml"
OUTPUT = REPO_ROOT / "databricks" / "metric_view.yaml"
PLACEHOLDER = "__catalog__.__schema__"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warnings", action="store_true", help="show converter output on stderr (hidden by default)"
    )
    args = parser.parse_args()

    load_env_file()
    catalog = os.environ.get("DATABRICKS_CATALOG", "ossi")
    schema = os.environ.get("DATABRICKS_SCHEMA", "test")
    ossie_yaml = INPUT.read_text().replace(PLACEHOLDER, f"{catalog}.{schema}")

    metric_view, messages = ossie_to_metric_view(ossie_yaml)
    OUTPUT.write_text(metric_view)
    if args.warnings and messages:
        print(messages)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} (qualified for {catalog}.{schema})")


if __name__ == "__main__":
    main()
