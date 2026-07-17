import json

import pytest

from app.domain.queries import SearchRequest, UserContext
from app.retrieval.pipeline import HybridRetrievalPipeline


def user(**updates) -> UserContext:
    values = {
        "user_id": "employee-one",
        "tenant_id": "tenant-one",
        "region": "cn",
        "groups": ["employees"],
    }
    values.update(updates)
    return UserContext(**values)


def request(mode: str, **updates) -> SearchRequest:
    values = {
        "request_id": f"request-{mode}",
        "query": "needle",
        "purpose": "find needle policy",
        "user": user(),
        "mode": mode,
        "top_k": 2,
        "candidate_k": 3,
        "include_parent": False,
    }
    values.update(updates)
    return SearchRequest(**values)


@pytest.mark.parametrize("mode", ["bm25", "dense", "hybrid"])
def test_denied_high_score_chunk_never_enters_candidates_or_result(
    mode,
    chunk_factory,
    snapshot_factory,
) -> None:
    visible = chunk_factory(
        chunk_id="visible-chunk",
        doc_id="visible-doc",
        text="needle visible policy",
        checksum="1" * 64,
    )
    denied = chunk_factory(
        chunk_id="secret-chunk",
        doc_id="secret-doc",
        text="needle needle needle secret salary",
        acl_groups=["board_only"],
        checksum="2" * 64,
    )
    distractor = chunk_factory(
        chunk_id="other-chunk",
        doc_id="other-doc",
        text="ordinary unrelated policy",
        checksum="3" * 64,
    )
    snapshot = snapshot_factory(
        [visible, denied, distractor],
        vectors=[[0.8, 0.2], [1.0, 0.0], [0.0, 1.0]],
    )
    pipeline = HybridRetrievalPipeline(
        snapshot,
        embed_text=lambda text: [1.0, 0.0],
    )

    result = pipeline.search(request(mode))
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    assert result.internal_denied_count == 1
    assert "internal_denied_count" not in result.model_dump()
    assert all(hit.chunk_id != "secret-chunk" for hit in result.hits)
    assert all(key.startswith(("acl_", "metadata_", "bm25_", "dense_", "fused_", "returned")) for key in result.stage_counts)
    for secret in ["secret-chunk", "secret-doc", "secret salary", "board_only"]:
        assert secret not in serialized


def test_all_denied_returns_no_visible_evidence_without_ids(
    chunk_factory,
    snapshot_factory,
) -> None:
    denied = chunk_factory(
        chunk_id="secret-chunk",
        doc_id="secret-doc",
        text="needle secret policy",
        acl_groups=["board_only"],
    )
    pipeline = HybridRetrievalPipeline(snapshot_factory([denied]))

    result = pipeline.search(request("bm25", top_k=1, candidate_k=1))

    assert result.hits == []
    assert result.stop_reason == "no_visible_evidence"
    assert result.internal_denied_count == 1
    assert "secret" not in json.dumps(result.model_dump(mode="json"))
