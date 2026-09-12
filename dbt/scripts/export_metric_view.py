"""Convert dbt/ossie/orders_customers.yaml via apache-ossie-dbt, overwriting
target/semantic_manifest.json - not dbt-core's own native OSI loader, which
rejects this file's version outright. See NOTES.md.
"""

import json
from pathlib import Path

import yaml
from ossie import OssieDocument
from ossie_dbt.ossie_to_msi import OssieToMSIConverter

REPO_ROOT = Path(__file__).parent.parent.parent
INPUT_PATH = REPO_ROOT / "dbt" / "ossie" / "orders_customers.yaml"
OUTPUT_PATH = REPO_ROOT / "dbt" / "target" / "semantic_manifest.json"  # `mf query` reads dbt's compiled manifest from here


def main() -> None:
    print(f"Step 1: load {INPUT_PATH.relative_to(REPO_ROOT)}")
    raw = yaml.safe_load(INPUT_PATH.read_text())

    print("Step 2: validate as an OssieDocument")
    document = OssieDocument.model_validate(raw)

    print("Step 3: convert via OssieToMSIConverter")
    result = OssieToMSIConverter().convert(document)

    if result.issues:
        print(f"Step 4: {len(result.issues)} conversion issue(s):")
        for issue in result.issues:
            print(f"  [warning] {issue.issue_type.value}: {issue.element_name}")
    else:
        print("Step 4: zero conversion issues")

    print(f"Step 5: write {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    # .json(), not .model_dump_json() - result.output is a Pydantic v1 shim, see NOTES.md
    output_text = result.output.json(by_alias=True, exclude_none=True, indent=2)
    OUTPUT_PATH.write_text(output_text)

    print("\nMetric -> owning semantic_model:")
    manifest = json.loads(output_text)
    for metric in manifest["metrics"]:
        agg_params = metric["type_params"].get("metric_aggregation_params", {})
        print(f"  {metric['name']:16s} -> {agg_params.get('semantic_model')}  "
              f"({agg_params.get('agg')}({metric['type_params'].get('expr')}))")


if __name__ == "__main__":
    main()
