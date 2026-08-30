"""Convert dbt/ossie/orders_customers.yaml with apache-ossie-dbt's own
converter (converters/dbt/src/ossie_dbt/ossie_to_msi.py in the apache/ossie
repo, at the commit pinned in the root uv.lock) - the standalone converter
package, not dbt-core's vendored native OSI loader (dbt-core rejects this
file's version 0.2.0.dev0 outright and silently finds zero metrics itself).

Run: uv run scripts/export_metric_view.py
"""

import json
from pathlib import Path

import yaml
from ossie import OssieDocument
from ossie_dbt.ossie_to_msi import OssieToMSIConverter

REPO_ROOT = Path(__file__).parent.parent.parent
INPUT_PATH = REPO_ROOT / "dbt" / "ossie" / "orders_customers.yaml"
# target/semantic_manifest.json, not a bare file in dbt/ - `mf query` looks
# for it there, same as dbt-core's own compiled manifest would be. Run
# `dbt run` first so target/ and the real tables exist, then this script
# overwrites dbt's own compiled manifest with the one from
# apache-ossie-dbt's converter instead.
OUTPUT_PATH = REPO_ROOT / "dbt" / "target" / "semantic_manifest.json"


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
    # NOT result.output.model_dump_json(...) - that's what the package's own
    # CLI (ossie-dbt ossie-to-msi) calls, and it crashes: PydanticSemanticManifest
    # inherits from a Pydantic v1 shim (msi_pydantic_shim), so only .json()/.dict()
    # exist, not the Pydantic v2-only .model_dump_json().
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
