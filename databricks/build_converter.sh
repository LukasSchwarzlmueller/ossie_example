#!/usr/bin/env bash
# Build the Java Ossie -> Databricks converter at a pinned apache/ossie-converters commit.
# Needs git, JDK 21+ and Maven. To update the converter, change CONVERTERS_REV and rerun.
set -euo pipefail

CONVERTERS_REV=811149647ef280b652a03efab112fa937372c21d
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
