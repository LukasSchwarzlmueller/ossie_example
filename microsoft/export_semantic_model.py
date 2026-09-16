"""Convert microsoft/ossie/orders_customers.yaml to model.bim.

Replaces the model's `__catalog__.__schema__` source placeholder with
FABRIC_LAKEHOUSE/FABRIC_SCHEMA from .env before conversion - see NOTES.md.
Pass --warnings to see what didn't survive the conversion.
"""

import argparse
import json
import os
import warnings

from ossie_microsoft.ossie_to_semantic_model import convert_ossie_to_semantic_model

from common.env import REPO_ROOT, load_env_file

INPUT = REPO_ROOT / "microsoft" / "ossie" / "orders_customers.yaml"
OUTPUT = REPO_ROOT / "microsoft" / "model.bim"
PLACEHOLDER = "__catalog__.__schema__"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warnings", action="store_true", help="show conversion warnings (hidden by default)"
    )
    args = parser.parse_args()

    load_env_file()
    lakehouse = os.environ.get("FABRIC_LAKEHOUSE", "ossie")
    schema = os.environ.get("FABRIC_SCHEMA", "dbo")
    ossie_yaml = INPUT.read_text().replace(PLACEHOLDER, f"{lakehouse}.{schema}")

    with warnings.catch_warnings():
        if not args.warnings:
            warnings.simplefilter("ignore")
        bim = convert_ossie_to_semantic_model(ossie_yaml)
    OUTPUT.write_text(json.dumps(bim, indent=2))
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} (qualified for {lakehouse}.{schema})")


if __name__ == "__main__":
    main()
