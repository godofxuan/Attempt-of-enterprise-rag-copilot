from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from contextlib import closing
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.security.model_endpoint import parse_pinned_model_endpoint


class WorkspaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_endpoint: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen3.5:9b"
    embedding_model: str = "bge-m3"
    request_timeout_seconds: float = Field(default=90, ge=1, le=300)
    max_parallel_requests: int = Field(default=1, ge=1, le=4)
    sample_data: bool = False

    @field_validator("model_endpoint")
    @classmethod
    def local_endpoint(cls, value):
        return parse_pinned_model_endpoint(value).origin


def data_root(value=None):
    import os

    return Path(value or os.getenv("ESA_DATA_DIR") or Path.home() / ".esa").expanduser().resolve()


def load_config(root, overrides=None):
    import os

    path = root / "workspace.json"
    values = json.loads(path.read_text("utf8")) if path.exists() else {}
    for key in ("model_endpoint", "chat_model", "embedding_model"):
        if os.getenv("ESA_" + key.upper()):
            values[key] = os.environ["ESA_" + key.upper()]
    values.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return WorkspaceConfig.model_validate(values)


def initialize(root, *, sample=False):
    """Explicit idempotent initialization; serve never resets or seeds user state."""
    from app.runtime.workspace_lock import WorkspaceLease

    with WorkspaceLease(root):
        _initialize(root, sample=sample)


def _initialize(root, *, sample=False):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "workspace.json"
    if not path.exists():
        config = WorkspaceConfig(sample_data=sample)
        with path.open("x", encoding="utf8") as stream:
            stream.write(config.model_dump_json(indent=2) + "\n")
    for folder in ("documents", "indexes", "logs"):
        (root / folder).mkdir(exist_ok=True)
    with closing(sqlite3.connect(root / "app.sqlite3")) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS workspace_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        db.execute(
            "INSERT OR IGNORE INTO workspace_meta VALUES('initialized_at',?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
    if sample and load_config(root).sample_data:
        from app.workbench_service import seed_sample

        seed_sample(root)
