"""The Java Databricks converter, plus the one step its output needs for Ossie 0.3.0.dev0.

    uv run python -m common.databricks_converter metric_view.yaml -o ossie.yaml
"""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from common.env import REPO_ROOT

BUILD_DIR = REPO_ROOT / ".ossie-converters" / "databricks" / "java" / "target"


def find_jar() -> Path:
    """Java Databricks converter jar: $OSSIE_DATABRICKS_JAR, else the build_converter.sh output."""
    if env_jar := os.environ.get("OSSIE_DATABRICKS_JAR"):
        return Path(env_jar)
    built = sorted(BUILD_DIR.glob("ossie-databricks-converter-*.jar"))
    built = [j for j in built if not j.name.endswith(("-sources.jar", "-javadoc.jar"))]
    if not built:
        raise SystemExit("converter jar not found - run databricks/build_converter.sh (see README.md).")
    return built[0]


def _run(command: str, text: str) -> tuple[str, str]:
    """Run the jar on `text`; returns (converted text, converter messages)."""
    with tempfile.TemporaryDirectory() as tmp:
        source, target = Path(tmp) / "input.yaml", Path(tmp) / "output.yaml"
        source.write_text(text)
        result = subprocess.run(
            ["java", "-jar", str(find_jar()), command, str(source), "-o", str(target)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit(f"converter failed:\n{result.stdout}{result.stderr}")
        return target.read_text(), result.stderr


def ossie_to_metric_view(ossie_yaml: str) -> tuple[str, str]:
    return _run("export", ossie_yaml)


def metric_view_to_ossie(metric_view_yaml: str) -> tuple[str, str]:
    return _run("import", metric_view_yaml)


def to_nonportable_extensions(node):
    """Rewrite `custom_extensions` (JSON strings) as `nonportable_extensions` (objects), in place.

    The Java converter stops at the older form of 0.3.0.dev0; apache/ossie#522 renamed the field
    and the Microsoft converter accepts only the new one.
    """
    if isinstance(node, list):
        for item in node:
            to_nonportable_extensions(item)
    elif isinstance(node, dict):
        if "custom_extensions" in node:
            node["nonportable_extensions"] = [
                {**ext, "data": json.loads(ext["data"])} for ext in node.pop("custom_extensions")
            ]
        for key, value in node.items():
            if key != "nonportable_extensions":
                to_nonportable_extensions(value)
    return node


def main() -> None:
    parser = argparse.ArgumentParser(description="Metric View -> Ossie, ready for the Microsoft converter")
    parser.add_argument("metric_view", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    ossie_yaml, _ = metric_view_to_ossie(args.metric_view.read_text())
    model = to_nonportable_extensions(yaml.safe_load(ossie_yaml))
    args.output.write_text(yaml.safe_dump(model, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
