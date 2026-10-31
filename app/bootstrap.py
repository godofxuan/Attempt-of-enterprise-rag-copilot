"""Explicit dependencies and lifetime for the sole product factory."""

from datetime import datetime
from contextlib import closing
import sqlite3
import httpx
from app.persistence.workspaces import load_config, WorkspaceConfig
from app.api.workbench_errors import WorkspaceError


class Workspace:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir.resolve()
        self.db_path = settings.sqlite_path.resolve()
        self.configuration_error = None
        try:
            self.config = load_config(self.root)
        except (ValueError, OSError) as exc:
            self.configuration_error = {
                "message": "工作区配置需要修复，原文件保持未改。请到设置核对并保存。",
                "detail": str(exc),
            }
            self.config = WorkspaceConfig()
        self.started = False
        self.client = None

    async def start(self):
        # No model probe, index load, source scan, fixture import or business seed.
        from app.runtime.workspace_lock import WorkspaceLease

        self.lease = WorkspaceLease(self.root).acquire()
        self.root.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            # History/source snapshots must not block short business commits.
            # Keep the existing single-workspace lease and BEGIN IMMEDIATE
            # transaction checks; WAL changes reader/writer coexistence only.
            if db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
                raise RuntimeError("WORKSPACE_WAL_UNAVAILABLE: 工作区需要支持SQLite WAL的本地磁盘")
            db.execute(
                "CREATE TABLE IF NOT EXISTS workspace_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
            )
        self.client = httpx.AsyncClient(
            trust_env=False,
            timeout=2,
            follow_redirects=False,
            transport=getattr(self, "model_transport", None),
        )
        from app.runtime.workbench_models import ModelService
        from app.knowledge.service import Library
        from app.runtime.workbench_runs import Runs
        from app.workbench_service import TaskService

        self.models = ModelService(self)
        self.library = Library(self)
        self.runs = Runs(self)
        self.service = TaskService(self)
        from app.conversations import ConversationService

        self.conversations = ConversationService(self)
        await self.library.start()
        self.started = True

    async def close(self):
        if getattr(self, "runs", None):
            await self.runs.close()
        if getattr(self, "library", None):
            await self.library.close()
        if getattr(self, "models", None):
            await self.models.close()
        if self.client:
            await self.client.aclose()
        if getattr(self, "lease", None):
            self.lease.close()
        self.started = False

    async def status(self):
        models = []
        error = None
        try:
            response = await self.client.get(self.config.model_endpoint + "/api/tags")
            response.raise_for_status()
            models = [
                {"name": m["name"], "digest": m.get("digest")} for m in response.json()["models"]
            ]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            error = {"code": "MODEL_UNAVAILABLE", "message": str(exc)}
        found = {m["name"].removesuffix(":latest") for m in models}
        initialized = None
        calls = 0
        onboarding = False
        if self.db_path.is_file():
            with sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True) as db:
                tables = {
                    r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "workspace_meta" in tables:
                    initialized = db.execute(
                        "SELECT value FROM workspace_meta WHERE key='initialized_at'"
                    ).fetchone()
                    onboarding = bool(
                        db.execute(
                            "SELECT 1 FROM workspace_meta WHERE key='onboarding_completed'"
                        ).fetchone()
                    )
                    # Existing usable workspaces do not become new installations after upgrade.
                    if not onboarding and "conversations" in tables:
                        onboarding = bool(
                            db.execute("SELECT 1 FROM conversations LIMIT 1").fetchone()
                        )
                if "model_calls" in tables:
                    calls = db.execute(
                        "SELECT COUNT(*) FROM model_calls WHERE kind='chat'"
                    ).fetchone()[0]
        return {
            "web": True,
            "storage": self.started,
            "data_dir": str(self.root),
            "database": str(self.db_path),
            "initialized_at": initialized[0] if initialized else None,
            "models": models,
            "chat": {
                "ready": self.config.chat_model.removesuffix(":latest") in found,
                "model": self.config.chat_model,
            },
            "embedding": {
                "ready": self.config.embedding_model.removesuffix(":latest") in found,
                "model": self.config.embedding_model,
            },
            "model_error": error,
            "mode": "SYNTHETIC_LOCAL" if self.config.sample_data else "LOCAL_OWNER",
            "generation_calls": calls,
            "configuration_error": self.configuration_error,
            "onboarding_complete": onboarding,
        }

    def save_settings(self, changes):
        if getattr(self, "runs", None) and (self.runs.tasks or self.library.running):
            raise WorkspaceError(
                409,
                "SETTINGS_IN_USE",
                {"reason": "请先完成或停止当前运行/索引任务，再修改模型连接"},
            )
        updated = self.config.model_copy(update=changes)
        updated = WorkspaceConfig.model_validate(updated.model_dump())
        if self.configuration_error:
            import shutil

            shutil.copy2(
                self.root / "workspace.json",
                self.root
                / ("workspace.invalid." + datetime.now().strftime("%Y%m%d%H%M%S%f") + ".json"),
            )
        temp = self.root / "workspace.json.tmp"
        temp.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf8")
        temp.replace(self.root / "workspace.json")
        self.config = updated
        self.configuration_error = None
        return updated.model_dump()
