#!/usr/bin/env bash
# Build the Java Ossie -> Databricks converter at a pinned apache/ossie commit.
# Needs git, JDK 21+ and Maven. To update the converter, change OSSIE_REV and rerun.
set -euo pipefail

OSSIE_REV=7c03c46eae6c9946f50d9aa6c36918cdfb28f540
DIR="$(cd "$(dirname "$0")/.." && pwd)/.ossie"

if [ ! -d "$DIR/.git" ]; then
  git clone https://github.com/apache/ossie "$DIR"
fi
git -C "$DIR" fetch origin
git -C "$DIR" checkout "$OSSIE_REV"

(cd "$DIR/converters/databricks/java" && mvn clean package)

JAR=$(ls "$DIR"/converters/databricks/java/target/ossie-databricks-converter-*.jar | grep -v -e sources -e javadoc | head -n 1)
echo
echo "Built: $JAR"
echo "export_metric_view.py finds it automatically; set OSSIE_DATABRICKS_JAR in .env to use another jar."
