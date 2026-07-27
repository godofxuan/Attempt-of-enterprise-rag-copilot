from __future__ import annotations

import re
from pathlib import Path

from app.deployment.releases import (
    RUNTIME_CONTRACT_PATHS,
    calculate_runtime_contract_sha256,
)


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_image_is_digest_pinned_and_runs_as_numeric_non_root() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split("FROM dependencies AS runtime", maxsplit=1)[1]

    assert re.search(
        r"^FROM python:3\.11\.15-slim-bookworm@sha256:[0-9a-f]{64} ",
        dockerfile,
        flags=re.MULTILINE,
    )
    assert "USER 10001:10001" in runtime
    assert "COPY --chown=10001:10001 app /opt/rag/app" in runtime
    assert "COPY . " not in runtime
    assert "HEALTHCHECK" in runtime
    assert "--host\", \"127.0.0.1\"" in runtime


def test_compose_contract_is_single_host_least_privilege_and_digest_only() -> None:
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    for required in (
        "network_mode: host",
        'user: "10001:10001"',
        "read_only: true",
        "cap_drop:",
        "- ALL",
        "no-new-privileges:true",
        "pids_limit: 512",
        "mem_limit: 4g",
        "source: ${RAG_IDENTITY_ROOT:",
        "read_only: true",
        "DEPLOYMENT_EXPECTED_INDEX_MANIFEST_SHA256:",
    ):
        assert required in compose
    assert "image: ${RAG_IMAGE:?" in compose
    assert "build:" not in compose
    assert "ports:" not in compose


def test_docker_context_excludes_local_secrets_models_and_runtime_state() -> None:
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    for required in (
        ".git",
        ".venv",
        ".env",
        ".private",
        "*.gguf",
        "*.safetensors",
        "data/app.db",
        "data/indexes_v2",
        "data/generated",
    ):
        assert required in ignore


def test_runtime_contract_hash_binds_all_operator_facing_files() -> None:
    first = calculate_runtime_contract_sha256(ROOT)
    second = calculate_runtime_contract_sha256(ROOT)

    assert len(first) == 64
    assert first == second
    assert RUNTIME_CONTRACT_PATHS == (
        ".dockerignore",
        "Dockerfile",
        "deploy/compose.yaml",
        "requirements.txt",
    )
