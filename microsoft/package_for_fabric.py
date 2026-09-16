"""Wrap microsoft/model/ (from export_semantic_model.py --tmdl-folder) into the folder
shape Fabric's git integration actually expects for a semantic model item.

TmdlSerializer.SerializeDatabaseToFolder only writes the *contents* of that item's
`definition/` folder - it has no notion of a Fabric item at all, so it can't produce the
two wrapper files (`.platform`, `definition.pbism`) or the `{name}.SemanticModel` item
directory Fabric's git-sync looks for. Those aren't part of the semantic model itself,
they're Fabric's own item bookkeeping, so this is glue code, not a converter fix.

Run `python microsoft/export_semantic_model.py --tmdl-folder` first, then this.

Result: microsoft/<name>.SemanticModel/{.platform,definition.pbism,definition/...}
A fresh logicalId is generated every run by default - fine for "does this look right",
but a real workspace's git history needs that id stable across commits, so pass
--logical-id on any run after the first to keep reusing the same one.
"""

import argparse
import json
import shutil
import uuid

import yaml

from common.env import REPO_ROOT

MODEL_INPUT = REPO_ROOT / "microsoft" / "model"
OSSIE_YAML = REPO_ROOT / "microsoft" / "ossie" / "orders_customers.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--logical-id",
        help="reuse an existing item's logicalId instead of generating a new one "
        "(needed to update rather than recreate an item already connected to a workspace)",
    )
    args = parser.parse_args()

    if not MODEL_INPUT.is_dir():
        raise SystemExit(
            f"{MODEL_INPUT.relative_to(REPO_ROOT)} not found - run "
            "`python microsoft/export_semantic_model.py --tmdl-folder` first"
        )

    semantic_model = yaml.safe_load(OSSIE_YAML.read_text())["semantic_model"][0]
    name = semantic_model["name"]
    description = semantic_model.get("description", "")

    item_dir = REPO_ROOT / "microsoft" / f"{name}.SemanticModel"
    if item_dir.exists():
        shutil.rmtree(item_dir)
    item_dir.mkdir(parents=True)

    shutil.copytree(MODEL_INPUT, item_dir / "definition")

    platform = {
        "version": "2.0",
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/platform/platformProperties.json",
        "config": {"logicalId": args.logical_id or str(uuid.uuid4())},
        "metadata": {
            "type": "SemanticModel",
            "displayName": name,
            "description": description,
        },
    }
    (item_dir / ".platform").write_text(json.dumps(platform, indent=2) + "\n")

    definition_pbism = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2",
        "settings": {},
    }
    (item_dir / "definition.pbism").write_text(json.dumps(definition_pbism, indent=2) + "\n")

    print(f"Wrote {item_dir.relative_to(REPO_ROOT)}/ (logicalId {platform['config']['logicalId']})")


if __name__ == "__main__":
    main()
