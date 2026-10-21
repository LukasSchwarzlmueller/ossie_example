#!/usr/bin/env bash
# Build the Java Ossie -> Databricks converter at a pinned apache/ossie-converters commit.
# Needs git, JDK 21+ and Maven. To update the converter, change CONVERTERS_REV and rerun.
set -euo pipefail

CONVERTERS_REV=853c52986cd03508fe233fbab8c4213890943095
DIR="$(cd "$(dirname "$0")/.." && pwd)/.ossie-converters"

if [ ! -d "$DIR/.git" ]; then
  git clone https://github.com/apache/ossie-converters "$DIR"
fi
git -C "$DIR" fetch origin
git -C "$DIR" checkout "$CONVERTERS_REV"

(cd "$DIR/databricks/java" && mvn clean package)

JAR=$(ls "$DIR"/databricks/java/target/ossie-databricks-converter-*.jar | grep -v -e sources -e javadoc | head -n 1)
echo
echo "Built: $JAR"
echo "export_metric_view.py finds it automatically; set OSSIE_DATABRICKS_JAR in .env to use another jar."
