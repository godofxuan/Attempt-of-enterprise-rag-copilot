from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.domain.queries import QueryFilters, SearchRequest, UserContext
from app.evaluation.runtime import (
    EvaluationRuntimeError,
    build_deterministic_runtime,
    build_live_runtime,
    deterministic_embedding,
)


def test_deterministic_runtime_builds_fixed_hash_index_and_runs_search(
    tmp_path: Path,
    evaluation_corpus_dir: Path,
) -> None:
    runtime = build_deterministic_runtime(
        evaluation_corpus_dir,
        tmp_path / "runtime",
    )
    first = runtime.snapshot.chunks[0]
    user = UserContext(
        user_id="runtime-test",
        tenant_id=first.tenant_id,
        region=first.region,
        groups=list(first.acl_groups),
    )
    result = runtime.pipeline.search(
        SearchRequest(
            query=first.text,
            purpose="runtime smoke test",
            user=user,
            filters=QueryFilters(
                temporal_scope="all",
                authoritative_only=False,
            ),
            top_k=1,
            candidate_k=5,
        )
    )

    assert runtime.mode == "deterministic"
    assert runtime.variant == "fixed-500-80-hash-128-extractive"
    assert runtime.snapshot.version.manifest.chunker_config["mode"] == "fixed"
    assert runtime.snapshot.version.manifest.embedding.model == "deterministic-hash-128"
    assert runtime.snapshot.version.manifest.embedding.dimension == 128
    assert result.hits
    assert runtime.counters.embedding_calls == 0
    assert runtime.counters.generation_calls == 0
    assert runtime.metadata()["model_calls"] == 0


def test_deterministic_embedding_is_stable_and_nonzero() -> None:
    first = deterministic_embedding("远程工作 policy")
    second = deterministic_embedding("远程工作 policy")

    assert first == second
    assert len(first) == 128
    assert any(value != 0 for value in first)


def test_live_runtime_fails_closed_when_active_index_is_absent(
    tmp_path: Path,
) -> None:
    settings = Settings(v2_indexes_dir=tmp_path / "missing-index")

    with pytest.raises(EvaluationRuntimeError, match="active v2 index"):
        build_live_runtime(settings)


def test_runtime_metadata_never_contains_api_key(
    tmp_path: Path,
    evaluation_corpus_dir: Path,
) -> None:
    runtime = build_deterministic_runtime(
        evaluation_corpus_dir,
        tmp_path / "runtime",
    )

    metadata = runtime.metadata()
    assert "api_key" not in metadata
    assert "ollama" not in str(metadata).casefold()
