"""The whole trip: Databricks Metric View -> Ossie -> Power BI (-> Fabric), red/green per object.

  0. pull the Metric View definition from Databricks (SHOW CREATE TABLE) -> output/metric_view.yaml
  1. Metric View -> output/ossie.yaml               Java Databricks converter (import)
  2. "mirroring": dataset sources Unity Catalog -> OneLake lakehouse (only the names change)
  3. fixes in Ossie -> output/ossie_fixed.yaml       see FIXES below
  4. both Ossie files -> Power BI                    output/model_raw.bim, output/model.bim
  5. Fabric glue + upload of model.bim to Fabric (code from roundtrip_powerbi/), then a refresh
     so the Direct Lake model has data

--dry-run needs no account: step 0 reads the local metric_view.yaml instead, step 5 writes
output/model_fabric.bim (what would be uploaded) and sends nothing.

The summary shows, per measure, column and relationship, what arrives as is (green), what is
lost (red) or arrives with a wrong value (yellow), and below it what the fix in Ossie gets back.

FIXES - everything happens in the Ossie file, the converters stay as they are:
  - relationship keys: the Databricks import writes the physical column (customer_id) into the
    relationship, but the field is named customer_key -> point the relationship at the field
  - DAX from fixes.yaml as a second dialect for measures that don't translate from SQL
  - Databricks `format` (kept in custom_extensions) -> Power BI formatString
  - column types from fixes.yaml: a Metric View has none, and Fabric refuses the model without

    uv run databricks_to_powerbi/run_trip.py               # real: from Databricks, into Fabric
    uv run databricks_to_powerbi/run_trip.py --no-upload   # real Databricks, stop before Fabric
    uv run databricks_to_powerbi/run_trip.py --dry-run     # offline: local file, nothing sent
    uv run databricks_to_powerbi/run_trip.py --raw         # only the "as is" result, no fixes
    uv run databricks_to_powerbi/run_trip.py --step        # live: Enter before each summary line
    uv run databricks_to_powerbi/run_trip.py --details     # summary with SQL, DAX and reasons

Real runs need DATABRICKS_HOST / DATABRICKS_TOKEN / DATABRICKS_WAREHOUSE_ID (setup_databricks.py
deployed the view) and FABRIC_WORKSPACE_ID / FABRIC_LAKEHOUSE_ID plus an az login.
"""

import argparse
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import textwrap
import sys
import warnings

import yaml

from ossie_microsoft import convert_ossie_to_semantic_model

from common.env import REPO_ROOT, load_env_file

HERE = REPO_ROOT / "databricks_to_powerbi"
OUT = HERE / "output"
PLACEHOLDER = "__catalog__.__schema__"
JAR_DIRS = [  # where the converter jar has lived over time
    REPO_ROOT / ".ossie" / "converters" / "databricks" / "java" / "target",
    REPO_ROOT / ".ossie-converters" / "databricks" / "java" / "target",
]
CURRENCY = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF "}
POWERBI = "https://analysis.windows.net/powerbi/api"


def load_roundtrip():
    """Reuse Fabric upload, token and glue from roundtrip_powerbi/run_fabric_roundtrip.py."""
    path = REPO_ROOT / "roundtrip_powerbi" / "run_fabric_roundtrip.py"
    spec = importlib.util.spec_from_file_location("run_fabric_roundtrip", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # also silences the ossie_microsoft logger
    return module


def pull_metric_view(qualified_view: str) -> str:
    """The Metric View's YAML as Databricks stores it, from SHOW CREATE TABLE."""
    from databricks.sdk import WorkspaceClient  # only needed for a real run

    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not warehouse_id:
        raise SystemExit("DATABRICKS_WAREHOUSE_ID not set - is it in .env? (or use --dry-run)")
    result = WorkspaceClient().statement_execution.execute_statement(
        statement=f"SHOW CREATE TABLE {qualified_view}", warehouse_id=warehouse_id, wait_timeout="30s"
    )
    if result.status and result.status.error:
        error = result.status.error
        raise SystemExit(f"Could not read {qualified_view} ({error.error_code}): {error.message}\n"
                         "Run setup_databricks.py first, or use --dry-run.")
    ddl = result.result.data_array[0][0]
    found = re.search(r"\$\$(.*)\$\$", ddl, re.DOTALL)
    if not found:
        raise SystemExit(f"No YAML body found in the definition of {qualified_view}:\n{ddl}")
    return textwrap.dedent(found.group(1)).strip() + "\n"


def refresh(token: str, workspace_id: str, model_id: str) -> str:
    """Refresh (frame) the Direct Lake model: until then its tables have no data in Fabric."""
    import time
    import urllib.error
    import urllib.request

    url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{model_id}/refreshes"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=b'{"type": "full"}', headers=headers, method="POST"))
        for _ in range(60):
            time.sleep(3)
            latest = json.load(urllib.request.urlopen(urllib.request.Request(f"{url}?$top=1", headers=headers)))
            status = latest["value"][0]["status"]
            if status != "Unknown":  # Unknown = still running
                return status if status == "Completed" else f"{status}: {latest['value'][0].get('serviceExceptionJson', '')}"
        return "still running after 3 min"
    except urllib.error.HTTPError as e:
        return f"failed ({e.code}): {e.read().decode()[:300]}"


def find_jar() -> str:
    if jar := os.environ.get("OSSIE_DATABRICKS_JAR"):
        return jar
    for folder in JAR_DIRS:
        jars = [j for j in sorted(folder.glob("ossie-databricks-converter-*.jar"))
                if not j.name.endswith(("-sources.jar", "-javadoc.jar"))]
        if jars:
            return str(jars[0])
    raise SystemExit("Databricks converter jar not found - run databricks/build_converter.sh")


# --- Ossie helpers ---------------------------------------------------------------------------

def dialects(obj: dict) -> list[dict]:
    return obj["expression"]["dialects"]


def stash(obj: dict, vendor: str) -> dict:
    for ext in obj.get("custom_extensions", []):
        if ext.get("vendor_name") == vendor:
            return json.loads(ext["data"])
    return {}


def set_stash(obj: dict, vendor: str, data: dict) -> None:
    exts = [e for e in obj.get("custom_extensions", []) if e.get("vendor_name") != vendor]
    exts.append({"vendor_name": vendor, "data": json.dumps(data)})
    obj["custom_extensions"] = exts


def plain_column(field: dict) -> str | None:
    expr = dialects(field)[0]["expression"].strip()
    return expr if re.fullmatch(r"\w+", expr) else None


def format_string(spec: dict) -> str | None:
    """Databricks Metric View `format` -> Power BI formatString."""
    kind = spec.get("type")
    if kind == "currency":
        return f"{CURRENCY.get(spec.get('currency_code', ''), '')}#,0.00"
    if kind == "percentage":
        return "0.0%"
    if kind == "number":
        return "#,0.##"
    return None


# --- fixes (all in the Ossie file) -----------------------------------------------------------

def apply_fixes(ossie: dict, dax: dict[str, str], types: dict[str, str]) -> dict[str, str]:
    """Fix the Ossie model in place; returns {object: what was fixed} for the summary."""
    notes: dict[str, str] = {}
    datasets = {d["name"]: d for d in ossie["datasets"]}

    def to_field(dataset: str, column: str) -> str:
        fields = datasets[dataset].get("fields", [])
        if any(f["name"] == column for f in fields):
            return column
        return next((f["name"] for f in fields if plain_column(f) == column), column)

    for rel in ossie.get("relationships", []):
        before = (list(rel["from_columns"]), list(rel["to_columns"]))
        rel["from_columns"] = [to_field(rel["from"], c) for c in rel["from_columns"]]
        rel["to_columns"] = [to_field(rel["to"], c) for c in rel["to_columns"]]
        changed = [f"{rel[side]}.{a} -> {b}" for side, cols, old in
                   (("from", rel["from_columns"], before[0]), ("to", rel["to_columns"], before[1]))
                   for a, b in zip(old, cols) if a != b]
        if changed:
            notes[f"relationship {rel['from']} -> {rel['to']}"] = "key points to the field: " + ", ".join(changed)
    for dataset in ossie["datasets"]:
        if "unique_keys" in dataset:
            dataset["unique_keys"] = [[to_field(dataset["name"], c) for c in key] for key in dataset["unique_keys"]]

    for metric in ossie.get("metrics", []):
        if metric["name"] in dax:
            dialects(metric).append({"dialect": "DAX", "expression": dax[metric["name"]].strip()})
            notes[metric["name"]] = "DAX added in Ossie"

    formats = 0
    for obj in [f for d in ossie["datasets"] for f in d.get("fields", [])] + ossie.get("metrics", []):
        if (spec := stash(obj, "DATABRICKS").get("format")) and (fs := format_string(spec)):
            set_stash(obj, "POWER_BI", {**stash(obj, "POWER_BI"), "formatString": fs})
            formats += 1
    if formats:
        notes["formats"] = f"Databricks format -> Power BI formatString ({formats}x)"

    typed = 0
    for field in [f for d in ossie["datasets"] for f in d.get("fields", [])]:
        if not field.get("datatype") and field["name"] in types:
            field["datatype"] = types[field["name"]]
            typed += 1
    if typed:
        notes["types"] = f"datatype set in Ossie ({typed}x)"
    return notes


# --- conversion ------------------------------------------------------------------------------

def to_powerbi(ossie: dict, source: dict | None) -> tuple[dict, list[str]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bim = convert_ossie_to_semantic_model(yaml.safe_dump(ossie, sort_keys=False), source=source)
    bim["name"] = os.environ.get("FABRIC_TRIP_MODEL_NAME", "ossie_databricks_trip")
    return bim, [str(w.message) for w in caught]


class Result:
    """What one Power BI model says about each object."""

    def __init__(self, ossie: dict, bim: dict, messages: list[str]):
        self.ossie, self.messages = ossie, messages
        tables = bim["model"]["tables"]
        self.measures = {m["name"]: m for t in tables for m in t.get("measures", [])}
        self.columns = {(t["name"], c["name"]): c for t in tables for c in t.get("columns", [])}
        self.relationships = {(r["fromTable"], r["toTable"]) for r in bim["model"].get("relationships", [])}
        self.metrics = {m["name"]: m for m in ossie.get("metrics", [])}

    def reason(self, key: str, word: str) -> str:
        for m in self.messages:
            if m.startswith(f"[{key}]") and word in m:
                if found := re.search(r"could not be translated to DAX \((.*?)\), and", m):
                    return found.group(1)
                return m.split("]", 1)[-1].split(";")[0].strip()
        return ""

    def measure(self, name: str) -> tuple[str, str, str]:
        """(state, DAX, why) with state ok / lost / wrong."""
        dax = self.measures.get(name, {}).get("expression")
        if dax is None:
            return "lost", "missing", ""
        if "BLANK()" in dax:
            return "lost", "BLANK()", self.reason(f"metric '{name}'", "translated")
        has_dax = any(d["dialect"] == "DAX" for d in dialects(self.metrics[name]))
        window = stash(self.metrics[name], "DATABRICKS").get("window")
        if window and not has_dax:
            return "wrong", dax, "window dropped: plain SUM, wrong number, no warning"
        return "ok", dax, ""

    def column(self, dataset: str, field: str) -> tuple[str, str]:
        column = self.columns.get((dataset, field))
        if column is None:
            return "lost", "missing"
        if column.get("type") == "calculated" and "BLANK()" in str(column.get("expression")):
            return "lost", self.reason(f"dataset '{dataset}' field '{field}'", "translated")
        return "ok", ""

    def relationship(self, rel: dict) -> tuple[str, str]:
        if (rel["from"], rel["to"]) in self.relationships:
            return "ok", ""
        return "lost", self.reason(f"relationship '{rel['name']}'", "skipped")

    def described(self) -> int:
        return sum(1 for o in [*self.measures.values(), *self.columns.values()] if o.get("description"))

    def typed(self) -> int:
        return sum(1 for c in self.columns.values() if c.get("dataType"))

    def formats(self) -> int:
        return sum(1 for m in self.measures.values() if m.get("formatString")) + \
            sum(1 for c in self.columns.values() if c.get("formatString"))


# --- output ----------------------------------------------------------------------------------

COLOR = sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))
MARK = {"ok": ("32", "✓"), "lost": ("31", "✕"), "wrong": ("33", "⚠")}


def paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def clip(text: str, width: int = 34) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def line(state: str, name: str, detail: str = "", why: str = "") -> None:
    code, mark = MARK[state]
    detail = detail if state == "ok" else paint(code, detail)
    print(f"    {paint(code, f'{mark} {name:<24}')}{detail}" + (f"  {paint('2', clip(why, 56))}" if why else ""))


def fixed(detail: str, why: str) -> None:
    print(f"      {paint('32', '↳ fixed')}{' ' * 17}{paint('32', detail)}  {paint('2', why)}")


STEP = False  # --step: wait for Enter before each line


def pause() -> None:
    """With --step: wait for Enter, then remove the prompt line so the output stays clean."""
    if STEP:
        input(paint("2", "  ⏎"))
        sys.stdout.write("\033[1A\033[2K")


def kind(measure: dict) -> str:
    """What kind of measure this is, in plain words."""
    expr = " ".join(measure["expr"].split()).upper()
    if measure.get("window"):
        return "time logic"
    if "FILTER" in expr:
        return "business logic"
    if "MEASURE(" in expr:
        return "composed"
    if re.fullmatch(r"COUNT\(\s*\*\s*\)", expr):
        return "count rows"
    if found := re.fullmatch(r"(SUM|AVG|MIN|MAX|COUNT)\((DISTINCT )?\w+(\.\w+)?\)", expr):
        names = {"SUM": "sum", "AVG": "average", "MIN": "minimum", "MAX": "maximum", "COUNT": "count"}
        return "simple " + ("distinct count" if found.group(2) else names[found.group(1)])
    return "expression"


OUTCOME = {
    "ok": "arrives",
    "lost": "arrives empty",
    "wrong": "wrong number, no warning",
}


def plain(state: str, name: str, what: str, outcome: str, explain: str = "") -> None:
    pause()
    code, mark = MARK[state]
    print(f"    {paint(code, f'{mark} {name:<24}')}{what:<17}{paint(code, outcome) if state != 'ok' else outcome}")
    if explain:
        print(paint("2", f"      {explain}"))


def explain_measure(m: dict, state: str, dax: str) -> str:
    """One short line on what happened to this measure."""
    sql = " ".join(m["expr"].split())
    if state == "ok":
        return f"{sql}  ->  {dax}"
    what = kind(m)
    if state == "wrong":
        windows = m.get("window") or []
        order = windows[0].get("order") if windows else "?"
        return f"the window (cumulative by {order}) is dropped, a plain {sql} is left"
    if what == "count rows":
        return "COUNT(*) names no table to count -> BLANK()"
    if what == "business logic":
        return "FILTER (WHERE ...) has no DAX translation -> BLANK()"
    if what == "composed":
        return "MEASURE() references aren't translated -> BLANK()"
    return "no DAX translation -> BLANK()"


def key_mismatch(rel: dict, ossie: dict) -> tuple[str, str] | None:
    """(column the relationship names, field it should name) when the key was renamed."""
    datasets = {d["name"]: d.get("fields", []) for d in ossie["datasets"]}
    for side, cols in (("from", rel["from_columns"]), ("to", rel["to_columns"])):
        fields = datasets[rel[side]]
        for col in cols:
            if not any(f["name"] == col for f in fields):
                renamed = next((f["name"] for f in fields if plain_column(f) == col), None)
                return col, renamed or "?"
    return None


def plain_summary(view: dict, raw: "Result", fix: "Result", raw_ossie: dict, show_fix: bool) -> None:
    """The talk version: what arrives, then what was fixed by hand. --details has the rest."""
    measures = view.get("measures", [])
    rels = raw_ossie.get("relationships", [])
    n_columns = sum(len(d.get("fields", [])) for d in raw_ossie["datasets"])
    broken_rels = [r for r in rels if raw.relationship(r)[0] != "ok"]
    untyped = raw.typed() < n_columns

    pause()
    print(paint("1", "\n  What arrives in Power BI?"))
    correct = 0
    for m in measures:
        state, dax, _ = raw.measure(m["name"])
        correct += state == "ok"
        plain(state, m["name"], kind(m), OUTCOME[state], explain_measure(m, state, dax))

    problems, why = [], []
    if untyped:
        problems.append("no column types")
        why.append("Metric View has no types, Fabric refuses the model")
    if broken_rels:
        problems.append("tables not connected")
        if found := key_mismatch(broken_rels[0], raw_ossie):
            why.append(f"relationship says {found[0]}, field is {found[1]}")
    if problems:
        plain("lost", "model", "", ", ".join(problems), " · ".join(why))

    pause()
    print(f"\n  Converter: {paint('32', 'success')}"
          + paint("1", f"  → {correct} of {len(measures)} measures correct"))

    if not show_fix:
        return
    pause()
    print(paint("1", "\n  Fixed in the Ossie file") + paint("2", "  (converters unchanged)"))
    if broken_rels:
        print(paint("2", "    universal fix: the same code works for any Metric View"))
        found = key_mismatch(broken_rels[0], raw_ossie)
        ok = all(fix.relationship(r)[0] == "ok" for r in broken_rels)
        plain("ok" if ok else "lost", "relationship", "",
              (f"points at {found[1]}" if found else "fixed") if ok else "still broken")
    print(paint("2", "    added for this model: fixes.yaml, written by hand"))
    fixed_ok = 0
    for m in measures:
        if raw.measure(m["name"])[0] == "ok":
            fixed_ok += 1
            continue
        state = fix.measure(m["name"])[0]
        fixed_ok += state == "ok"
        plain(state, m["name"], "", "DAX added next to the SQL" if state == "ok" else "still wrong")
    if untyped:
        ok = fix.typed() >= n_columns
        plain("ok" if ok else "lost", "column types", "", f"datatype for {n_columns} columns" if ok else "still missing")
    pause()
    print(paint("1", f"  → {fixed_ok} of {len(measures)} correct in Fabric."))


# --- the trip --------------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", action="store_true", help="no fixes: only what arrives as is")
    parser.add_argument("--dry-run", action="store_true",
                        help="no Databricks, no Fabric: local metric_view.yaml, write what would be uploaded")
    parser.add_argument("--no-upload", action="store_true", help="real Databricks pull, but skip Fabric")
    parser.add_argument("--warnings", action="store_true", help="print the converter warnings in full")
    parser.add_argument("--details", action="store_true", help="summary with SQL, DAX and the reasons")
    parser.add_argument("--step", action="store_true", help="wait for Enter before each summary line")
    args = parser.parse_args()
    global STEP
    STEP = args.step and sys.stdin.isatty()

    load_env_file()
    catalog = os.environ.get("DATABRICKS_CATALOG", "ossi")
    schema = os.environ.get("DATABRICKS_SCHEMA", "test")
    lakehouse = os.environ.get("FABRIC_LAKEHOUSE", "ossie")
    lake_schema = os.environ.get("FABRIC_SCHEMA", "dbo")
    uc, onelake = f"{catalog}.{schema}", f"{lakehouse}.{lake_schema}"
    workspace_id = os.environ.get("FABRIC_WORKSPACE_ID")
    lakehouse_id = os.environ.get("FABRIC_LAKEHOUSE_ID")
    source = {"workspaceId": workspace_id, "itemId": lakehouse_id} if workspace_id and lakehouse_id else None

    roundtrip = load_roundtrip()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    print(paint("1", "Databricks metric view  ->  Ossie  ->  Power BI semantic model\n"))

    # 0. The Metric View: from Databricks, or the local file in a dry run
    if args.dry_run:
        print("  ① Read the metric view                 metric_view.yaml " + paint("2", "(dry run, no Databricks)"))
        view_yaml = (HERE / "metric_view.yaml").read_text().replace(PLACEHOLDER, uc)
    else:
        view_name = f"{uc}.{os.environ.get('DATABRICKS_TRIP_VIEW_NAME', 'sales_demo_trip')}"
        print(f"  ① Read the metric view from Databricks {view_name}")
        view_yaml = pull_metric_view(view_name)

    # 1. Databricks -> Ossie
    view = yaml.safe_load(view_yaml)
    (OUT / "metric_view.yaml").write_text(view_yaml)
    joins = len(view.get("joins", []))
    print(paint("2", f"     {len(view.get('measures', []))} measures · {len(view.get('dimensions', []))} columns · "
                     f"{joins} join{'s' if joins != 1 else ''}"))
    print("  ② Databricks -> Ossie                  " + paint("2", "Databricks converter"))
    result = subprocess.run(
        ["java", "-jar", find_jar(), "import", str(OUT / "metric_view.yaml"), "-o", str(OUT / "ossie.yaml")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"Databricks import failed:\n{result.stdout}{result.stderr}")

    # 2. "Mirroring": same tables, now read from OneLake
    ossie_text = (OUT / "ossie.yaml").read_text().replace(f'"{uc}.', f'"{onelake}.')
    (OUT / "ossie.yaml").write_text(ossie_text)
    raw_ossie = yaml.safe_load(ossie_text)

    # 3. Fixes in Ossie
    fixed_ossie = copy.deepcopy(raw_ossie)
    notes = {}
    if not args.raw:
        fixes = yaml.safe_load((HERE / "fixes.yaml").read_text())
        notes = apply_fixes(fixed_ossie, fixes["metrics"], fixes.get("datatypes", {}))
        (OUT / "ossie_fixed.yaml").write_text(yaml.safe_dump(fixed_ossie, sort_keys=False, allow_unicode=True))

    # 4. Ossie -> Power BI, as is and fixed
    print("  ③ Ossie -> Power BI                    " + paint("2", "Microsoft converter"))
    print(paint("2", f"     tables read from OneLake ({onelake}), e.g. via mirroring"))
    raw_bim, raw_messages = to_powerbi(raw_ossie, source)
    bim, messages = (raw_bim, raw_messages) if args.raw else to_powerbi(fixed_ossie, source)
    if not args.raw:
        (OUT / "model_raw.bim").write_text(json.dumps(raw_bim, indent=2))
    (OUT / "model.bim").write_text(json.dumps(bim, indent=2))

    # 5. Fabric
    if args.dry_run:
        print("  ④ Upload to Fabric                     " + paint("2", "dry run, nothing sent"))
        upload = copy.deepcopy(bim)
        roundtrip.fabric_glue(upload)
        (OUT / "model_fabric.bim").write_text(json.dumps(upload, indent=2))
        target = workspace_id or "<FABRIC_WORKSPACE_ID not set>"
        ids = "real workspace/lakehouse ids" if source else "placeholder ids (FABRIC_* not in .env)"
        print(paint("2", f"     would upload '{upload['name']}' to workspace {target}, {ids}"))
    elif not args.no_upload:
        if not source:
            raise SystemExit("Fabric upload needs FABRIC_WORKSPACE_ID and FABRIC_LAKEHOUSE_ID in .env "
                             "(or use --no-upload / --dry-run)")
        print("  ④ Upload to Fabric")
        roundtrip.fabric_glue(bim)
        fabric = roundtrip.Fabric(roundtrip.get_token(), workspace_id)
        model_id, action = fabric.upload(bim, os.environ.get("FABRIC_FOLDER_ID"))
        print(f"     {action} '{bim['name']}': https://app.powerbi.com/groups/{workspace_id}/datasets/{model_id}")
        print(f"     refresh (Direct Lake framing): {refresh(roundtrip.get_token(POWERBI), workspace_id, model_id)}")

    if args.warnings:
        print()
        for m in messages:
            print(paint("2", f"  {m}"))

    # --- summary -------------------------------------------------------------------------------
    raw = Result(raw_ossie, raw_bim, raw_messages)
    fix = Result(fixed_ossie, bim, messages)

    if not args.details:
        plain_summary(view, raw, fix, raw_ossie, show_fix=not args.raw)
        return

    print(paint("1", "\n  Measures"))
    for m in view.get("measures", []):
        name = m["name"]
        state, dax, why = raw.measure(name)
        line(state, name, f"{clip(m['expr'])}  ->  {clip(dax, 40)}", why)
        if state != "ok" and not args.raw:
            new_state, new_dax, _ = fix.measure(name)
            if new_state == "ok":
                fixed(clip(new_dax, 60), notes.get(name, ""))

    print(paint("1", "\n  Columns"))
    arrived = []
    for dataset in raw_ossie["datasets"]:
        for field in dataset.get("fields", []):
            name = f"{dataset['name']}.{field['name']}"
            state, why = raw.column(dataset["name"], field["name"])
            if state == "ok":
                arrived.append(name)
            else:
                line(state, name, f"{clip(dialects(field)[0]['expression'])}  ->  BLANK()", why)
    if arrived:
        line("ok", f"{len(arrived)} columns", paint("2", ", ".join(c.split(".", 1)[1] for c in arrived)))
    if raw.typed() < len(raw.columns):
        line("lost", f"{len(raw.columns) - raw.typed()} column types", "missing", "a Metric View has no column types")
        if not args.raw and fix.typed() >= len(fix.columns):
            fixed(f"{fix.typed()} dataTypes", notes.get("types", ""))
    labels = sum(1 for m in raw_messages if "display label" in m)
    if labels:
        line("lost", f"{labels} labels", "dropped", "Power BI has no separate display label")
    wanted = sum(1 for d in raw_ossie["datasets"] for f in d.get("fields", []) if stash(f, "DATABRICKS").get("format")) \
        + sum(1 for m in raw_ossie.get("metrics", []) if stash(m, "DATABRICKS").get("format"))
    if wanted:
        line("lost", f"{wanted} formats", "dropped", "only kept in the DATABRICKS custom_extensions")
        if not args.raw and fix.formats():
            fixed(f"{fix.formats()} formatStrings", notes.get("formats", ""))

    print(paint("1", "\n  Relationships"))
    for rel in raw_ossie.get("relationships", []):
        name = f"{rel['from']} -> {rel['to']}"
        state, why = raw.relationship(rel)
        line(state, name, "" if state == "ok" else "skipped", why)
        if state != "ok" and not args.raw and fix.relationship(rel)[0] == "ok":
            fixed("relationship built", notes.get(f"relationship {name}", ""))

    print(f"\n  Converter result: {paint('32', 'success')} "
          + paint("2", f"(exit 0, {len(raw_messages)} warnings - only those tell you)"))


if __name__ == "__main__":
    main()
