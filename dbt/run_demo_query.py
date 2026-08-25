"""Run a real, working `mf query` against the local dbt project - one command.

dbt-core 1.12's native OSI -> MetricFlow conversion has two real bugs (see
NOTES.md and scripts/patch_manifest_for_mf_query.py's docstring): it never
sets `agg_time_dimension`, and it misattributes `order_count` to the wrong
semantic model. `dbt parse`/`dbt run` succeed cleanly despite both - the
manifest just isn't queryable as-compiled.

This script chains the actual working sequence (dbt run -> patch -> mf
query) into one command, so "the metrics are queryable" is something you
run, not just claim. Sticks to `total_revenue`/`avg_order_value` -
`order_count` still fails for an unrelated, unpatched reason (bare
`COUNT(*)` generates invalid SQL); see NOTES.md if you want to show that
failure on purpose.

Usage (from the repo root or from dbt/, doesn't matter):
    uv run python3 dbt/run_demo_query.py
"""

import os
import subprocess
from pathlib import Path

DBT_DIR = Path(__file__).parent


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=DBT_DIR, env={**os.environ, "DBT_PROFILES_DIR": "."}, check=True)


def main() -> None:
    run(["uv", "run", "dbt", "--quiet", "run"])
    run(["uv", "run", "python3", "scripts/patch_manifest_for_mf_query.py"])
    run([
        "uv", "run", "mf", "query",
        "--metrics", "total_revenue,avg_order_value",
        "--group-by", "customer_id__customer_segment",
    ])


if __name__ == "__main__":
    main()
