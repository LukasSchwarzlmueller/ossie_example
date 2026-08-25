"""Human-readable summary of what differs between the dbt and Databricks
OSI model variants - for showing live instead of a raw JSON diff.
"""

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
DBT_MODEL = REPO_ROOT / "dbt" / "ossie" / "orders_customers.json"
DATABRICKS_MODEL = REPO_ROOT / "databricks" / "ossie" / "orders_customers.yaml"


def field_names(dataset: dict) -> set[str]:
    return {f["name"] for f in dataset.get("fields", [])}


def main() -> None:
    dbt = json.loads(DBT_MODEL.read_text())
    databricks = yaml.safe_load(DATABRICKS_MODEL.read_text())

    print(f"{DBT_MODEL.relative_to(REPO_ROOT)}  vs.  {DATABRICKS_MODEL.relative_to(REPO_ROOT)}")
    print()

    if dbt["version"] != databricks["version"]:
        print(f'  version:  "{dbt["version"]}"  ->  "{databricks["version"]}"')

    dbt_datasets = {d["name"]: d for d in dbt["semantic_model"][0]["datasets"]}
    databricks_datasets = {d["name"]: d for d in databricks["semantic_model"][0]["datasets"]}

    for name in dbt_datasets:
        dbt_fields = field_names(dbt_datasets[name])
        databricks_fields = field_names(databricks_datasets[name])
        removed = dbt_fields - databricks_fields
        added = databricks_fields - dbt_fields
        for field in sorted(removed):
            print(f"  {name}: field '{field}' removed")
        for field in sorted(added):
            print(f"  {name}: field '{field}' added")


if __name__ == "__main__":
    main()
