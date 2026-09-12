import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent  # src/common/env.py -> repo root


def load_env_file(path: Path = REPO_ROOT / ".env") -> None:
    """Set env vars from a `KEY=value` file, without overriding ones already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
