#!/usr/bin/env bash
# Build the Java Ossie -> Databricks converter at a pinned apache/ossie-converters commit.
# Only needed by databricks_powerbi and roundtrip_databricks. The pin is the
# last commit with the Java converter: upstream replaced it on 2026-11-18 (#218) with a Python one
# that has no joins, so it cannot read a joined metric view back into Ossie.
# Needs git, JDK 21+ and Maven. To update the converter, change CONVERTERS_REV and rerun.
set -euo pipefail

CONVERTERS_REV=6f91f23dbfa6a9c5fad05242860ee4db20767f49
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="$HERE/../.ossie-converters"

if [ ! -d "$DIR/.git" ]; then
  git clone https://github.com/apache/ossie-converters "$DIR"
fi
git -C "$DIR" fetch origin
# Drop earlier local patches so checkout and re-patching start clean.
git -C "$DIR" reset --hard --quiet
git -C "$DIR" checkout "$CONVERTERS_REV"

# Local fixes on top of the pinned commit, until they land upstream (see README.md).
for PATCH in "$HERE"/patches/*.patch; do
  git -C "$DIR" apply "$PATCH"
  echo "Applied: $(basename "$PATCH")"
done

(cd "$DIR/databricks/java" && mvn clean package)

JAR=$(ls "$DIR"/databricks/java/target/ossie-databricks-converter-*.jar | grep -v -e sources -e javadoc | head -n 1)
echo
echo "Built: $JAR"
echo "export_metric_view.py finds it automatically; set OSSIE_DATABRICKS_JAR in .env to use another jar."
