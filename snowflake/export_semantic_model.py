"""Regenerate snowflake/semantic_model.yaml from the Ossie model.

Same conversion as `ossie-snowflake -i ... -o ...` - just wrapped so the
demo doesn't have to type the full command. Warnings (what the conversion
couldn't carry over) are suppressed by default; pass --warnings to show
them.

Usage:
    uv run python3 snowflake/export_semantic_model.py [--warnings]
"""

import argparse
import warnings
from pathlib import Path

from ossie_snowflake.converter import convert_osi_to_snowflake

REPO_ROOT = Path(__file__).parent.parent
INPUT = REPO_ROOT / "snowflake" / "ossie" / "orders_customers.yaml"
OUTPUT = REPO_ROOT / "snowflake" / "semantic_model.yaml"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warnings", action="store_true", help="show conversion warnings (hidden by default)"
    )
    args = parser.parse_args()

    with warnings.catch_warnings():
        if not args.warnings:
            warnings.simplefilter("ignore")
        semantic_model_yaml = convert_osi_to_snowflake(INPUT.read_text())
    OUTPUT.write_text(semantic_model_yaml)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
