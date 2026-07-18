from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.domain.queries import QueryFilters, SearchRequest, UserContext
from app.evaluation.indirect_injection_dataset import (
    build_v1_bundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_live_index import (
    build_live_fixture_index,
)
from app.retrieval.pipeline import HybridRetrievalPipeline


FROZEN_AT = "2026-07-18T00:00:00Z"
FREEZE_HEAD = "a" * 40
FIXTURE_SHA256 = "b" * 64
BUILD_TIME = datetime(2026, 7, 18, 1, 2, 3, tzinfo=timezone.utc)


def _embedding(text: str, dimension: int = 8) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [float(digest[index] + 1) for index in range(dimension)]


@pytest.fixture()
def test_bundle(tmp_path: Path):
    security_root = tmp_path / "security-data"
    build_v1_bundle(
        security_root,
        frozen_at_utc=FROZEN_AT,
        freeze_git_head=FREEZE_HEAD,
    )
    return load_security_bundle(security_root, "test")


def test_build_projects_fixtures_to_a_valid_active_v2_snapshot(
    tmp_path: Path,
    test_bundle,
) -> None:
    calls: list[str] = []

    def tracked_embedding(text: str) -> list[float]:
        calls.append(text)
        return _embedding(text)

    built = build_live_fixture_index(
        dataset=test_bundle.dataset,
        fixtures=test_bundle.fixture_manifest,
        root=tmp_path / "live-security-index",
        run_id="r2-s1-d7-test-index",
        fixture_sha256=FIXTURE_SHA256,
        embedding_model="bge-m3",
        embed_text=tracked_embedding,
        started_at=BUILD_TIME,
        finished_at=BUILD_TIME,
    )

    expected_candidates = sum(
        len(case.candidates) for case in test_bundle.fixture_manifest.cases
    )
    expected_documents = {
        candidate.document_id
        for case in test_bundle.fixture_manifest.cases
        for candidate in case.candidates
    }
    expected_documents.update(
        opened.document_id
        for case in test_bundle.fixture_manifest.cases
        for opened in case.open_results
    )

    assert built.snapshot.version.manifest == built.manifest
    assert built.snapshot.version.manifest_sha256 == built.manifest_sha256
    assert built.manifest.corpus_manifest_hash == FIXTURE_SHA256
    assert built.manifest.embedding.model == "bge-m3"
    assert built.manifest.embedding.dimension == 8
    assert built.manifest.indexed_chunk_count == expected_candidates
    assert built.manifest.canonical_document_count == len(expected_documents)
    assert built.embedding_call_count == expected_candidates
    assert len(calls) == expected_candidates
    assert (built.index_root / "active.json").is_file()

    case_by_chunk = {
        candidate.chunk_id: case.case_id
        for case in test_bundle.fixture_manifest.cases
        for candidate in case.candidates
    }
    assert all(
        chunk.policy_id == case_by_chunk[chunk.chunk_id]
        for chunk in built.snapshot.chunks
    )
    assert all(chunk.variant == "authoritative" for chunk in built.snapshot.chunks)


def test_projection_preserves_title_parent_and_open_attack_surfaces(
    tmp_path: Path,
    test_bundle,
) -> None:
    built = build_live_fixture_index(
        dataset=test_bundle.dataset,
        fixtures=test_bundle.fixture_manifest,
        root=tmp_path / "live-security-index",
        run_id="r2-s1-d7-surface-index",
        fixture_sha256=FIXTURE_SHA256,
        embedding_model="bge-m3",
        embed_text=_embedding,
        started_at=BUILD_TIME,
        finished_at=BUILD_TIME,
    )

    title_case = next(
        case
        for case in test_bundle.fixture_manifest.cases
        if any(candidate.title_unit_id for candidate in case.candidates)
    )
    title_candidate = next(
        candidate for candidate in title_case.candidates if candidate.title_unit_id
    )
    assert (
        built.snapshot.documents_by_id[title_candidate.document_id].title
        == title_candidate.document_title
    )

    parent_case = next(
        case
        for case in test_bundle.fixture_manifest.cases
        if any(candidate.context_from_parent for candidate in case.candidates)
    )
    parent_candidate = next(
        candidate
        for candidate in parent_case.candidates
        if candidate.context_from_parent
    )
    assert (
        built.snapshot.parents_by_id[parent_candidate.parent_chunk_id].text
        == parent_candidate.context_text
    )

    open_case = next(
        case for case in test_bundle.fixture_manifest.cases if case.open_results
    )
    opened = open_case.open_results[0]
    assert built.snapshot.documents_by_id[opened.document_id].text == opened.content


def test_production_retrieval_is_policy_isolated_and_embeds_the_query(
    tmp_path: Path,
    test_bundle,
) -> None:
    built = build_live_fixture_index(
        dataset=test_bundle.dataset,
        fixtures=test_bundle.fixture_manifest,
        root=tmp_path / "live-security-index",
        run_id="r2-s1-d7-retrieval-index",
        fixture_sha256=FIXTURE_SHA256,
        embedding_model="bge-m3",
        embed_text=_embedding,
        started_at=BUILD_TIME,
        finished_at=BUILD_TIME,
    )
    query_calls: list[str] = []

    def query_embedding(text: str) -> list[float]:
        query_calls.append(text)
        return _embedding(text)

    case = test_bundle.dataset.cases[0]
    fixture = test_bundle.fixture_manifest.cases[0]
    pipeline = HybridRetrievalPipeline(
        built.snapshot,
        embed_text=query_embedding,
    )
    pool = pipeline.ranked_candidates_for_guard(
        SearchRequest(
            request_id="d7-index-test",
            query=case.question,
            purpose="D7 paired security evaluation",
            user=UserContext(
                user_id="synthetic-evaluator",
                tenant_id="synthetic-tenant",
                region="global",
                groups=["synthetic-employees"],
                roles=["knowledge-reader"],
            ),
            filters=QueryFilters(policy_ids=[case.case_id]),
            top_k=1,
            candidate_k=4,
        )
    )

    assert query_calls == [case.question]
    assert pool.stop_reason == "ok"
    assert pool.visible_candidate_count == len(fixture.candidates)
    assert {item.hit.chunk_id for item in pool.candidates} == {
        item.chunk_id for item in fixture.candidates
    }


def test_build_is_immutable_and_does_not_touch_the_production_index(
    tmp_path: Path,
    test_bundle,
) -> None:
    production_active = tmp_path / "production-index" / "active.json"
    production_active.parent.mkdir(parents=True)
    production_active.write_bytes(b"production-sentinel\n")
    before = production_active.read_bytes()
    security_root = tmp_path / "live-security-index"

    kwargs = {
        "dataset": test_bundle.dataset,
        "fixtures": test_bundle.fixture_manifest,
        "root": security_root,
        "run_id": "r2-s1-d7-immutable-index",
        "fixture_sha256": FIXTURE_SHA256,
        "embedding_model": "bge-m3",
        "embed_text": _embedding,
        "started_at": BUILD_TIME,
        "finished_at": BUILD_TIME,
    }
    build_live_fixture_index(**kwargs)

    with pytest.raises(FileExistsError):
        build_live_fixture_index(**kwargs)

    assert production_active.read_bytes() == before


@pytest.mark.parametrize("unsafe_run_id", ["../escape", "bad/path", "C:drive"])
def test_build_rejects_unsafe_run_ids(
    tmp_path: Path,
    test_bundle,
    unsafe_run_id: str,
) -> None:
    with pytest.raises(ValueError):
        build_live_fixture_index(
            dataset=test_bundle.dataset,
            fixtures=test_bundle.fixture_manifest,
            root=tmp_path / "live-security-index",
            run_id=unsafe_run_id,
            fixture_sha256=FIXTURE_SHA256,
            embedding_model="bge-m3",
            embed_text=_embedding,
            started_at=BUILD_TIME,
            finished_at=BUILD_TIME,
        )
