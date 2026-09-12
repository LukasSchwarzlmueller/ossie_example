"""Regenerate snowflake/semantic_model.yaml from the Ossie model.

Same conversion as `ossie-snowflake -i ... -o ...` - just wrapped so the
demo doesn't have to type the full command. Warnings (what the conversion
couldn't carry over) are suppressed by default; pass --warnings to show
them.

`snowflake/ossie/orders_customers.yaml`'s `source:` fields hold the literal
placeholder `__catalog__.__schema__` instead of a real database/schema -
this script replaces it with `SNOWFLAKE_DATABASE`/`SNOWFLAKE_SCHEMA` from
`.env` (defaults `OSSIE_DEMO`/`PUBLIC`) before conversion, so the exported
semantic model's `base_table`s come out already qualified.
`deploy_to_snowflake.py` reads the same two env vars for where to create
the underlying tables, so export and deploy can't drift apart.

Usage:
    uv run python3 snowflake/export_semantic_model.py [--warnings]
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
