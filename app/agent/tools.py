from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.evidence import (
    EvidenceAssessment,
    EvidenceAssessor,
    LocalEvidenceAssessor,
    MAX_EVIDENCE_CHUNKS,
    is_usable_rewrite,
)
from app.agent.schemas import EvidenceTraceRecord
from app.eval_metrics import unsafe_answer
from app.rag_service import answer_from_retrieved
from app.retriever import hybrid_search


DEFAULT_REFUSAL_ANSWER = (
    "不能协助绕过审批、泄露敏感信息、编造依据或执行越权操作；"
    "我只能基于知识库提供合规回答。"
)
DEFAULT_NO_ANSWER = "根据当前知识库检索结果，未找到足以回答该问题的明确依据。"
ASSESSMENT_UNAVAILABLE_ANSWER = (
    "当前无法可靠判断知识库证据是否足以回答该问题，请稍后重试。"
)


@dataclass
class ToolExecutionResult:
    updates: dict[str, Any] = field(default_factory=dict)
    output_summary: str = ""


ToolFn = Callable[[dict[str, Any]], ToolExecutionResult]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolFn] = {}

    def register(self, name: str, fn: ToolFn) -> None:
        self._tools[name] = fn

    def run(self, name: str, context: dict[str, Any]) -> ToolExecutionResult:
        if name not in self._tools:
            raise KeyError(f"Tool is not registered: {name}")
        return self._tools[name](context)


def _source_view(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": item.get("source", ""),
        "section": item.get("section", ""),
        "chunk_id": item.get("chunk_id", ""),
        "preview": item.get("preview") or item.get("text", "")[:120],
    }


def _chunk_key(item: dict[str, Any]) -> tuple[str, ...]:
    chunk_id = str(item.get("chunk_id", "")).strip()
    if chunk_id:
        return ("chunk_id", chunk_id)
    return (
        "content",
        str(item.get("source", "")),
        str(item.get("section", "")),
        str(item.get("text", "")),
    )


def _merge_unique_chunks(
    existing: list[dict[str, Any]],
    latest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = []
    seen = set()
    for item in [*existing, *latest]:
        key = _chunk_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _select_assessment_chunks(
    accumulated: list[dict[str, Any]],
    latest: list[dict[str, Any]],
    limit: int = MAX_EVIDENCE_CHUNKS,
) -> list[dict[str, Any]]:
    if len(accumulated) <= limit:
        return accumulated

    latest_unique = _merge_unique_chunks([], latest)
    latest_keys = {_chunk_key(item) for item in latest_unique}
    prior = [item for item in accumulated if _chunk_key(item) not in latest_keys]
    if not prior:
        return latest_unique[:limit]
    if not latest_unique:
        return prior[:limit]

    selected = []
    for index in range(max(len(prior), len(latest_unique))):
        if index < len(prior):
            selected.append(prior[index])
            if len(selected) == limit:
                break
        if index < len(latest_unique):
            selected.append(latest_unique[index])
            if len(selected) == limit:
                break
    return selected


def retrieval_search_tool(context: dict[str, Any]) -> ToolExecutionResult:
    search_query = context.get("search_query") or context["question"]
    attempt = int(context.get("retrieval_attempts", 0)) + 1
    latest = hybrid_search(
        question=search_query,
        top_k=context.get("top_k"),
    )
    accumulated = _merge_unique_chunks(
        context.get("retrieved_chunks", []),
        latest,
    )
    latest_sources = [_source_view(item) for item in latest]
    accumulated_sources = [_source_view(item) for item in accumulated]
    return ToolExecutionResult(
        updates={
            "latest_retrieved_chunks": latest,
            "latest_retrieved_sources": latest_sources,
            "retrieved_chunks": accumulated,
            "retrieved_sources": accumulated_sources,
            "retrieval_attempts": attempt,
            "phase": "retrieved",
        },
        output_summary=(
            f"retrieved {len(latest)} latest chunks for attempt {attempt}; "
            f"{len(accumulated)} accumulated unique chunks"
        ),
    )


def make_evidence_assess_tool(assessor: EvidenceAssessor) -> ToolFn:
    def evidence_assess_tool(context: dict[str, Any]) -> ToolExecutionResult:
        assessment_chunks = _select_assessment_chunks(
            context["retrieved_chunks"],
            context.get("latest_retrieved_chunks", []),
        )
        try:
            assessment = assessor.assess(
                question=context["question"],
                search_query=context["search_query"],
                chunks=assessment_chunks,
            )
        except Exception as exc:
            assessment = EvidenceAssessment(
                verdict="error",
                reason=f"evidence assessment failed: {type(exc).__name__}",
            )

        record = EvidenceTraceRecord(
            attempt=context["retrieval_attempts"],
            search_query=context["search_query"],
            **assessment.model_dump(),
        )
        return ToolExecutionResult(
            updates={
                "evidence_assessment": assessment,
                "evidence_history": [*context.get("evidence_history", []), record],
                "phase": "assessed",
            },
            output_summary=f"evidence {assessment.verdict}: {assessment.reason[:160]}",
        )

    return evidence_assess_tool


def query_rewrite_tool(context: dict[str, Any]) -> ToolExecutionResult:
    assessment = context.get("evidence_assessment")
    if not isinstance(assessment, EvidenceAssessment) or not is_usable_rewrite(
        assessment.rewritten_query,
        context["question"],
        context["search_query"],
    ):
        raise ValueError("query.rewrite requires a usable rewritten query")

    rewritten_query = assessment.rewritten_query
    return ToolExecutionResult(
        updates={
            "search_query": rewritten_query,
            "phase": "rewritten",
        },
        output_summary=f"applied rewritten search query: {rewritten_query}",
    )


def rag_answer_tool(context: dict[str, Any]) -> ToolExecutionResult:
    retrieved_chunks = context["retrieved_chunks"]
    result = answer_from_retrieved(context["question"], retrieved_chunks)
    sources = [_source_view(item) for item in result.get("sources", [])]
    return ToolExecutionResult(
        updates={
            "answer": result.get("answer", ""),
            "sources": sources,
            "phase": "answered",
            "final_outcome": "answered",
        },
        output_summary=f"generated answer with {len(sources)} sources",
    )


def rag_no_answer_tool(context: dict[str, Any]) -> ToolExecutionResult:
    assessment = context.get("evidence_assessment")
    assessment_failed = (
        isinstance(assessment, EvidenceAssessment) and assessment.verdict == "error"
    )
    answer = ASSESSMENT_UNAVAILABLE_ANSWER if assessment_failed else DEFAULT_NO_ANSWER
    final_outcome = "error" if assessment_failed else "grounded_no_answer"
    return ToolExecutionResult(
        updates={
            "answer": answer,
            "sources": [],
            "phase": "no_answer",
            "final_outcome": final_outcome,
        },
        output_summary=(
            "returned assessment-unavailable answer"
            if assessment_failed
            else "returned grounded no-answer"
        ),
    )


def guardrail_check_tool(context: dict[str, Any]) -> ToolExecutionResult:
    answer = context.get("answer", "")
    if unsafe_answer(answer):
        return ToolExecutionResult(
            updates={
                "answer": DEFAULT_REFUSAL_ANSWER,
                "sources": [],
                "guardrail_blocked": True,
                "phase": "guarded",
                "final_outcome": "refused",
            },
            output_summary="blocked unsafe answer",
        )
    return ToolExecutionResult(
        updates={"guardrail_blocked": False, "phase": "guarded"},
        output_summary="answer allowed",
    )


def guardrail_refuse_tool(context: dict[str, Any]) -> ToolExecutionResult:
    return ToolExecutionResult(
        updates={
            "answer": DEFAULT_REFUSAL_ANSWER,
            "sources": [],
            "guardrail_blocked": True,
            "phase": "refused",
            "final_outcome": "refused",
        },
        output_summary="refused unsafe request",
    )


def build_default_registry(
    assessor: EvidenceAssessor | None = None,
) -> ToolRegistry:
    assessor = assessor or LocalEvidenceAssessor()
    registry = ToolRegistry()
    registry.register("retrieval.search", retrieval_search_tool)
    registry.register("evidence.assess", make_evidence_assess_tool(assessor))
    registry.register("query.rewrite", query_rewrite_tool)
    registry.register("rag.answer", rag_answer_tool)
    registry.register("rag.no_answer", rag_no_answer_tool)
    registry.register("guardrail.check", guardrail_check_tool)
    registry.register("guardrail.refuse", guardrail_refuse_tool)
    return registry
