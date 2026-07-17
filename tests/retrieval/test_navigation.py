from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.domain.agent import ToolError
from app.domain.documents import SourceLocator
from app.domain.queries import (
    FindRequest,
    FindResult,
    OpenRequest,
    OpenResult,
    SearchRequest,
    SearchResult,
    UserContext,
)
from app.retrieval.navigation import DocumentNavigator
from app.retrieval.pipeline import HybridRetrievalPipeline


USER = UserContext(
    user_id="employee-one",
    tenant_id="tenant-one",
    region="cn",
    groups=["employees"],
)


def _navigation_snapshot(chunk_factory, document_factory, snapshot_factory):
    documents = [
        document_factory(
            doc_id="doc-a",
            title="Approval Policy",
            text="Approval policy full document: approval limit is 5000 yuan.",
        ),
        document_factory(
            doc_id="doc-b",
            title="Travel Policy",
            source_path="documents/doc-b.md",
            policy_id="policy-b",
            text="Travel policy ordinary content.",
        ),
        document_factory(
            doc_id="doc-c",
            title="Expense Policy",
            source_path="documents/doc-c.md",
            policy_id="policy-c",
            text="Expense policy ordinary content.",
        ),
    ]
    chunks = [
        chunk_factory(
            chunk_id="chunk-a-2",
            doc_id="doc-a",
            text="needle approval limit is 5000 yuan",
            locator=SourceLocator(kind="paragraph", start=20),
        ),
        chunk_factory(
            chunk_id="chunk-a-1",
            doc_id="doc-a",
            text="approval limit requires manager review",
            locator=SourceLocator(kind="paragraph", start=10),
        ),
        chunk_factory(
            chunk_id="chunk-b",
            doc_id="doc-b",
            source_path="documents/doc-b.md",
            policy_id="policy-b",
            text="ordinary travel content",
        ),
        chunk_factory(
            chunk_id="chunk-c",
            doc_id="doc-c",
            source_path="documents/doc-c.md",
            policy_id="policy-c",
            text="ordinary expense content",
        ),
    ]
    parent = chunk_factory(
        chunk_id="parent-a",
        doc_id="doc-a",
        kind="parent",
        indexable=False,
        text="Parent approval context with all workflow details.",
    )
    return snapshot_factory(chunks, parents=[parent], documents=documents)


def test_search_discovers_visible_documents(
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _navigation_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )
    navigator = DocumentNavigator(snapshot)

    result = navigator.search(
        SearchRequest(
            query="needle",
            purpose="discover the approval policy",
            user=USER,
            mode="bm25",
            top_k=1,
            candidate_k=4,
        )
    )

    assert isinstance(result, SearchResult)
    assert result.stop_reason == "ok"
    assert [hit.chunk_id for hit in result.hits] == ["chunk-a-2"]


def test_find_is_scoped_bounded_and_stably_ordered(
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _navigation_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )
    navigator = DocumentNavigator(snapshot)

    result = navigator.find(
        FindRequest(
            request_id="find-approval",
            user=USER,
            doc_id="doc-a",
            pattern="approval limit",
            max_results=1,
        )
    )

    assert isinstance(result, FindResult)
    assert result.request_id == "find-approval"
    assert result.stop_reason == "ok"
    assert [match.chunk_id for match in result.matches] == ["chunk-a-1"]
    assert "approval limit" in result.matches[0].preview.casefold()


@pytest.mark.parametrize(
    ("target_type", "target_id", "expected_content"),
    [
        ("chunk", "chunk-a-2", "needle approval limit"),
        ("parent", "parent-a", "Parent approval context"),
        ("document", "doc-a", "Approval policy full document"),
    ],
)
def test_open_reads_only_snapshot_targets(
    target_type,
    target_id,
    expected_content,
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _navigation_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )
    result = DocumentNavigator(snapshot).open(
        OpenRequest(
            user=USER,
            target_type=target_type,
            target_id=target_id,
        )
    )

    assert isinstance(result, OpenResult)
    assert expected_content in result.content
    assert result.truncated is False


def test_open_applies_character_limit(
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _navigation_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )

    result = DocumentNavigator(snapshot).open(
        OpenRequest(
            user=USER,
            target_type="document",
            target_id="doc-a",
            max_chars=12,
        )
    )

    assert isinstance(result, OpenResult)
    assert result.content == "Approval pol"
    assert result.truncated is True


def test_wrong_target_type_is_not_found(
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _navigation_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )

    result = DocumentNavigator(snapshot).open(
        OpenRequest(
            user=USER,
            target_type="parent",
            target_id="chunk-a-2",
        )
    )

    assert isinstance(result, ToolError)
    assert result.code == "not_found"
    assert "chunk-a-2" not in result.safe_message


@dataclass
class _MutableClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


class _SlowPipeline:
    def __init__(self, delegate, clock: _MutableClock) -> None:
        self.delegate = delegate
        self.clock = clock

    def search(self, request):
        result = self.delegate.search(request)
        self.clock.value = 1.0
        return result


@pytest.mark.parametrize(
    ("exception", "code", "retryable"),
    [
        (ValueError("bad vector at D:/secret/model.bin"), "invalid_args", False),
        (RuntimeError("database password=secret"), "system", True),
    ],
)
def test_search_maps_exceptions_to_safe_tool_errors(
    exception,
    code,
    retryable,
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _navigation_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )

    class RaisingPipeline:
        def search(self, request):
            raise exception

    result = DocumentNavigator(snapshot, pipeline=RaisingPipeline()).search(
        SearchRequest(
            query="needle",
            purpose="error mapping",
            user=USER,
            mode="bm25",
        )
    )

    assert isinstance(result, ToolError)
    assert result.code == code
    assert result.retryable is retryable
    assert "secret" not in result.safe_message.casefold()
    assert "D:/" not in result.safe_message


def test_search_enforces_post_call_deadline(
    chunk_factory,
    document_factory,
    snapshot_factory,
) -> None:
    snapshot = _navigation_snapshot(
        chunk_factory,
        document_factory,
        snapshot_factory,
    )
    clock = _MutableClock()
    pipeline = _SlowPipeline(HybridRetrievalPipeline(snapshot), clock)
    navigator = DocumentNavigator(snapshot, pipeline=pipeline, clock=clock)

    result = navigator.search(
        SearchRequest(
            query="needle",
            purpose="deadline",
            user=USER,
            mode="bm25",
            timeout_ms=10,
        )
    )

    assert isinstance(result, ToolError)
    assert result.code == "timeout"
    assert result.retryable is True
