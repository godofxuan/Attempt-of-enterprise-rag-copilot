from __future__ import annotations

from app.domain.documents import SourceLocator
from app.domain.queries import (
    FindResult,
    OpenResult,
    SearchHit,
    SearchResult,
    UserContext,
)
from app.domain.retrieved_security import (
    AdmittedEvidenceChunk,
    AdmittedOpenResult,
)
from app.retrieval.pipeline import RankedSearchCandidate, RankedSearchPool
from app.security.retrieved_content import RetrievedContentGuard


def user_context() -> UserContext:
    return UserContext(
        user_id="employee-one",
        tenant_id="tenant-one",
        region="cn",
        groups=["employees"],
    )


def search_hit(**updates) -> SearchHit:
    values = {
        "index_run_id": "run-one",
        "chunk_id": "chunk-a",
        "doc_id": "doc-a",
        "parent_chunk_id": None,
        "policy_id": "policy-a",
        "source_path": "documents/doc-a.md",
        "section_path": ["Policy A"],
        "locator": SourceLocator(kind="paragraph", start=1),
        "matched_text": "Policy A allows remote work three days per month.",
        "context_text": "Policy A allows remote work three days per month.",
        "context_from_parent": False,
        "tenant_id": "tenant-one",
        "region": "cn",
        "acl_groups": ["employees"],
        "version_id": "policy-a@2026",
        "version": "2026",
        "status": "active",
        "authority_level": 100,
        "variant": "authoritative",
        "fact_ids": ["fact-a"],
        "fused_score": 1.0,
        "bm25_score": 1.0,
        "bm25_rank": 1,
    }
    values.update(updates)
    return SearchHit(**values)


def search_result(
    hits: list[SearchHit] | None = None,
    *,
    stop_reason: str | None = None,
    denied_count: int = 0,
) -> SearchResult:
    hits = hits or []
    reason = stop_reason or ("ok" if hits else "no_match")
    return SearchResult(
        request_id="request",
        query="policy",
        mode="hybrid",
        index_run_id="run-one",
        manifest_sha256="a" * 64,
        hits=hits,
        visible_candidate_count=len(hits),
        internal_denied_count=denied_count,
        stage_counts={"returned": len(hits)},
        stop_reason=reason,
    )


def admit_search_hit(hit: SearchHit) -> AdmittedEvidenceChunk:
    guard = RetrievedContentGuard()
    admitted_hit = hit
    if hit.context_from_parent and hit.context_text == hit.matched_text:
        admitted_hit = hit.model_copy(update={"context_from_parent": False})
    matched_decision = guard.scan(hit.matched_text)
    metadata_decision = guard.scan(
        "\n".join(
            part
            for part in [
                hit.source_path,
                *hit.section_path,
                hit.locator.label if hit.locator is not None else None,
                hit.version,
            ]
            if part
        )
    )
    context_decision = (
        guard.scan(hit.context_text)
        if hit.context_from_parent and hit.context_text != hit.matched_text
        else None
    )
    return AdmittedEvidenceChunk(
        hit=admitted_hit,
        matched_decision=matched_decision,
        context_decision=context_decision,
        metadata_decision=metadata_decision,
    )


def admitted_search_hit(**updates) -> AdmittedEvidenceChunk:
    return admit_search_hit(search_hit(**updates))


def admit_open_result(result: OpenResult) -> AdmittedOpenResult:
    guard = RetrievedContentGuard()
    return AdmittedOpenResult(
        result=result,
        content_decision=guard.scan(result.content),
        metadata_decision=guard.scan(
            "\n".join([result.source_path, *result.section_path])
        ),
    )


def find_result(*, doc_id: str = "doc-a", matches=None) -> FindResult:
    matches = matches or []
    return FindResult(
        request_id="request",
        doc_id=doc_id,
        matches=matches,
        stop_reason="ok" if matches else "not_found",
    )


def open_result(
    *,
    target_id: str = "doc-a",
    content: str = "Visible document content.",
) -> OpenResult:
    return OpenResult(
        request_id="request",
        target_type="document",
        target_id=target_id,
        doc_id=target_id,
        content=content,
        truncated=False,
        source_path=f"documents/{target_id}.md",
        section_path=[],
    )


class RecordingNavigator:
    def __init__(
        self,
        *,
        search_results=None,
        find_results=None,
        open_results=None,
        search_error: Exception | None = None,
    ) -> None:
        self.search_results = list(search_results or [])
        self.find_results = list(find_results or [])
        self.open_results = list(open_results or [])
        self.search_error = search_error
        self.calls: list[tuple[str, object]] = []

    def search(self, request):
        self.calls.append(("search", request))
        if self.search_error is not None:
            raise self.search_error
        return self.search_results.pop(0)

    def search_ranked(self, request):
        self.calls.append(("search", request))
        if self.search_error is not None:
            raise self.search_error
        result = self.search_results.pop(0)
        if not isinstance(result, SearchResult):
            return result
        return RankedSearchPool(
            request_id=result.request_id,
            query=result.query,
            mode=result.mode,
            index_run_id=result.index_run_id,
            manifest_sha256=result.manifest_sha256,
            candidates=tuple(
                RankedSearchCandidate(
                    rank=rank,
                    hit=hit,
                    document_title=None,
                )
                for rank, hit in enumerate(result.hits, start=1)
            ),
            visible_candidate_count=result.visible_candidate_count,
            internal_denied_count=result.internal_denied_count,
            stage_counts=dict(result.stage_counts),
            stop_reason=result.stop_reason,
        )

    def find(self, request):
        self.calls.append(("find", request))
        return self.find_results.pop(0)

    def open(self, request):
        self.calls.append(("open", request))
        return self.open_results.pop(0)


__all__ = [
    "RecordingNavigator",
    "admit_open_result",
    "admit_search_hit",
    "admitted_search_hit",
    "find_result",
    "open_result",
    "search_hit",
    "search_result",
    "user_context",
]
