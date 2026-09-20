"""Power BI semantic model (sample/) -> Databricks Metric View, from TMSL or TMDL.

    uv run powerbi_databricks/export_metric_view.py [--from tmsl|tmdl] [--warnings]

Writes powerbi_databricks/metric_view_from_<tmsl|tmdl>.yaml (default: both). Tables are prefixed
with the input format (tmsl_orders, tmdl_orders, ...) so both can be deployed side by side.
Power BI measures are DAX only and ossie-databricks needs SQL, and neither converter translates
one into the other, so the measures are left out: dimensions only.

ossie-microsoft can't read a TMDL folder, so that way goes through Microsoft's TOM (`tom` extra,
assemblies in .tom/assemblies) and two private helpers of ossie_microsoft.tom.
"""

import argparse
import json
import logging
import os
import warnings

import yaml
from ossie_databricks.ossie_to_metric_view import convert_ossie_to_metric_view
from ossie_microsoft.semantic_model_to_ossie import convert_semantic_model_to_ossie
from ossie_microsoft.tom import _assembly_directory, _load_tom

from common.env import REPO_ROOT, load_env_file

HERE = REPO_ROOT / "powerbi_databricks"

# every ossie_microsoft warning is also logged; don't let the logging fallback print it twice
logging.getLogger("ossie_microsoft").addHandler(logging.NullHandler())


def read_tmsl() -> dict:
    return json.loads((HERE / "sample/TMSL/model.bim").read_text(encoding="utf-8-sig"))


def read_tmdl() -> dict:
    tom = _load_tom(_assembly_directory(REPO_ROOT / ".tom" / "assemblies"))
    db = tom.TmdlSerializer.DeserializeDatabaseFromFolder(str(HERE / "sample/TMDL/definition"))
    return json.loads(str(tom.JsonSerializer.SerializeDatabase(db)))


def fix_up(ossie: dict, catalog: str, schema: str, way: str) -> None:
    """Two things ossie-databricks rejects in this model."""
    datasets = {d["name"]: d for d in ossie["datasets"]}
    for d in datasets.values():  # `dbo.orders` -> 3-part `catalog.schema.tmsl_orders`
        d["source"] = f"{catalog}.{schema}.{way}_{d['source'].rsplit('.', 1)[-1]}"
    for r in ossie["relationships"]:  # dimension names are global: drop the `to` copy of a join key
        clash = {f["name"] for f in datasets[r["from"]]["fields"]} & set(r["to_columns"])
        datasets[r["to"]]["fields"] = [f for f in datasets[r["to"]]["fields"] if f["name"] not in clash]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="way", choices=("tmsl", "tmdl"), help="default: both")
    parser.add_argument("--warnings", action="store_true", help="show conversion warnings")
    args = parser.parse_args()

    load_env_file()
    catalog = os.environ.get("DATABRICKS_CATALOG", "ossi")
    schema = os.environ.get("DATABRICKS_SCHEMA", "test")
    readers = {"tmsl": read_tmsl, "tmdl": read_tmdl}

    for way in [args.way] if args.way else readers:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ossie = yaml.safe_load(convert_semantic_model_to_ossie(readers[way]()))
            fix_up(ossie, catalog, schema, way)
            view_yaml = convert_ossie_to_metric_view(yaml.safe_dump(ossie, sort_keys=False))
        if args.warnings:
            print("\n".join(f"warning: {w.message}" for w in caught))
        output = HERE / f"metric_view_from_{way}.yaml"
        output.write_text(view_yaml)
        view = yaml.safe_load(view_yaml)
        measures = len(view.get("measures", []))
        print(f"Wrote {output.relative_to(REPO_ROOT)} (qualified for {catalog}.{schema}): "
              f"{len(view['dimensions'])} dimensions, {measures} measures, "
              f"{len(ossie['metrics']) - measures} DAX-only metrics dropped")


if __name__ == "__main__":
    main()
