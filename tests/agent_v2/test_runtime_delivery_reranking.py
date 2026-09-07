import pytest

from app.agent.tools_v2 import V2ToolRegistry
from app.domain.agent import AgentBudget, BudgetState
from app.security.reranking_admission import RerankingContentAdmission as RetrievedContentAdmission
from tests.agent_v2.test_tools_v2 import search_action
from tests.security.test_retrieved_admission import _pool
from tests.v2_test_support import search_hit


@pytest.mark.parametrize("depth", [20, 50])
def test_server_profile_limits_raw_candidates_before_admission(depth):
    seen = []

    class Navigator:
        def search_ranked(self, request):
            assert request.mode == "dense"
            assert request.candidate_k == 200
            assert request.max_chunks_per_doc == 1
            return _pool(*(search_hit(chunk_id=str(i), doc_id=f"doc-{i}") for i in range(60)))

    def scorer(query, texts):
        seen.extend(texts)
        return list(range(len(texts)))

    registry = V2ToolRegistry(
        Navigator(),
        clock_ms=lambda: 1,
        admission=RetrievedContentAdmission(search_scorer=scorer),
        retrieval_profile=f"safe_dense_raw{depth}_bge",
    )
    action = search_action()
    execution = registry.run(action, BudgetState(deadline_at_ms=1000))
    assert execution.status == "ok"
    assert len(seen) == depth
    assert execution.result.hits[0].hit.chunk_id == str(depth - 1)
    assert execution.security_counters.candidate_count == depth
    assert action.search_request.mode == "bm25"
    from app.agent.runner_v2 import _tool_step_trace

    trace = _tool_step_trace(execution, latency_ms=1)
    assert trace["retrieval_counts"]["reranker_scored"] == depth
    assert "matched_text" not in str(trace)


def test_profile_cannot_silently_run_without_scorer():
    with pytest.raises(ValueError, match="requires"):
        V2ToolRegistry(object(), retrieval_profile="safe_dense_raw20_bge")


def test_model_failure_does_not_return_unchecked_evidence():
    class Navigator:
        def search_ranked(self, request):
            return _pool(search_hit())

    def scorer(query, texts):
        raise RuntimeError("private model error")

    registry = V2ToolRegistry(
        Navigator(),
        clock_ms=lambda: 1,
        admission=RetrievedContentAdmission(search_scorer=scorer),
        retrieval_profile="safe_dense_raw20_bge",
    )
    execution = registry.run(search_action(), BudgetState(deadline_at_ms=1000))
    assert execution.status == "error"
    assert execution.visible_count == 0
    assert "private model error" not in execution.model_dump_json()


def test_identical_matched_and_context_text_are_charged_once():
    text = "The policy is effective. " * 100

    class Navigator:
        def search_ranked(self, request):
            return _pool(search_hit(matched_text=text, context_text=text))

    execution = V2ToolRegistry(Navigator(), clock_ms=lambda: 1).run(
        search_action(), BudgetState(budget=AgentBudget(max_context_chars=3000))
    )
    assert execution.status == "ok"
    assert len(text) <= execution.context_chars_added < 3000


def test_completed_inference_after_deadline_is_not_published():
    now = [1]

    class Navigator:
        def search_ranked(self, request):
            return _pool(search_hit())

    def scorer(query, texts):
        now[0] = 2000
        return [1.0] * len(texts)

    registry = V2ToolRegistry(
        Navigator(),
        clock_ms=lambda: now[0],
        admission=RetrievedContentAdmission(search_scorer=scorer),
        retrieval_profile="safe_dense_raw20_bge",
    )
    execution = registry.run(search_action(), BudgetState(deadline_at_ms=1000))
    assert execution.status == "error"
    assert execution.result.code == "timeout"
    assert execution.visible_count == 0
    assert execution.context_chars_added == 0
    assert execution.security_counters.post_guard_evidence_count == 0


@pytest.mark.parametrize(
    "failure,reason",
    [
        (TimeoutError("private capacity details"), "capacity_timeout"),
        (MemoryError("private allocation details"), "out_of_memory"),
        (FileNotFoundError("private model path"), "model_unavailable"),
        (RuntimeError("private inference details"), "inference_failure"),
    ],
)
def test_scorer_failures_have_bounded_diagnostic_codes(failure, reason):
    from app.agent.runner_v2 import _tool_step_trace

    class Navigator:
        def search_ranked(self, request):
            return _pool(search_hit())

    def scorer(query, texts):
        raise failure

    result = V2ToolRegistry(
        Navigator(),
        clock_ms=lambda: 1,
        admission=RetrievedContentAdmission(search_scorer=scorer),
        retrieval_profile="safe_dense_raw20_bge",
    ).run(search_action(), BudgetState(deadline_at_ms=1000))
    trace = _tool_step_trace(result, latency_ms=1)
    assert trace["reranker_failure_reason"] == reason
    assert result.visible_count == 0
    assert "private" not in result.model_dump_json()
