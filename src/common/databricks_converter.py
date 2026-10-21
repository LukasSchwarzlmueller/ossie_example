import os
from pathlib import Path

from common.env import REPO_ROOT

BUILD_DIR = REPO_ROOT / ".ossie" / "converters" / "databricks" / "java" / "target"


def find_jar() -> Path:
    """Java Databricks converter jar: $OSSIE_DATABRICKS_JAR, else the build_converter.sh output."""
    if env_jar := os.environ.get("OSSIE_DATABRICKS_JAR"):
        return Path(env_jar)
    built = sorted(BUILD_DIR.glob("ossie-databricks-converter-*.jar"))
    built = [j for j in built if not j.name.endswith(("-sources.jar", "-javadoc.jar"))]
    if not built:
        raise SystemExit("converter jar not found - run databricks/build_converter.sh (see README.md).")
    return built[0]
