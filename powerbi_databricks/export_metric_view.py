"""Power BI semantic model (sample/) -> Databricks Metric Views, from TMSL or TMDL.

    uv run powerbi_databricks/export_metric_view.py [--from tmsl|tmdl] [--warnings]

Writes powerbi_databricks/metric_view_from_<tmsl|tmdl>_<dataset>.yaml (default: both), one Metric
View per table, without joins (the Python Databricks converter has none). Tables are prefixed
with the input format (tmsl_orders, tmdl_orders, ...) so both can be deployed side by side.
Power BI measures are DAX only and the Databricks converter needs SQL, and neither converter translates
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
from ossie_microsoft.semantic_model_to_ossie import convert_semantic_model_to_ossie
from ossie_microsoft.tom import _assembly_directory, _load_tom

from common.databricks_converter import ossie_to_metric_views
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


def strip_extensions(node) -> None:
    """Power BI details mean nothing to Databricks, and the pinned validator predates their new form."""
    if isinstance(node, dict):
        node.pop("nonportable_extensions", None)
        node = list(node.values())
    if isinstance(node, list):
        for item in node:
            strip_extensions(item)


def fix_up(ossie: dict, catalog: str, schema: str, way: str) -> None:
    """What the Databricks converter rejects in this model."""
    strip_extensions(ossie)
    for d in ossie["datasets"]:  # `dbo.orders` -> 3-part `catalog.schema.tmsl_orders`
        d["source"] = f"{catalog}.{schema}.{way}_{d['source'].rsplit('.', 1)[-1]}"


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
            views, messages = ossie_to_metric_views(yaml.safe_dump(ossie, sort_keys=False), catalog, schema)
        if args.warnings:
            print("\n".join(f"warning: {w.message}" for w in caught))
            print("\n".join(messages))
        dimensions = 0
        for dataset, view_yaml in views.items():
            (HERE / f"metric_view_from_{way}_{dataset}.yaml").write_text(view_yaml)
            dimensions += len(yaml.safe_load(view_yaml).get("dimensions", []))
        print(f"Wrote {len(views)} metric views for {way} (qualified for {catalog}.{schema}): "
              f"{dimensions} dimensions, {len(ossie['metrics'])} DAX-only metrics dropped")


if __name__ == "__main__":
    main()
