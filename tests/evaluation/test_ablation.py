from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from app.corpus.schemas import EvalCase, EvalUserContext
from app.domain.agent import AgentBudget
from app.domain.evidence import AnswerResponse, AnswerSource, Claim, ClaimCitation
from app.evaluation.ablation import run_ablation
from tests.v2_test_support import search_hit, search_result


def eval_case(**updates) -> EvalCase:
    values = {
        "case_id": "case-one",
        "question": "Policy A 的规则是什么？",
        "task_type": "fact_lookup",
        "answer_mode": "answered",
        "user_context": EvalUserContext(
            user_id="employee-one",
            tenant="tenant-one",
            region="cn",
            groups=["employees"],
        ),
        "required_fact_ids": ["fact-a"],
        "gold_doc_ids": ["doc-a"],
        "distractor_doc_ids": [],
        "forbidden_doc_ids": [],
        "expected_answer": "3 days",
        "expected_filters": {},
        "expected_authority_doc_ids": ["doc-a"],
        "tags": ["current"],
    }
    values.update(updates)
    return EvalCase(**values)


@dataclass
class FakeCounters:
    embedding_calls: int = 0
    generation_calls: int = 0

    @property
    def model_calls(self) -> int:
        return self.embedding_calls + self.generation_calls


class RecordingPipeline:
    def __init__(self, result) -> None:
        self.result = result
        self.requests = []

    def search(self, request):
        self.requests.append(request)
        return self.result


class StaticRunner:
    def __init__(self, response: AnswerResponse) -> None:
        self.response = response
        self.calls = []

    def run(self, question, user, top_k=None):
        self.calls.append((question, user, top_k))
        return self.response


def answered_response() -> AnswerResponse:
    budget = {
        "search_calls": 1,
        "find_calls": 0,
        "open_calls": 0,
        "steps": 1,
        "context_chars": 100,
    }
    return AnswerResponse(
        mode="answered",
        answer="Policy A allows 3 days.",
        claims=[Claim(claim_id="c1", text="3 days", cited_chunk_ids=["chunk-a"])],
        citations=[
            ClaimCitation(
                claim_id="c1",
                cited_chunk_ids=["chunk-a"],
                citation_present=True,
                references_visible_evidence=True,
                lexical_support=1.0,
                supported=True,
            )
        ],
        sources=[
            AnswerSource(
                doc_id="doc-a",
                source_path="documents/doc-a.md",
                section_path=["Policy"],
                chunk_id="chunk-a",
                preview="3 days",
            )
        ],
        stop_reason="completed",
        trace={"budget": budget},
    )


def fake_runtime(response: AnswerResponse | None = None):
    hit = search_hit(chunk_id="chunk-a", doc_id="doc-a", fact_ids=["fact-a"])
    pipeline = RecordingPipeline(search_result([hit]))
    return SimpleNamespace(
        mode="deterministic",
        pipeline=pipeline,
        runner=StaticRunner(response or answered_response()),
        budget=AgentBudget(),
        counters=FakeCounters(),
        snapshot=SimpleNamespace(all_chunks_by_id={"chunk-a": hit}),
    )


def test_ablation_uses_same_pipeline_with_request_level_variants() -> None:
    runtime = fake_runtime()
    result = run_ablation([eval_case()], runtime, top_k=5, candidate_k=20)

    assert [row.variant for row in result.rows] == [
        "bm25",
        "dense",
        "hybrid_rrf",
        "hybrid_metadata_temporal",
        "hybrid_diversity_parent",
        "hybrid_optional_reranker",
        "fixed_rag",
        "bounded_agentic_retrieval",
    ]
    assert len(runtime.pipeline.requests) == 6
    assert [request.mode for request in runtime.pipeline.requests[:5]] == [
        "bm25",
        "dense",
        "hybrid",
        "hybrid",
        "hybrid",
    ]
    assert runtime.pipeline.requests[0].include_parent is False
    assert runtime.pipeline.requests[3].filters.temporal_scope == "current"
    assert runtime.pipeline.requests[4].include_parent is True
    assert runtime.pipeline.requests[4].max_chunks_per_doc == 2
    assert all(request.user.tenant_id == "tenant-one" for request in runtime.pipeline.requests)
    reranker = result.rows[5]
    assert reranker.status == "not_run"
    assert reranker.reason == "no_admitted_reranker"
    assert reranker.metrics == {}
    assert all(row.case_count == 1 for row in result.rows if row.status == "completed")


def test_fixed_rag_and_bounded_agent_score_outcomes_without_using_gold_to_predict() -> None:
    no_answer = eval_case(
        task_type="no_answer",
        answer_mode="not_found",
        required_fact_ids=[],
        gold_doc_ids=[],
        expected_answer=None,
        expected_authority_doc_ids=[],
        tags=["no_answer"],
    )
    runtime = fake_runtime(
        AnswerResponse(
            mode="not_found",
            answer="No supported answer is available.",
            stop_reason="not_found",
            trace={
                "budget": {
                    "search_calls": 1,
                    "find_calls": 0,
                    "open_calls": 0,
                    "steps": 1,
                    "context_chars": 0,
                }
            },
        )
    )

    result = run_ablation([no_answer], runtime)
    rows = {row.variant: row for row in result.rows}

    assert rows["fixed_rag"].metrics["outcome_accuracy"] == 0.0
    assert rows["bounded_agentic_retrieval"].metrics["outcome_accuracy"] == 1.0
    assert result.failure_case_ids["fixed_rag"] == ["case-one"]
    assert result.failure_case_ids["bounded_agentic_retrieval"] == []


def test_ablation_records_quality_latency_calls_and_context() -> None:
    result = run_ablation([eval_case()], fake_runtime())

    for row in result.rows:
        if row.status != "completed":
            continue
        assert "outcome_accuracy" in row.metrics or "document_recall@5" in row.metrics
        assert row.latency_ms_avg is not None
        assert row.model_calls == 0
        assert row.tool_calls >= 1
        assert row.context_chars >= 0
