from __future__ import annotations

import pytest

from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.agent.runner_v2 import V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from tests.v2_test_support import RecordingNavigator, search_hit, search_result, user_context


def run_pair(first, second, *, generated=False):
    def forbidden_model(*args, **kwargs):
        pytest.fail("unresolved conflict must not invoke the generation model")

    navigator = RecordingNavigator(search_results=[search_result([first, second])])
    return V2AgentRunner(
        registry=V2ToolRegistry(navigator, clock_ms=lambda: 0.0),
        response_builder=GenerationV2ResponseBuilder(
            chat_fn=forbidden_model,
            model="fixture",
            max_attempts=1,
        )
        if generated
        else None,
        clock_ms=lambda: 0.0,
    ).run("How many days does the refund policy allow?", user_context())


def pair(second_text="Refunds arrive in 30 days.", **updates):
    return (
        search_hit(
            matched_text="Refunds arrive in 7 days.", context_text="Refunds arrive in 7 days."
        ),
        search_hit(
            chunk_id="chunk-b", matched_text=second_text, context_text=second_text, **updates
        ),
    )


@pytest.mark.parametrize("generated", [False, True])
def test_equal_scope_active_numeric_conflict_does_not_publish_a_chosen_winner(generated):
    response = run_pair(*pair(), generated=generated)
    assert response.mode == "partial"
    assert response.trace["evidence"]["conflicting"] == 1
    assert "7 days" in response.answer and "30 days" in response.answer
    assert len(response.sources) == 2
    assert any("conflict" in warning.casefold() for warning in response.warnings)


@pytest.mark.parametrize(
    "second_text",
    [
        "Refunds arrive in 7.0 days.",
        "Refunds arrive in 30 days for overseas orders.",
        "Refunds are archived for 30 days.",
    ],
)
def test_same_value_or_different_explicit_scope_is_not_an_automatic_conflict(second_text):
    response = run_pair(*pair(second_text))
    assert response.trace["evidence"]["conflicting"] == 0


def test_unrelated_high_authority_hit_does_not_resolve_a_numeric_conflict():
    from app.agent.evidence_ledger import build_ledger
    from tests.agent_v2.test_generation_v2 import state_with_evidence
    from tests.v2_test_support import admit_search_hit

    first, second = pair()
    values = [
        admit_search_hit(item.model_copy(update={"authority_level": 80}))
        for item in (first, second)
    ]
    values.append(
        admit_search_hit(
            search_hit(
                chunk_id="unrelated-high",
                authority_level=100,
                matched_text="Refund support is available through the help desk.",
                context_text="Refund support is available through the help desk.",
            )
        )
    )
    ledger = build_ledger(state_with_evidence().analysis, {"answer": values})
    assert ledger.conflicting_aspects == ["answer"]


def test_distinct_documents_in_same_policy_revision_are_compared():
    first, second = pair(doc_id="doc-b", version_id="doc-b@2026", version="2026")
    first = first.model_copy(update={"version_id": "doc-a@2026"})
    response = run_pair(first, second, generated=True)
    assert response.mode == "partial"
    assert response.trace["evidence"]["conflicting"] == 1


def test_distinct_policy_revision_is_not_automatically_compared():
    response = run_pair(*pair(doc_id="doc-b", version_id="doc-b@2027", version="2027"))
    assert response.trace["evidence"]["conflicting"] == 0
