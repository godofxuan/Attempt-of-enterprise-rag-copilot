"""Capture local runtime identity without performing model inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import requests

from app.config import get_settings
from app.retrieval.serving_config import ServingRetrievalSettings
from app.security.model_endpoint import parse_pinned_model_endpoint


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    root = Path(__file__).resolve().parents[1]

    def git(*arguments: str) -> str:
        return subprocess.check_output(["git", *arguments], cwd=root).decode("utf-8").strip()

    identity = {}
    for filename in git(
        "ls-files", "--cached", "--others", "--exclude-standard", "app"
    ).splitlines():
        path = root / filename
        identity[filename] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    package_versions = {}
    for package in ("numpy", "faiss-cpu", "pydantic", "fastapi", "requests", "pytest", "pypdf"):
        try:
            package_versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            package_versions[package] = None
    origin = parse_pinned_model_endpoint(settings.llm_base_url).origin
    model_status = "AVAILABLE"
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(f"{origin}/api/tags", timeout=5, allow_redirects=False)
            response.raise_for_status()
            models = {row["name"]: row["digest"] for row in response.json()["models"]}
    except (requests.RequestException, ValueError, KeyError):
        models = {}
        model_status = "UNAVAILABLE"
    try:
        gpu = (
            subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,driver_version",
                    "--format=csv,noheader",
                ],
                timeout=10,
            )
            .decode("utf-8")
            .strip()
        )
    except (OSError, subprocess.SubprocessError):
        gpu = None
    pointer_path = settings.v2_indexes_dir / "active.json"
    pointer_bytes = pointer_path.read_bytes()
    disk = shutil.disk_usage(root)
    payload = {
        "schema_version": "runtime_delivery_baseline_v1",
        "kind": "ENVIRONMENT_CAPTURE_NOT_MODEL_EVALUATION",
        "captured_at": datetime.now(UTC).isoformat(),
        "git_sha": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "git_dirty": bool(git("status", "--porcelain")),
        "app_worktree_changed": bool(git("status", "--porcelain", "--", "app")),
        "app_file_sha256": identity,
        "python": sys.version,
        "platform": platform.platform(),
        "packages": package_versions,
        "gpu": gpu,
        "workspace_free_bytes": disk.free,
        "config": {
            name: getattr(settings, name)
            for name in (
                "chat_model",
                "evidence_model",
                "embedding_model",
                "agent_v2_deadline_ms",
                "api_request_deadline_ms",
                "model_request_timeout_seconds",
                "model_max_attempts",
                "structured_generation_max_attempts",
            )
        },
        "model_status": model_status,
        "serving_retrieval": {
            "profile": ServingRetrievalSettings().retrieval_profile,
            "device": ServingRetrievalSettings().reranker_device,
        },
        "ollama_model_digests": models,
        "active_pointer": json.loads(pointer_bytes),
        "active_pointer_sha256": hashlib.sha256(pointer_bytes).hexdigest(),
        "real_model_evaluation": "NOT_RUN",
    }
    encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(encoded)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "app_worktree_changed": payload["app_worktree_changed"],
                "model_status": model_status,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
