from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from app.evaluation.contracts import StrictModel


_PACKAGE_ALLOWLIST = (
    "pytest",
    "pydantic",
    "fastapi",
    "numpy",
    "faiss-cpu",
    "rank-bm25",
    "jieba",
)
_SECRET_KEY_PARTS = ("api_key", "apikey", "password", "secret", "token")


class GitProvenance(StrictModel):
    head: str = Field(min_length=1)
    branch: str | None = None
    dirty: bool


class DatasetProvenance(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_count: int = Field(ge=0)


class CorpusProvenance(StrictModel):
    path: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_id: str | None = None
    generator_version: str | None = None
    document_count: int | None = Field(default=None, ge=0)


class IndexProvenance(StrictModel):
    status: Literal["active", "not_available"]
    root: str | None = None
    run_id: str | None = None
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    embedding_model: str | None = None
    embedding_dimension: int | None = Field(default=None, ge=1)
    chunker_mode: str | None = None


class EnvironmentProvenance(StrictModel):
    python_version: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    packages: dict[str, str]


class RunManifest(StrictModel):
    schema_version: Literal["enterprise_evaluation_run_manifest_v1"] = (
        "enterprise_evaluation_run_manifest_v1"
    )
    producer: Literal["enterprise_agentic_rag_v2"] = "enterprise_agentic_rag_v2"
    run_id: str = Field(min_length=1, max_length=200)
    suite: Literal[
        "retrieval",
        "answer",
        "agent",
        "security",
        "all",
        "ablation",
        "human_review",
    ]
    split: Literal["dev", "test", "regression"]
    mode: Literal["deterministic", "live"]
    started_at_utc: datetime
    completed_at_utc: datetime
    git: GitProvenance
    dataset: DatasetProvenance
    corpus: CorpusProvenance
    index: IndexProvenance
    runtime: dict[str, Any]
    config: dict[str, Any]
    environment: EnvironmentProvenance
    artifacts: dict[str, str] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        import re

        if value in {".", ".."} or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", value
        ):
            raise ValueError("run ID contains unsafe characters")
        return value


def build_run_manifest(
    *,
    run_id: str,
    suite: str,
    split: str,
    mode: str,
    dataset_path: Path,
    corpus_dir: Path,
    index_root: Path | None,
    config: dict[str, Any],
    runtime: dict[str, Any],
    repository_root: Path,
) -> RunManifest:
    now = datetime.now(timezone.utc)
    dataset_path = Path(dataset_path).resolve()
    corpus_dir = Path(corpus_dir).resolve()
    dataset_payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(dataset_payload, list):
        raise ValueError("evaluation dataset must be a JSON array")
    corpus_manifest_path = corpus_dir / "manifest.json"
    corpus_payload = json.loads(corpus_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(corpus_payload, dict):
        raise ValueError("corpus manifest must be a JSON object")

    return RunManifest(
        run_id=run_id,
        suite=suite,
        split=split,
        mode=mode,
        started_at_utc=now,
        completed_at_utc=now,
        git=_git_provenance(Path(repository_root).resolve()),
        dataset=DatasetProvenance(
            path=str(dataset_path),
            sha256=_sha256(dataset_path),
            case_count=len(dataset_payload),
        ),
        corpus=CorpusProvenance(
            path=str(corpus_dir),
            manifest_sha256=_sha256(corpus_manifest_path),
            profile_id=_optional_string(corpus_payload.get("profile_id")),
            generator_version=_optional_string(
                corpus_payload.get("generator_version")
            ),
            document_count=_optional_nonnegative_int(
                corpus_payload.get("document_count")
            ),
        ),
        index=_index_provenance(index_root),
        runtime=_sanitize(runtime),
        config=_sanitize(config),
        environment=_environment_provenance(),
    )


def _git_provenance(root: Path) -> GitProvenance:
    head = _git(root, "rev-parse", "HEAD") or "unavailable"
    branch = _git(root, "branch", "--show-current") or None
    status = _git(root, "status", "--porcelain")
    return GitProvenance(head=head, branch=branch, dirty=bool(status))


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _index_provenance(index_root: Path | None) -> IndexProvenance:
    if index_root is None:
        return IndexProvenance(status="not_available")
    root = Path(index_root).resolve()
    if not (root / "active.json").is_file():
        return IndexProvenance(status="not_available", root=str(root))

    from app.indexing.store import load_index_version

    loaded = load_index_version(root)
    manifest = loaded.manifest
    return IndexProvenance(
        status="active",
        root=str(root),
        run_id=manifest.run_id,
        manifest_sha256=loaded.manifest_sha256,
        embedding_model=manifest.embedding.model,
        embedding_dimension=manifest.embedding.dimension,
        chunker_mode=str(manifest.chunker_config.get("mode") or "unknown"),
    )


def _environment_provenance() -> EnvironmentProvenance:
    packages: dict[str, str] = {}
    for package in _PACKAGE_ALLOWLIST:
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = "not-installed"
    return EnvironmentProvenance(
        python_version=platform.python_version(),
        platform=platform.platform(),
        packages=packages,
    )


def _sanitize(value: Any, *, key: str = "") -> Any:
    if any(part in key.casefold() for part in _SECRET_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(item_key): _sanitize(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


__all__ = [
    "CorpusProvenance",
    "DatasetProvenance",
    "EnvironmentProvenance",
    "GitProvenance",
    "IndexProvenance",
    "RunManifest",
    "build_run_manifest",
]
