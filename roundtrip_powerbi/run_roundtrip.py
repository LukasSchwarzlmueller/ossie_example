"""Ossie -> Power BI -> Ossie round trip, for the internal talk's Power BI demo.

Starts from roundtrip_powerbi/ossie/orders_customers.yaml (a copy of the
Microsoft model) and writes every intermediate file to roundtrip_powerbi/out/,
so each step can be opened live:

  1. ossie/orders_customers.yaml          -> out/tmsl/model.bim        (Ossie -> Power BI)
  2. out/tmsl/model.bim                   -> out/tmdl/                 (TMDL folder, --tmdl only)
  3. out/tmsl/model.bim                   -> out/ossie_back/orders_customers.yaml  (Power BI -> Ossie)
  4. out/ossie_back/orders_customers.yaml -> out/tmsl/model_again.bim  (Ossie -> Power BI again)

Then prints two diffs: the starting Ossie file vs the round-tripped one, and
the two model.bim files. Differences are expected on the Ossie side, so a
mismatch is reported, not treated as an error.

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
TMSL_DIR = OUT / "tmsl"
TMDL_DIR = OUT / "tmdl"
OSSIE_BACK_DIR = OUT / "ossie_back"
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
    for folder in (TMSL_DIR, OSSIE_BACK_DIR):
        folder.mkdir(parents=True)

    with warnings.catch_warnings():
        if not args.warnings:
            warnings.simplefilter("ignore")

        print("Step 1: Ossie -> Power BI (out/tmsl/model.bim)")
        bim = convert_ossie_to_semantic_model(original_ossie)
        bim_text = json.dumps(bim, indent=2)
        (TMSL_DIR / "model.bim").write_text(bim_text)

        if args.tmdl:
            from ossie_microsoft.tom import _assembly_directory, _load_tom

            print("Step 2: model.bim -> TMDL folder (out/tmdl/)")
            tom = _load_tom(_assembly_directory(None))
            database = tom.JsonSerializer.DeserializeDatabase(bim_text)
            tom.TmdlSerializer.SerializeDatabaseToFolder(database, str(TMDL_DIR))
        else:
            print("Step 2: skipped (pass --tmdl for the TMDL folder)")

        print("Step 3: Power BI -> Ossie (out/ossie_back/orders_customers.yaml)")
        roundtripped_ossie = convert_semantic_model_to_ossie(bim)
        (OSSIE_BACK_DIR / "orders_customers.yaml").write_text(roundtripped_ossie)

        print("Step 4: Ossie -> Power BI again (out/tmsl/model_again.bim)")
        bim_again_text = json.dumps(convert_ossie_to_semantic_model(roundtripped_ossie), indent=2)
        (TMSL_DIR / "model_again.bim").write_text(bim_again_text)

    print("\nOssie side: start vs round-tripped")
    show_diff(original_ossie, roundtripped_ossie, "ossie/orders_customers.yaml", "out/ossie_back/orders_customers.yaml")

    print("\nPower BI side: first vs second model.bim")
    if json.loads(bim_text) == json.loads(bim_again_text):
        print("  same content: out/tmsl/model.bim == out/tmsl/model_again.bim (only JSON key order differs)")
    else:
        show_diff(bim_text, bim_again_text, "out/tmsl/model.bim", "out/tmsl/model_again.bim")


if __name__ == "__main__":
    main()
