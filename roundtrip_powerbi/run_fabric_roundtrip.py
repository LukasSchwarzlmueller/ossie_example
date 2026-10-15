"""Ossie -> Fabric -> Ossie round trip, through a real Fabric workspace.

The Power BI model goes up to Fabric and comes back down via the Fabric REST API:

  1. ossie/orders_customers.yaml -> powerbi/model.bim  (Ossie -> Power BI; Fabric glue below
     is applied to the uploaded copy only)
  2. upload to FABRIC_WORKSPACE_ID (create, or update the definition if a model
     with the same name already exists)
  3. download from Fabric (getDefinition, TMSL)
     -> ossie_from_fabric/orders_customers.yaml  (Power BI -> Ossie)

Only those two files are written - the converted model and what came back - then the
starting Ossie file is diffed against the one that came back from Fabric.

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
import time
import urllib.error
import urllib.request
import warnings

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
    show_diff(original_ossie, roundtripped_ossie,
              "ossie/orders_customers.yaml", "ossie_from_fabric/orders_customers.yaml")


if __name__ == "__main__":
    main()
