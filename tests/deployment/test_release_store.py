from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from app.deployment.releases import (
    DeploymentRelease,
    activate_deployment,
    load_active_deployment,
    recover_deployment,
    register_release,
    render_compose_environment,
    rollback_deployment,
    verify_active_deployment,
)
from app.indexing.store import build_index_version, load_active_pointer
from app.ingestion.chunking import ChunkerConfig


ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"
START = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)


def _embed(text: str) -> list[float]:
    total = sum(ord(character) for character in text)
    return [
        float((total % 97) + 1),
        float((len(text) % 31) + 1),
        float((total % 17) + 1),
        1.0,
    ]


@pytest.fixture(scope="module")
def corpus_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("deployment-corpus") / "corpus"
    write_corpus(target, load_facts(FACTS), load_profile(PROFILE))
    return target


def _build_index(root: Path, corpus_dir: Path, run_id: str, offset: int) -> str:
    build_index_version(
        root=root,
        input_dir=corpus_dir,
        run_id=run_id,
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        embedding_model="deployment-test-4d",
        embed_text=_embed,
        activate=offset == 0,
        started_at=START + timedelta(seconds=offset),
        finished_at=START + timedelta(seconds=offset + 1),
    )
    return (
        root / "versions" / run_id / "manifest.json"
    ).read_bytes().hex()


def _manifest_sha256(index_root: Path, run_id: str) -> str:
    import hashlib

    return hashlib.sha256(
        (index_root / "versions" / run_id / "manifest.json").read_bytes()
    ).hexdigest()


def _release(
    *,
    release_id: str,
    index_root: Path,
    index_run_id: str,
    previous_release_id: str | None,
) -> DeploymentRelease:
    return DeploymentRelease(
        schema_version="enterprise_deployment_release_v1",
        producer="enterprise_agentic_rag_v2",
        release_id=release_id,
        image_reference=(
            f"ghcr.io/example/rag:{release_id}@sha256:" + release_id[-1] * 64
        ),
        source_commit=release_id[-1] * 40,
        runtime_contract_sha256="c" * 64,
        index_run_id=index_run_id,
        index_manifest_sha256=_manifest_sha256(index_root, index_run_id),
        previous_release_id=previous_release_id,
        created_at=START,
    )


def _two_release_store(
    tmp_path: Path,
    corpus_dir: Path,
) -> tuple[Path, Path]:
    state_root = tmp_path / "deployment"
    index_root = tmp_path / "indexes"
    _build_index(index_root, corpus_dir, "index-1", 0)
    _build_index(index_root, corpus_dir, "index-2", 2)
    release_1 = _release(
        release_id="release-1",
        index_root=index_root,
        index_run_id="index-1",
        previous_release_id=None,
    )
    release_2 = _release(
        release_id="release-2",
        index_root=index_root,
        index_run_id="index-2",
        previous_release_id="release-1",
    )
    register_release(state_root, index_root, release_1)
    register_release(state_root, index_root, release_2)
    return state_root, index_root


def test_release_registration_requires_immutable_image_digest(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    index_root = tmp_path / "indexes"
    _build_index(index_root, corpus_dir, "index-1", 0)

    with pytest.raises(
        ValueError,
        match="exact sha256 manifest digest",
    ):
        valid = _release(
            release_id="release-1",
            index_root=index_root,
            index_run_id="index-1",
            previous_release_id=None,
        )
        DeploymentRelease.model_validate(
            {
                **valid.model_dump(mode="json"),
                "image_reference": "ghcr.io/example/rag:latest",
            }
        )

    with pytest.raises(ValueError, match="exact sha256 manifest digest"):
        DeploymentRelease.model_validate(
            {
                **valid.model_dump(mode="json"),
                "image_reference": "https://registry.example/rag@sha256:"
                + "a" * 64,
            }
        )


def test_register_activate_and_render_environment_bind_exact_index(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    state_root, index_root = _two_release_store(tmp_path, corpus_dir)

    pointer = activate_deployment(
        state_root,
        index_root,
        "release-1",
        activated_at=START,
    )
    verified = verify_active_deployment(state_root, index_root)
    environment = render_compose_environment(state_root, index_root)

    assert verified == pointer
    assert pointer.index_run_id == "index-1"
    assert "DEPLOYMENT_RELEASE_ID=release-1\n" in environment
    assert "DEPLOYMENT_EXPECTED_INDEX_RUN_ID=index-1\n" in environment
    assert "RAG_IMAGE=ghcr.io/example/rag:release-1@sha256:" in environment


def test_release_registration_is_append_only(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    state_root, index_root = _two_release_store(tmp_path, corpus_dir)
    release = _release(
        release_id="release-1",
        index_root=index_root,
        index_run_id="index-1",
        previous_release_id=None,
    )

    with pytest.raises(FileExistsError, match="already exists"):
        register_release(state_root, index_root, release)


def test_activation_requires_a_linear_release_chain(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    state_root, index_root = _two_release_store(tmp_path, corpus_dir)

    with pytest.raises(ValueError, match="does not extend"):
        activate_deployment(state_root, index_root, "release-2")


def test_rollback_restores_release_and_index_together(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    state_root, index_root = _two_release_store(tmp_path, corpus_dir)
    activate_deployment(state_root, index_root, "release-1")
    activate_deployment(state_root, index_root, "release-2")

    pointer = rollback_deployment(state_root, index_root)

    assert pointer.release_id == "release-1"
    assert load_active_pointer(index_root).run_id == "index-1"
    assert verify_active_deployment(state_root, index_root) == pointer


def test_mid_activation_failure_is_detected_and_can_restore_previous(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    state_root, index_root = _two_release_store(tmp_path, corpus_dir)
    activate_deployment(state_root, index_root, "release-1")

    with pytest.raises(RuntimeError, match="injected activation failure"):
        activate_deployment(
            state_root,
            index_root,
            "release-2",
            before_deployment_replace=lambda: (_ for _ in ()).throw(
                RuntimeError("injected activation failure")
            ),
        )

    assert load_active_pointer(index_root).run_id == "index-2"
    with pytest.raises(RuntimeError, match="recovery is required"):
        load_active_deployment(state_root)

    recovered = recover_deployment(
        state_root,
        index_root,
        strategy="restore_previous",
    )
    assert recovered is not None
    assert recovered.release_id == "release-1"
    assert load_active_pointer(index_root).run_id == "index-1"
    verify_active_deployment(state_root, index_root)


def test_mid_activation_failure_can_complete_verified_target(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    state_root, index_root = _two_release_store(tmp_path, corpus_dir)
    activate_deployment(state_root, index_root, "release-1")

    with pytest.raises(RuntimeError):
        activate_deployment(
            state_root,
            index_root,
            "release-2",
            before_deployment_replace=lambda: (_ for _ in ()).throw(
                RuntimeError("stop after index activation")
            ),
        )

    recovered = recover_deployment(
        state_root,
        index_root,
        strategy="complete_target",
    )
    assert recovered is not None
    assert recovered.release_id == "release-2"
    assert load_active_pointer(index_root).run_id == "index-2"
    verify_active_deployment(state_root, index_root)
