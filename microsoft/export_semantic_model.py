"""Convert microsoft/ossie/orders_customers.yaml to model.bim, model.tmdl, or a TMDL folder.

Replaces the model's `__catalog__.__schema__` source placeholder with
FABRIC_LAKEHOUSE/FABRIC_SCHEMA from .env before conversion - see NOTES.md.
Pass --warnings to see what didn't survive the conversion.

--tmdl and --tmdl-folder both require the `tom` extra (Microsoft's .NET TOM library via
pythonnet) and its assemblies restored to .tom/assemblies - see
converters/microsoft/scripts/restore_tom.py in the apache/ossie repo.

--tmdl-folder calls Microsoft.AnalysisServices.Tabular.TmdlSerializer.SerializeDatabaseToFolder
directly (via ossie_microsoft.tom's private _load_tom/_assembly_directory helpers - not part of
that package's public API) to get the real split-per-table TMDL layout, since
ossie_microsoft.tom.serialize_tmdl only exposes the single-file form. This still omits the
.platform and definition.pbism files a Fabric git-synced workspace item needs - those are
Fabric item metadata, not part of the semantic model itself.
"""

import argparse
import json
import os
import shutil
import warnings

from ossie_microsoft.ossie_to_semantic_model import convert_ossie_to_semantic_model
from ossie_microsoft.tom import _assembly_directory, _load_tom

from common.env import REPO_ROOT, load_env_file

INPUT = REPO_ROOT / "microsoft" / "ossie" / "orders_customers.yaml"
PLACEHOLDER = "__catalog__.__schema__"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warnings", action="store_true", help="show conversion warnings (hidden by default)"
    )
    parser.add_argument(
        "--tmdl", action="store_true", help="write model.tmdl (single file) instead of model.bim"
    )
    parser.add_argument(
        "--tmdl-folder",
        action="store_true",
        help="write model/ as the real split-per-table TMDL folder instead of model.bim",
    )
    args = parser.parse_args()

    load_env_file()
    lakehouse = os.environ.get("FABRIC_LAKEHOUSE", "ossie")
    schema = os.environ.get("FABRIC_SCHEMA", "dbo")
    ossie_yaml = INPUT.read_text().replace(PLACEHOLDER, f"{lakehouse}.{schema}")

    with warnings.catch_warnings():
        if not args.warnings:
            warnings.simplefilter("ignore")
        bim = convert_ossie_to_semantic_model(ossie_yaml)  # TMSL, always - the other formats build on it

        if args.tmdl_folder:
            output = REPO_ROOT / "microsoft" / "model"
            if output.exists():
                shutil.rmtree(output)
            tom = _load_tom(_assembly_directory(None))
            database = tom.JsonSerializer.DeserializeDatabase(json.dumps(bim))
            tom.TmdlSerializer.SerializeDatabaseToFolder(database, str(output))
        elif args.tmdl:
            output = REPO_ROOT / "microsoft" / "model.tmdl"
            tom = _load_tom(_assembly_directory(None))
            database = tom.JsonSerializer.DeserializeDatabase(json.dumps(bim))
            output.write_text(str(tom.TmdlSerializer.SerializeDatabase(database)))
        else:
            output = REPO_ROOT / "microsoft" / "model.bim"
            output.write_text(json.dumps(bim, indent=2))
    print(f"Wrote {output.relative_to(REPO_ROOT)} (qualified for {lakehouse}.{schema})")


if __name__ == "__main__":
    main()
