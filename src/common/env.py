import os
from pathlib import Path

# src/common/env.py -> common/ -> src/ -> repo root. Anchored on this file's
# own location (stable regardless of invocation cwd), not on the caller's
# __file__, since callers live at varying depths (databricks/, snowflake/).
REPO_ROOT = Path(__file__).parent.parent.parent


def load_env_file(path: Path = REPO_ROOT / ".env") -> None:
    """Set env vars from a `KEY=value` file, without overriding ones already set.

    Defaults to the repo root's `.env` - every caller wants that one; pass
    `path` explicitly to load a different file instead.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
