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
    assert "XDG_CACHE_HOME=/tmp/xdg-cache" in dockerfile


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


def test_container_ci_routes_test_writes_to_bounded_tmpfs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    gate = workflow.split(
        "- name: Run deterministic gates inside the image",
        maxsplit=1,
    )[1].split(
        "- name: Run readiness failure and rollback drill",
        maxsplit=1,
    )[0]

    for required in (
        "--read-only",
        "--tmpfs /tmp:rw,exec,nosuid,nodev,size=1g,uid=10001,gid=10001",
        (
            "--tmpfs /workspace/data/indexes_v2:"
            "rw,exec,nosuid,nodev,size=256m,uid=10001,gid=10001"
        ),
        "--env HOME=/tmp/home",
        "--env XDG_CACHE_HOME=/tmp/xdg-cache",
        "--env PYTHONPYCACHEPREFIX=/tmp/pycache",
        "-p no:cacheprovider",
    ):
        assert required in gate

    assert "--env DATA_DIR=" not in gate


def test_container_ci_private_outputs_are_owned_by_runtime_identity() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    rollback = workflow.split(
        "- name: Run readiness failure and rollback drill",
        maxsplit=1,
    )[1].split(
        "- name: Generate Python runtime SBOM",
        maxsplit=1,
    )[0]
    sbom = workflow.split(
        "- name: Generate Python runtime SBOM",
        maxsplit=1,
    )[1].split(
        "- name: Upload deployment SBOM",
        maxsplit=1,
    )[0]

    for block in (rollback, sbom):
        assert "sudo chown 10001:10001" in block
        assert "sudo chmod 0700" in block
        assert "chmod 0777" not in block

    assert (
        "sudo docker run -d --rm --name enterprise-rag-api" in rollback
    )
    assert 'sudo chown "$(id -u):$(id -g)"' in sbom
    assert "sudo chmod 0600" in sbom


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
