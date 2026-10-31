"""One build record, not a source-tree scan or a model profile."""
import json
from pathlib import Path
import subprocess
import tomllib
from functools import lru_cache


@lru_cache(maxsize=1)
def build_info():
    app_root = Path(__file__).resolve().parent
    packaged = app_root / "resources" / "build.json"
    if packaged.is_file():
        return json.loads(packaged.read_text("utf8"))
    root = app_root.parent
    version = "unknown"
    if (root / "pyproject.toml").is_file():
        version = tomllib.loads((root / "pyproject.toml").read_text("utf8"))["project"]["version"]
    commit, dirty = None, False
    if (root / ".git").exists():
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=3).strip()
            dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--", "app", "frontend/src"], cwd=root, timeout=3))
        except (OSError, subprocess.SubprocessError):
            pass
    return {"version": version, "source_commit": commit,
            "build_id": (commit or "unversioned-source") + ("-dirty" if dirty else ""),
            "source_dirty": dirty}
