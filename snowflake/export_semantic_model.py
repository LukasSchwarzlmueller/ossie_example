"""Convert snowflake/ossie/orders_customers.yaml to semantic_model.yaml.

Replaces the model's `__catalog__.__schema__` source placeholder with
SNOWFLAKE_DATABASE/SNOWFLAKE_SCHEMA from .env before conversion - see
NOTES.md. Pass --warnings to see what didn't survive the conversion.
"""

import argparse
import os
import warnings

from ossie_snowflake.converter import convert_ossie_to_snowflake

from common.env import REPO_ROOT, load_env_file

INPUT = REPO_ROOT / "snowflake" / "ossie" / "orders_customers.yaml"
OUTPUT = REPO_ROOT / "snowflake" / "semantic_model.yaml"
PLACEHOLDER = "__catalog__.__schema__"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warnings", action="store_true", help="show conversion warnings (hidden by default)"
    )
    args = parser.parse_args()

    load_env_file()
    database = os.environ.get("SNOWFLAKE_DATABASE", "OSSIE_DEMO")
    schema = os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC")
    ossie_yaml = INPUT.read_text().replace(PLACEHOLDER, f"{database}.{schema}")

    with warnings.catch_warnings():
        if not args.warnings:
            warnings.simplefilter("ignore")
        semantic_model_yaml = convert_ossie_to_snowflake(ossie_yaml)
    OUTPUT.write_text(semantic_model_yaml)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} (qualified for {database}.{schema})")


if __name__ == "__main__":
    main()
