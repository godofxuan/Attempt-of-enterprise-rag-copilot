import pytest

from app.domain.queries import SearchRequest, UserContext
from app.retrieval.pipeline import HybridRetrievalPipeline


USER = UserContext(
    user_id="employee-one",
    tenant_id="tenant-one",
    region="cn",
    groups=["employees"],
)


def request() -> SearchRequest:
    return SearchRequest(
        query="needle",
        purpose="parent expansion",
        user=USER,
        mode="bm25",
        top_k=1,
        candidate_k=1,
        include_parent=True,
    )


def test_child_keeps_citation_but_uses_authorized_parent_context(
    chunk_factory,
    snapshot_factory,
) -> None:
    parent = chunk_factory(
        chunk_id="parent-a",
        doc_id="doc-a",
        kind="parent",
        indexable=False,
        text="Full authorized parent context with policy conditions.",
    )
    child = chunk_factory(
        chunk_id="child-a",
        doc_id="doc-a",
        kind="child",
        parent_chunk_id="parent-a",
        text="needle matched child",
    )
    pipeline = HybridRetrievalPipeline(
        snapshot_factory([child], parents=[parent])
    )

    hit = pipeline.search(request()).hits[0]

    assert hit.chunk_id == "child-a"
    assert hit.matched_text == "needle matched child"
    assert hit.context_text == parent.text
    assert hit.context_from_parent is True


@pytest.mark.parametrize(
    "parent_updates",
    [
        {"doc_id": "doc-b"},
        {"acl_groups": ["board_only"]},
    ],
)
def test_mismatched_or_denied_parent_never_expands_context(
    parent_updates,
    chunk_factory,
    snapshot_factory,
) -> None:
    parent_values = {
        "chunk_id": "parent-a",
        "doc_id": "doc-a",
        "kind": "parent",
        "indexable": False,
        "text": "secret or unrelated parent text",
    }
    parent_values.update(parent_updates)
    parent = chunk_factory(**parent_values)
    child = chunk_factory(
        chunk_id="child-a",
        doc_id="doc-a",
        kind="child",
        parent_chunk_id="parent-a",
        text="needle matched child",
    )
    pipeline = HybridRetrievalPipeline(
        snapshot_factory([child], parents=[parent])
    )

    hit = pipeline.search(request()).hits[0]

    assert hit.context_text == child.text
    assert hit.context_from_parent is False
    assert "secret or unrelated" not in hit.context_text
