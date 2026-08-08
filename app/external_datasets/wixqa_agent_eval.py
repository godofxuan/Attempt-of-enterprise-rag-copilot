from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enterprise_documents import EnterpriseDocument
from app.domain.queries import (
    FindMatch,
    FindRequest,
    FindResult,
    OpenRequest,
    OpenResult,
    SearchHit,
    SearchRequest,
    SearchResult,
)
from app.external_datasets.wixqa import WixQAQuestion
from app.external_datasets.wixqa_retrieval import WixQAFlatChunk
from app.retrieval.pipeline import RankedSearchCandidate, RankedSearchPool
from app.utils import tokenize_for_bm25


RankArticles = Callable[[str], list[str]]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WixQAAgentCase(_StrictModel):
    question_id: str = Field(min_length=1)
    cohort: str = Field(min_length=1)
    gold_article_count: int = Field(ge=1)
    b2_ranked_article_ids: list[str] = Field(max_length=5)
    b2_recall_at_5: float = Field(ge=0, le=1)
    searched_article_ids: list[str]
    search_evidence_recall: float = Field(ge=0, le=1)
    cited_article_ids: list[str]
    citation_precision: float | None = Field(default=None, ge=0, le=1)
    citation_recall: float = Field(ge=0, le=1)
    citation_complete: float = Field(ge=0, le=1)
    response_mode: str = Field(min_length=1)
    stop_reason: str = Field(min_length=1)
    search_calls: int = Field(ge=0)
    find_calls: int = Field(ge=0)
    open_calls: int = Field(ge=0)
    tool_steps: int = Field(ge=0)
    context_chars: int = Field(ge=0)
    supported_aspects: int = Field(ge=0)
    last_tool_status: str | None = None
    last_error_code: str | None = None
    b2_latency_ms: float = Field(ge=0)
    agent_latency_ms: float = Field(ge=0)


class WixQAAgentSummary(_StrictModel):
    schema_version: str = "wixqa_agent_summary_v1"
    cohort: str = Field(min_length=1)
    case_count: int = Field(ge=1)
    multi_article_case_count: int = Field(ge=0)
    b2_recall_at_5: float = Field(ge=0, le=1)
    search_evidence_recall: float = Field(ge=0, le=1)
    citation_precision: float | None = Field(default=None, ge=0, le=1)
    citation_recall: float = Field(ge=0, le=1)
    multi_article_citation_complete: float | None = Field(
        default=None, ge=0, le=1
    )
    answered_rate: float = Field(ge=0, le=1)
    search_calls_mean: float = Field(ge=0)
    find_calls_mean: float = Field(ge=0)
    open_calls_mean: float = Field(ge=0)
    open_case_rate: float = Field(ge=0, le=1)
    b2_latency_ms_p95: float = Field(ge=0)
    agent_latency_ms_p95: float = Field(ge=0)
    latency_ratio_p95: float = Field(ge=0)


class WixQARankedNavigator:
    def __init__(
        self,
        *,
        rank_articles: RankArticles,
        articles: Sequence[EnterpriseDocument],
        chunks: Sequence[WixQAFlatChunk],
        index_run_id: str,
        manifest_sha256: str,
    ) -> None:
        self.rank_articles = rank_articles
        self.articles = {item.source_native_id: item for item in articles}
        self.chunks_by_article: dict[str, list[WixQAFlatChunk]] = {}
        for chunk in chunks:
            self.chunks_by_article.setdefault(chunk.article_id, []).append(chunk)
        self.index_run_id = index_run_id
        self.manifest_sha256 = manifest_sha256
        self.search_rankings: list[list[str]] = []

    def search_ranked(self, request: SearchRequest) -> RankedSearchPool:
        ranking = self.rank_articles(request.query)
        self.search_rankings.append(ranking[: request.top_k])
        candidates = tuple(
            RankedSearchCandidate(
                rank=rank,
                hit=self._search_hit(article_id, rank, request.query),
                document_title=self.articles[article_id].title,
            )
            for rank, article_id in enumerate(
                ranking[: request.candidate_k], start=1
            )
            if article_id in self.articles
        )
        return RankedSearchPool(
            request_id=request.request_id,
            query=request.query,
            mode=request.mode,
            index_run_id=self.index_run_id,
            manifest_sha256=self.manifest_sha256,
            candidates=candidates,
            visible_candidate_count=len(self.articles),
            internal_denied_count=0,
            stage_counts={
                "acl_visible": len(self.articles),
                "metadata_visible": len(self.articles),
                "bm25_candidates": min(200, len(self.articles)),
                "dense_candidates": min(200, len(self.articles)),
                "fused_candidates": len(ranking),
                "returned": 0,
            },
            stop_reason="ok" if candidates else "no_match",
        )

    def search(self, request: SearchRequest) -> SearchResult:
        pool = self.search_ranked(request)
        hits = [item.hit for item in pool.candidates[: request.top_k]]
        return SearchResult(
            request_id=pool.request_id,
            query=pool.query,
            mode=pool.mode,
            index_run_id=pool.index_run_id,
            manifest_sha256=pool.manifest_sha256,
            hits=hits,
            visible_candidate_count=pool.visible_candidate_count,
            internal_denied_count=0,
            stage_counts={**pool.stage_counts, "returned": len(hits)},
            stop_reason="ok" if hits else "no_match",
        )

    def find(self, request: FindRequest) -> FindResult:
        article = self.articles.get(request.doc_id)
        if article is None:
            return FindResult(
                request_id=request.request_id,
                doc_id=request.doc_id,
                matches=[],
                stop_reason="not_found",
            )
        haystack = article.text.casefold()
        needle = request.pattern.casefold()
        position = haystack.find(needle)
        matches = []
        if position >= 0:
            preview = article.text[max(0, position - 80) : position + 240]
            chunk = self.chunks_by_article[request.doc_id][0]
            matches.append(
                FindMatch(
                    doc_id=request.doc_id,
                    chunk_id=chunk.chunk_id,
                    section_path=[article.title],
                    preview=preview,
                )
            )
        return FindResult(
            request_id=request.request_id,
            doc_id=request.doc_id,
            matches=matches,
            stop_reason="ok" if matches else "not_found",
        )

    def open(self, request: OpenRequest) -> OpenResult:
        article = self.articles[request.target_id]
        content = article.text[: request.max_chars]
        return OpenResult(
            request_id=request.request_id,
            target_type=request.target_type,
            target_id=request.target_id,
            doc_id=request.target_id,
            content=content,
            truncated=len(article.text) > len(content),
            source_path=f"wixqa://article/{request.target_id}",
            section_path=[article.title],
        )

    def searched_article_ids(self) -> list[str]:
        return list(
            dict.fromkeys(
                article_id
                for ranking in self.search_rankings
                for article_id in ranking
            )
        )

    def _search_hit(self, article_id: str, rank: int, query: str) -> SearchHit:
        article = self.articles[article_id]
        chunk = _best_query_chunk(self.chunks_by_article[article_id], query)
        score = 1.0 / rank
        return SearchHit(
            index_run_id=self.index_run_id,
            chunk_id=chunk.chunk_id,
            doc_id=article_id,
            parent_chunk_id=f"wixqa:{article_id}:context",
            source_path=f"wixqa://article/{article_id}",
            section_path=[article.title],
            matched_text=_query_preview(chunk.text, query),
            context_text=chunk.text,
            context_from_parent=True,
            tenant_id="wixqa-public",
            region="global",
            acl_groups=["public"],
            version_id=article.raw_provenance.source_revision,
            version=article.raw_provenance.source_revision,
            status="active",
            authority_level=1,
            variant="official-wixqa",
            fused_score=score,
            dense_score=None,
            bm25_score=None,
        )


def score_wixqa_agent_case(
    question: WixQAQuestion,
    *,
    cohort: str,
    b2_ranked_article_ids: Sequence[str],
    searched_article_ids: Sequence[str],
    cited_article_ids: Sequence[str],
    response_mode: str,
    stop_reason: str,
    trace: dict,
    b2_latency_ms: float,
    agent_latency_ms: float,
) -> WixQAAgentCase:
    gold = set(question.article_ids)
    b2 = list(dict.fromkeys(b2_ranked_article_ids))[:5]
    searched = list(dict.fromkeys(searched_article_ids))
    cited = list(dict.fromkeys(cited_article_ids))
    budget = trace.get("budget", {})
    steps = trace.get("steps", [])
    tool_steps = [
        step for step in steps if step.get("tool") in {"search", "find", "open"}
    ]
    last_tool = tool_steps[-1] if tool_steps else {}
    cited_gold = gold.intersection(cited)
    return WixQAAgentCase(
        question_id=question.question_id,
        cohort=cohort,
        gold_article_count=len(gold),
        b2_ranked_article_ids=b2,
        b2_recall_at_5=len(gold.intersection(b2)) / len(gold),
        searched_article_ids=searched,
        search_evidence_recall=len(gold.intersection(searched)) / len(gold),
        cited_article_ids=cited,
        citation_precision=(len(cited_gold) / len(cited) if cited else None),
        citation_recall=len(cited_gold) / len(gold),
        citation_complete=float(gold <= set(cited)),
        response_mode=response_mode,
        stop_reason=stop_reason,
        search_calls=int(budget.get("search_calls", 0)),
        find_calls=int(budget.get("find_calls", 0)),
        open_calls=int(budget.get("open_calls", 0)),
        tool_steps=len(tool_steps),
        context_chars=int(budget.get("context_chars", 0)),
        supported_aspects=int(trace.get("evidence", {}).get("supported", 0)),
        last_tool_status=last_tool.get("status"),
        last_error_code=last_tool.get("error_code"),
        b2_latency_ms=b2_latency_ms,
        agent_latency_ms=agent_latency_ms,
    )


def summarize_wixqa_agent_cases(
    cases: Sequence[WixQAAgentCase], *, cohort: str
) -> WixQAAgentSummary:
    if not cases:
        raise ValueError("cannot summarize empty WixQA Agent cases")
    multi = [case for case in cases if case.gold_article_count > 1]
    cited_precisions = [
        case.citation_precision
        for case in cases
        if case.citation_precision is not None
    ]
    b2_latency = sorted(case.b2_latency_ms for case in cases)
    agent_latency = sorted(case.agent_latency_ms for case in cases)
    b2_p95 = _nearest_rank(b2_latency, 0.95)
    agent_p95 = _nearest_rank(agent_latency, 0.95)
    return WixQAAgentSummary(
        cohort=cohort,
        case_count=len(cases),
        multi_article_case_count=len(multi),
        b2_recall_at_5=_mean(case.b2_recall_at_5 for case in cases),
        search_evidence_recall=_mean(
            case.search_evidence_recall for case in cases
        ),
        citation_precision=(
            _mean(value for value in cited_precisions if value is not None)
            if cited_precisions
            else None
        ),
        citation_recall=_mean(case.citation_recall for case in cases),
        multi_article_citation_complete=(
            _mean(case.citation_complete for case in multi) if multi else None
        ),
        answered_rate=_mean(
            float(case.response_mode in {"answered", "partial"}) for case in cases
        ),
        search_calls_mean=_mean(case.search_calls for case in cases),
        find_calls_mean=_mean(case.find_calls for case in cases),
        open_calls_mean=_mean(case.open_calls for case in cases),
        open_case_rate=_mean(float(case.open_calls > 0) for case in cases),
        b2_latency_ms_p95=b2_p95,
        agent_latency_ms_p95=agent_p95,
        latency_ratio_p95=agent_p95 / b2_p95 if b2_p95 else 0.0,
    )


def _mean(values) -> float:
    rows = list(values)
    return sum(rows) / len(rows)


def _nearest_rank(values: Sequence[float], fraction: float) -> float:
    return values[max(0, math.ceil(fraction * len(values)) - 1)]


def _best_query_chunk(
    chunks: Sequence[WixQAFlatChunk], query: str
) -> WixQAFlatChunk:
    query_tokens = {
        token.casefold() for token in tokenize_for_bm25(query) if token.strip()
    }
    return max(
        chunks,
        key=lambda chunk: (
            len(
                query_tokens.intersection(
                    token.casefold()
                    for token in tokenize_for_bm25(chunk.text)
                    if token.strip()
                )
            ),
            -chunk.ordinal,
        ),
    )


def _query_preview(text: str, query: str, max_chars: int = 300) -> str:
    lowered = text.casefold()
    positions = [
        lowered.find(token.casefold())
        for token in tokenize_for_bm25(query)
        if token.strip() and lowered.find(token.casefold()) >= 0
    ]
    position = min(positions) if positions else 0
    start = max(0, position - max_chars // 3)
    end = min(len(text), start + max_chars)
    return text[max(0, end - max_chars) : end]


__all__ = [
    "WixQAAgentCase",
    "WixQAAgentSummary",
    "WixQARankedNavigator",
    "score_wixqa_agent_case",
    "summarize_wixqa_agent_cases",
]
