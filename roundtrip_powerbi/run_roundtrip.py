"""Ossie -> Power BI -> Ossie round trip, for the internal talk's Power BI demo.

Starts from roundtrip_powerbi/ossie/orders_customers.yaml (a copy of the
Microsoft model) and writes two files to roundtrip_powerbi/out/:

  1. ossie/orders_customers.yaml -> out/model.bim              (Ossie -> Power BI)
  2. out/model.bim               -> out/orders_customers.yaml  (Power BI -> Ossie)
     (--tmdl also writes out/model.bim as the TMDL folder out/tmdl/)

Then prints two diffs: the starting Ossie file vs the round-tripped one, and
model.bim vs the model.bim the round-tripped Ossie file converts to (kept in
memory only). Differences are expected on the Ossie side, so a mismatch is
reported, not treated as an error. run_fabric_roundtrip.py does the same
through a real Fabric workspace.

Replaces the `__catalog__.__schema__` source placeholder the same way
microsoft/export_semantic_model.py does. --tmdl needs the `tom` extra and its
assemblies, see that script. Pass --warnings to see what each converter drops.
"""

import argparse
import difflib
import json
import os
import shutil
import warnings

from ossie_microsoft import convert_ossie_to_semantic_model, convert_semantic_model_to_ossie

from common.env import REPO_ROOT, load_env_file

ROUNDTRIP_DIR = REPO_ROOT / "roundtrip_powerbi"
INPUT = ROUNDTRIP_DIR / "ossie" / "orders_customers.yaml"
OUT = ROUNDTRIP_DIR / "out"
TMDL_DIR = OUT / "tmdl"
PLACEHOLDER = "__catalog__.__schema__"


def show_diff(a: str, b: str, a_name: str, b_name: str) -> None:
    if a == b:
        print(f"  identical: {a_name} == {b_name}")
        return
    diff = "".join(difflib.unified_diff(
        a.splitlines(keepends=True), b.splitlines(keepends=True), a_name, b_name
    ))
    print(diff)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warnings", action="store_true", help="show conversion warnings (hidden by default)"
    )
    parser.add_argument(
        "--tmdl", action="store_true", help="also write the split-per-table TMDL folder (needs TOM)"
    )
    args = parser.parse_args()

    load_env_file()
    lakehouse = os.environ.get("FABRIC_LAKEHOUSE", "ossie")
    schema = os.environ.get("FABRIC_SCHEMA", "dbo")
    original_ossie = INPUT.read_text().replace(PLACEHOLDER, f"{lakehouse}.{schema}")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    with warnings.catch_warnings():
        if not args.warnings:
            warnings.simplefilter("ignore")

        print("Step 1: Ossie -> Power BI (out/model.bim)")
        bim = convert_ossie_to_semantic_model(original_ossie)
        bim_text = json.dumps(bim, indent=2)
        (OUT / "model.bim").write_text(bim_text)

        if args.tmdl:
            from ossie_microsoft.tom import _assembly_directory, _load_tom

            print("  --tmdl: model.bim -> TMDL folder (out/tmdl/)")
            tom = _load_tom(_assembly_directory(None))
            database = tom.JsonSerializer.DeserializeDatabase(bim_text)
            tom.TmdlSerializer.SerializeDatabaseToFolder(database, str(TMDL_DIR))

        print("Step 2: Power BI -> Ossie (out/orders_customers.yaml)")
        roundtripped_ossie = convert_semantic_model_to_ossie(bim)
        (OUT / "orders_customers.yaml").write_text(roundtripped_ossie)

        bim_again_text = json.dumps(convert_ossie_to_semantic_model(roundtripped_ossie), indent=2)

    print("\nOssie side: start vs round-tripped")
    show_diff(original_ossie, roundtripped_ossie, "ossie/orders_customers.yaml", "out/orders_customers.yaml")

    print("\nPower BI side: model.bim vs converting the round-tripped Ossie file again")
    if json.loads(bim_text) == json.loads(bim_again_text):
        print("  same content (only JSON key order differs)")
    else:
        show_diff(bim_text, bim_again_text, "out/model.bim", "model.bim (again)")


if __name__ == "__main__":
    main()
