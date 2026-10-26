"""Ossie -> Fabric -> Ossie round trip, through a real Fabric workspace.

The Power BI model goes up to Fabric and comes back down via the Fabric REST API:

  1. ossie/orders_customers.yaml -> powerbi/model.bim  (Ossie -> Power BI; Fabric glue below
     is applied to the uploaded copy only)
  2. upload to FABRIC_WORKSPACE_ID (create, or update the definition if a model
     with the same name already exists)
  3. download from Fabric (getDefinition, TMSL)
     -> ossie_from_fabric/orders_customers.yaml  (Power BI -> Ossie)

Only those two files are written - the converted model and what came back - then the
starting Ossie file is compared with the one that came back from Fabric: every change,
per object, as -/+ lines with the reason next to it (`--diff` adds the raw line diff).

Fabric glue (step 1) - two things Fabric rejects that the converter emits:
  - it only imports models marked `defaultPowerBIDataSourceVersion: powerBI_V3`
  - Direct Lake tables can't hold calculated columns, so those fall back to the
    physical column of the same name (the DAX expression is lost - visible in the diff)

Needs FABRIC_WORKSPACE_ID / FABRIC_LAKEHOUSE_ID in .env; FABRIC_FOLDER_ID is optional and
only used when the model is created. The access token comes from FABRIC_TOKEN if set,
otherwise from `az account get-access-token` (Linux az first, then the Windows az.cmd
via powershell.exe - on WSL behind a device-compliance policy only the Windows one works).
"""

import argparse
import base64
import difflib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import warnings

import yaml

from ossie_microsoft import convert_ossie_to_semantic_model, convert_semantic_model_to_ossie

from common.env import REPO_ROOT, load_env_file

# every ossie_microsoft warning is also logged; keep --warnings the only way to see them
logging.getLogger("ossie_microsoft").addHandler(logging.NullHandler())

ROUNDTRIP_DIR = REPO_ROOT / "roundtrip_powerbi"
INPUT = ROUNDTRIP_DIR / "ossie" / "orders_customers.yaml"
POWERBI_DIR = ROUNDTRIP_DIR / "powerbi"
OSSIE_BACK_DIR = ROUNDTRIP_DIR / "ossie_from_fabric"
PLACEHOLDER = "__catalog__.__schema__"
API = "https://api.fabric.microsoft.com/v1"
RESOURCE = "https://api.fabric.microsoft.com"
WINDOWS_AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
PBISM = {"version": "4.2", "settings": {}}


def get_token() -> str:
    if token := os.environ.get("FABRIC_TOKEN"):
        return token
    az_args = f"account get-access-token --resource {RESOURCE} --query accessToken -o tsv"
    attempts = [
        ["az", *az_args.split()],
        ["powershell.exe", "-NoProfile", "-Command", f"cd C:\\; & '{WINDOWS_AZ}' {az_args}"],
    ]
    for cmd in attempts:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            continue
        token = result.stdout.strip()
        if result.returncode == 0 and token.startswith("ey"):
            return token
    raise SystemExit("No Fabric token: set FABRIC_TOKEN or run `az login` (on WSL: in Windows PowerShell)")


class Fabric:
    def __init__(self, token: str, workspace_id: str):
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self.workspace = f"{API}/workspaces/{workspace_id}"

    def call(self, method: str, url: str, body: dict | None = None) -> dict | None:
        """One request; follows Fabric's long-running-operation protocol on 202."""
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{method} {url} -> {e.code}: {e.read().decode()}")
        if response.status != 202:
            text = response.read().decode()
            return json.loads(text) if text else None

        location = response.headers["Location"]
        while True:
            time.sleep(int(response.headers.get("Retry-After", 2)))
            response = urllib.request.urlopen(urllib.request.Request(location, headers=self.headers))
            operation = json.load(response)
            if operation["status"] == "Failed":
                raise SystemExit(f"Fabric operation failed: {operation.get('error')}")
            if operation["status"] == "Succeeded":
                break
        try:
            result = urllib.request.urlopen(urllib.request.Request(f"{location}/result", headers=self.headers))
        except urllib.error.HTTPError:
            return None  # operations like updateDefinition have no result body
        text = result.read().decode()
        return json.loads(text) if text else None

    def find_model(self, name: str) -> str | None:
        models = self.call("GET", f"{self.workspace}/semanticModels")["value"]
        return next((m["id"] for m in models if m["displayName"] == name), None)

    def upload(self, bim: dict, folder_id: str | None) -> tuple[str, str]:
        definition = {"parts": [
            {"path": "model.bim", "payload": _b64(bim), "payloadType": "InlineBase64"},
            {"path": "definition.pbism", "payload": _b64(PBISM), "payloadType": "InlineBase64"},
        ]}
        if model_id := self.find_model(bim["name"]):
            self.call("POST", f"{self.workspace}/semanticModels/{model_id}/updateDefinition",
                      {"definition": definition})
            return model_id, "updated"
        body = {"displayName": bim["name"], "definition": definition}
        if folder_id:
            body["folderId"] = folder_id
        return self.call("POST", f"{self.workspace}/semanticModels", body)["id"], "created"

    def download(self, model_id: str) -> dict:
        result = self.call("POST", f"{self.workspace}/semanticModels/{model_id}/getDefinition?format=TMSL")
        part = next(p for p in result["definition"]["parts"] if p["path"] == "model.bim")
        return json.loads(base64.b64decode(part["payload"]))


def flatten(model: dict) -> dict[tuple[str, str], object]:
    """{(object, attribute): value} for one Ossie model, so two models compare key by key.

    Objects are "model", a dataset, "dataset.field", a metric or "relationship from -> to".
    Lists are keyed by what identifies an item (name, dialect, vendor), not by position,
    so reordering is not a difference.
    """
    out = {}

    def walk(obj: str, attr: str, value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(obj, f"{attr}.{key}" if attr else key, child)
        elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            for item in value:
                if "dialect" in item:  # expression.dialects[] -> "ANSI_SQL expression"
                    out[(obj, f"{item['dialect']} expression")] = item.get("expression")
                    continue
                key = item.get("vendor_name") or item.get("name")
                rest = {k: v for k, v in item.items() if k not in ("vendor_name", "name")}
                walk(obj, f"{attr}.{key}", rest)
        else:
            out[(obj, attr)] = value

    for key, value in model.items():
        if key not in ("datasets", "relationships", "metrics"):
            walk("model", key, value)
    for dataset in model.get("datasets", []):
        for key, value in dataset.items():
            if key == "fields":
                for field in value:
                    for fkey, fvalue in field.items():
                        if fkey != "name":
                            walk(f"{dataset['name']}.{field['name']}", fkey, fvalue)
            elif key != "name":
                walk(dataset["name"], key, value)
    for rel in model.get("relationships", []):
        obj = f"relationship {rel['from']} -> {rel['to']}"
        for key, value in rel.items():
            if key not in ("from", "to"):
                walk(obj, key, value)
    for metric in model.get("metrics", []):
        for key, value in metric.items():
            if key != "name":
                walk(metric["name"], key, value)
    return out


SQL_DIALECTS = ("OSSIE_SQL_2026", "ANSI_SQL", "SNOWFLAKE", "DATABRICKS")


def reason(obj: str, attr: str, kind: str) -> str:
    """Why this demo model changes on the way through Fabric; "" when there's no known reason."""
    is_field = "." in obj
    if attr == "label":
        return "Power BI has no separate display label"
    if attr == "datatype" and not is_field:
        return "Power BI measures have no declared type"
    if attr == "dimension.is_time":
        return "Power BI only marks date columns as time"
    if attr == "source":
        return "Direct Lake: the lakehouse is in the model connection (see model above)"
    if obj.startswith("relationship") and attr == "name":
        return "Power BI relationships have no real name, so it is built from the columns (original kept in custom_extensions)"
    if attr.endswith(" expression"):
        if is_field:
            return "Direct Lake: no calculated columns, falls back to the plain column"
        if kind == "+":
            return "translated from the SQL version; the SQL is kept in custom_extensions"
        if attr.split()[0] in SQL_DIALECTS:
            return "Power BI keeps the DAX version only"
    return ""


class _Dumper(yaml.SafeDumper):
    """Multi-line strings as | blocks, so the M query reads like code."""


_Dumper.add_representer(str, lambda dumper, value: dumper.represent_scalar(
    "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None))


def model_extension(ossie: str) -> str | None:
    """The model-level Power BI extension (connection, culture, ...) as readable YAML."""
    for ext in yaml.safe_load(ossie).get("custom_extensions", []):
        if ext.get("vendor_name") == "POWER_BI":
            data = json.loads(ext["data"])
            for expression in data.get("expressions", []):  # M code is stored one line per item
                if isinstance(expression.get("expression"), list):
                    expression["expression"] = "\n".join(expression["expression"])
            return yaml.dump(data, Dumper=_Dumper, sort_keys=False, width=200)
    return None


def show_changes(a: str, b: str) -> None:
    """Every change that matters, per object, as -/+ lines with the reason next to it.

    Left out: reordering, re-quoting, and the Power BI details stored in custom_extensions.
    """
    before, after = flatten(yaml.safe_load(a)), flatten(yaml.safe_load(b))
    color = sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))
    paint = (lambda code, text: f"\033[{code}m{text}\033[0m") if color else (lambda code, text: text)
    is_ext = lambda key: key[1].startswith("custom_extensions")

    rows: dict[str, list[tuple[str, str, object]]] = {}  # object -> [(-/+, attribute, value)]
    for key in dict.fromkeys([*before, *after]):  # file order, before first
        if is_ext(key) or before.get(key) == after.get(key):
            continue
        if key in before:
            rows.setdefault(key[0], []).append(("-", key[1], before[key]))
        if key in after:
            rows.setdefault(key[0], []).append(("+", key[1], after[key]))

    objects = {k[0] for k in before} - {"model"}
    print(f"  {len(objects & {k[0] for k in after})} of {len(objects)} datasets, fields, "
          f"relationships and metrics came back. What changed:")
    show = lambda value: value if isinstance(value, str) else json.dumps(value)
    lines = [(obj, kind, f"{attr}: {show(value)}", reason(obj, attr, kind))
             for obj, changes in rows.items() for kind, attr, value in changes]
    width = max((len(t) for _, _, t, _ in lines), default=0)
    if extension := model_extension(b):
        print(f"\n  {paint('1', 'model')}")
        print(f"    {paint('32', '+ custom_extensions POWER_BI:')}  "
              + paint("2", "Power BI model settings; the lakehouse connection (workspace ID / lakehouse ID) is in DatabaseQuery"))
        for line in extension.splitlines():
            print(paint("32", f"        {line}"))
    last_obj, last_reason = None, None
    for obj, kind, text, why in lines:
        if obj != last_obj:
            print(f"\n  {paint('1', obj)}")
            last_obj, last_reason = obj, None
        note = f"  {why}" if why and why != last_reason else ""  # say each reason once per object
        last_reason = why or last_reason
        line = f"{kind} {text:<{width}}" if note else f"{kind} {text}"
        print(f"    {paint('31' if kind == '-' else '32', line)}{paint('2', note)}")
    ext_objects = sorted({k[0] for k in after if is_ext(k) and before.get(k) != after[k]} - {"model"})
    print(paint("2", f"\n  Not shown: reordering, re-quoting, and Power BI details kept in "
                     f"custom_extensions on {len(ext_objects)} more objects. --diff prints the raw diff."))


def show_diff(a: str, b: str, a_name: str, b_name: str) -> None:
    if a == b:
        print(f"  identical: {a_name} == {b_name}")
        return
    print("".join(difflib.unified_diff(
        a.splitlines(keepends=True), b.splitlines(keepends=True), a_name, b_name
    )))


def _b64(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def fabric_glue(bim: dict) -> None:
    bim["model"].setdefault("defaultPowerBIDataSourceVersion", "powerBI_V3")
    for table in bim["model"]["tables"]:
        if not any(p.get("mode") == "directLake" for p in table.get("partitions", [])):
            continue
        for column in table["columns"]:
            if column.get("type") == "calculated":
                print(f"  {table['name']}.{column['name']}: dropping `{column.pop('expression')}` (Direct Lake)")
                del column["type"]
                column["sourceColumn"] = column["name"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warnings", action="store_true", help="show conversion warnings (hidden by default)"
    )
    parser.add_argument(
        "--diff", action="store_true", help="also print the raw line diff of the two Ossie files"
    )
    args = parser.parse_args()

    load_env_file()
    lakehouse = os.environ.get("FABRIC_LAKEHOUSE", "ossie")
    schema = os.environ.get("FABRIC_SCHEMA", "dbo")
    workspace_id = os.environ.get("FABRIC_WORKSPACE_ID")
    lakehouse_id = os.environ.get("FABRIC_LAKEHOUSE_ID")
    if not (workspace_id and lakehouse_id):
        raise SystemExit("Set FABRIC_WORKSPACE_ID and FABRIC_LAKEHOUSE_ID in .env")
    original_ossie = INPUT.read_text().replace(PLACEHOLDER, f"{lakehouse}.{schema}")

    for folder in (POWERBI_DIR, OSSIE_BACK_DIR):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir()

    fabric = Fabric(get_token(), workspace_id)

    with warnings.catch_warnings():
        if not args.warnings:
            warnings.simplefilter("ignore")

        print("Step 1: Ossie -> Power BI (powerbi/model.bim)")
        source = {"workspaceId": workspace_id, "itemId": lakehouse_id}
        bim = convert_ossie_to_semantic_model(original_ossie, source=source)
        (POWERBI_DIR / "model.bim").write_text(json.dumps(bim, indent=2))  # converter output, before the glue
        fabric_glue(bim)  # in place, only what gets uploaded

        print(f"Step 2: upload '{bim['name']}' to workspace {workspace_id}")
        model_id, action = fabric.upload(bim, os.environ.get("FABRIC_FOLDER_ID"))
        print(f"  {action} semantic model {model_id}")

        print("Step 3: download from Fabric, Power BI -> Ossie (ossie_from_fabric/orders_customers.yaml)")
        downloaded = fabric.download(model_id)
        # Fabric keeps the name on the item (displayName) and leaves it out of model.bim
        downloaded = {"name": bim["name"], **downloaded}
        roundtripped_ossie = convert_semantic_model_to_ossie(downloaded)
        (OSSIE_BACK_DIR / "orders_customers.yaml").write_text(roundtripped_ossie)

    print("\nOssie side: start vs back from Fabric")
    show_changes(original_ossie, roundtripped_ossie)
    if args.diff:
        print()
        show_diff(original_ossie, roundtripped_ossie,
                  "ossie/orders_customers.yaml", "ossie_from_fabric/orders_customers.yaml")


if __name__ == "__main__":
    main()
