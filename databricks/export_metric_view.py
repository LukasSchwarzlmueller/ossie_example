"""Convert databricks/ossie/orders_customers.yaml to metric_view.yaml.

Uses the Java converter from apache/ossie (the Python one was removed
upstream). Replaces the model's `__catalog__.__schema__` source placeholder
with DATABRICKS_CATALOG/DATABRICKS_SCHEMA from .env before conversion - see
NOTES.md. Pass --warnings to see what the converter reports.

Needs JDK 21+ and the converter jar: run databricks/build_converter.sh once, or
point OSSIE_DATABRICKS_JAR at your own build - see README.md.
"""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from common.databricks_converter import find_jar
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
    jar = find_jar()
    catalog = os.environ.get("DATABRICKS_CATALOG", "ossi")
    schema = os.environ.get("DATABRICKS_SCHEMA", "test")
    ossie_yaml = INPUT.read_text().replace(PLACEHOLDER, f"{catalog}.{schema}")

    with tempfile.TemporaryDirectory() as tmp:
        qualified_input = Path(tmp) / INPUT.name
        qualified_input.write_text(ossie_yaml)
        result = subprocess.run(
            ["java", "-jar", str(jar), "export", str(qualified_input), "-o", str(OUTPUT)],
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise SystemExit(f"converter failed:\n{result.stdout}{result.stderr}")
    if args.warnings and result.stderr:
        print(result.stderr)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} (qualified for {catalog}.{schema})")


if __name__ == "__main__":
    main()
