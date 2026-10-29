"""Local workbench lifecycle and HTTP projection in the existing FastAPI app."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
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
    return Path(value or os.getenv("ESA_DATA_DIR") or Path.home()/".esa").expanduser().resolve()


def load_config(root, overrides=None):
    import os
    path = root/"workspace.json"
    values = json.loads(path.read_text("utf8")) if path.exists() else {}
    for key in ("model_endpoint", "chat_model", "embedding_model"):
        if os.getenv("ESA_"+key.upper()): values[key] = os.environ["ESA_"+key.upper()]
    values.update({k:v for k,v in (overrides or {}).items() if v is not None})
    return WorkspaceConfig.model_validate(values)


def initialize(root, *, sample=False):
    """Explicit idempotent initialization; serve never resets or seeds user state."""
    root.mkdir(parents=True, exist_ok=True)
    path = root/"workspace.json"
    if not path.exists():
        config = WorkspaceConfig(sample_data=sample)
        with path.open("x", encoding="utf8") as stream: stream.write(config.model_dump_json(indent=2)+"\n")
    for folder in ("documents", "indexes", "logs"): (root/folder).mkdir(exist_ok=True)
    with sqlite3.connect(root/"app.sqlite3") as db:
        db.execute("CREATE TABLE IF NOT EXISTS workspace_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO workspace_meta VALUES('initialized_at',?)", (datetime.now(timezone.utc).isoformat(),))


class Workspace:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir.resolve()
        self.db_path = settings.sqlite_path.resolve()
        self.config = load_config(self.root)
        self.started = False
        self.client = None

    async def start(self):
        # No model probe, index load, source scan, fixture import or business seed.
        self.root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS workspace_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        self.client = httpx.AsyncClient(trust_env=False, timeout=2, follow_redirects=False)
        self.started = True

    async def close(self):
        if self.client: await self.client.aclose()
        self.started = False

    async def status(self):
        models = []; error = None
        try:
            response = await self.client.get(self.config.model_endpoint+"/api/tags")
            response.raise_for_status()
            models = [{"name":m["name"],"digest":m.get("digest")} for m in response.json()["models"]]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            error = {"code": "MODEL_UNAVAILABLE", "message": str(exc)}
        found = {m["name"].removesuffix(":latest") for m in models}
        with sqlite3.connect(self.db_path) as db:
            initialized = db.execute("SELECT value FROM workspace_meta WHERE key='initialized_at'").fetchone()
        return {"web":True,"storage":self.started,"data_dir":str(self.root),"database":str(self.db_path),
                "initialized_at":initialized[0] if initialized else None,"models":models,
                "chat":{"ready":self.config.chat_model.removesuffix(":latest") in found,"model":self.config.chat_model},
                "embedding":{"ready":self.config.embedding_model.removesuffix(":latest") in found,"model":self.config.embedding_model},
                "model_error":error,"mode":"SYNTHETIC_LOCAL" if self.config.sample_data else "LOCAL_OWNER",
                "generation_calls":0}

    def save_settings(self, changes):
        updated = self.config.model_copy(update=changes)
        updated = WorkspaceConfig.model_validate(updated.model_dump())
        temp = self.root/"workspace.json.tmp"
        temp.write_text(updated.model_dump_json(indent=2)+"\n", encoding="utf8")
        temp.replace(self.root/"workspace.json")
        self.config = updated
        return updated.model_dump()


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_endpoint: str | None = None
    chat_model: str | None = Field(default=None,min_length=1,max_length=200)
    embedding_model: str | None = Field(default=None,min_length=1,max_length=200)
    request_timeout_seconds: float | None = Field(default=None,ge=1,le=300)


def require_local_request(request: Request):
    """Single-user loopback mode, not an enterprise login or a relaxed legacy ACL."""
    if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "LOCAL_OWNER_ONLY")
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).netloc != request.url.netloc or urlsplit(origin).scheme != request.url.scheme):
        raise HTTPException(403, "ORIGIN_MISMATCH")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-esa-request") != "1":
        raise HTTPException(403, "LOCAL_REQUEST_HEADER_REQUIRED")


def workspace_router(workspace):
    router = APIRouter(dependencies=[Depends(require_local_request)])

    @router.get("/", include_in_schema=False)
    def home():
        return FileResponse(Path(__file__).with_name("web")/"index.html", headers={"Cache-Control":"no-store"})

    @router.get("/api/status")
    async def status(): return await workspace.status()

    @router.get("/api/settings")
    def settings(): return workspace.config.model_dump()

    @router.patch("/api/settings")
    def update_settings(payload: SettingsPatch):
        from pydantic import ValidationError
        try: return workspace.save_settings(payload.model_dump(exclude_unset=True))
        except ValidationError as exc: raise HTTPException(422,"INVALID_SETTINGS") from exc

    @router.get("/api/history")
    def history():
        return {"tasks":[],"conversations":[],"database":str(workspace.db_path)}

    return router
