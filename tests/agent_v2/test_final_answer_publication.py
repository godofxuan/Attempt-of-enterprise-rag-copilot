"""Final response regressions, not a new model quality benchmark."""

import pytest

from app.agent.task_plan import RequestNeed, TaskPlan
from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.retrieval import conftest as retrieval_fixtures
from tests.v2_test_support import user_context

chunk_factory = retrieval_fixtures.chunk_factory
document_factory = retrieval_fixtures.document_factory
snapshot_factory = retrieval_fixtures.snapshot_factory


def test_question_echo_is_not_released_as_a_supported_fact(
    snapshot_factory, document_factory, chunk_factory
):
    question = "设备借用流程如何办理？"
    runner, _ = runner_fixture(
        snapshot_factory,
        document_factory,
        chunk_factory,
        texts=[question + "设备借用需登记用途。"],
        claim=question,
    )
    response = runner.run(question, user_context())
    assert all(c.text != question for c in response.claims)
    assert response.trace["request_echo_claims_omitted"] == 1
    assert response.trace["final_mode"] == response.mode


def test_partial_response_still_explains_missing_model_need(
    snapshot_factory, document_factory, chunk_factory
):
    question = "设备借用流程如何办理？"
    missing = "遗失设备如何赔偿"
    runner, _ = runner_fixture(
        snapshot_factory,
        document_factory,
        chunk_factory,
        texts=["设备借用需登记用途。"],
        claim="设备借用需登记用途。",
    )
    original = runner.response_builder._apply_answer_contract

    def force_existing_partial(q, state, response, sources):
        state.task_plan = TaskPlan(
            needs=(
                RequestNeed(
                    need_id="N1",
                    text=missing,
                    kind="model",
                    clarification_needed=True,
                ),
            )
        )
        response = response.model_copy(
            update={"mode": "partial", "stop_reason": "partial_evidence"}
        )
        return original(q, state, response, sources)

    runner.response_builder._apply_answer_contract = force_existing_partial
    response = runner.run(question, user_context())
    assert response.mode == "partial"
    assert missing in response.answer
    assert response.trace["task_coverage"]["answer_missing"] == 1


def test_complete_multineed_response_has_one_final_decision(
    snapshot_factory, document_factory, chunk_factory
):
    text = "入职需要身份证。入职试用期为三个月。"
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text
    )
    response = runner.run("入职需要哪些材料，试用期多久？", user_context())
    assert response.mode == "answered"
    decision = response.trace["answer_decision"]
    assert decision["version"] == "answer-publication-v1"
    assert decision["final_mode"] == response.mode
    assert decision["requirement_counts"]["supported_and_stated"] == 2
    assert decision["publication_count"] == 1
    assert all(c.supported for c in response.citations)


@pytest.mark.parametrize("change", ["not_delivered", "wrong_version", "wrong_claim_citation"])
def test_publisher_rejects_cross_bound_identity(
    change, snapshot_factory, document_factory, chunk_factory
):
    text = "入职需要身份证。"
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text
    )
    original = runner.response_builder._apply_answer_contract

    def corrupt(q, state, response, sources):
        if change == "not_delivered":
            sources = []
        elif change == "wrong_version":
            response = response.model_copy(
                update={
                    "sources": [
                        s.model_copy(update={"version_id": "wrong@version"})
                        for s in response.sources
                    ]
                }
            )
        else:
            response = response.model_copy(
                update={
                    "citations": [
                        c.model_copy(update={"cited_chunk_ids": ["wrong-id"]})
                        for c in response.citations
                    ]
                }
            )
        return original(q, state, response, sources)

    runner.response_builder._apply_answer_contract = corrupt
    response = runner.run("入职需要哪些材料？", user_context())
    assert response.mode != "answered"
    assert not response.claims and not response.sources
    assert response.trace["delivery_binding_dropped_claims"] == 1


@pytest.mark.parametrize(
    "status",
    [
        "not_retrieved",
        "retrieved_but_not_delivered",
        "evidence_insufficient",
        "supported_and_stated",
        "conflicted",
    ],
)
def test_requirement_statuses_are_distinct(status):
    from types import SimpleNamespace

    from app.agent.answer_publication import _requirements

    original = RequestNeed(
        need_id="N1",
        text="what",
        kind="whole",
        evidence_ids=("E1",) if status != "not_retrieved" else (),
    )
    delivered = original.model_copy(
        update={
            "evidence_ids": ("E1",)
            if status in {"evidence_insufficient", "supported_and_stated"}
            else (),
            "answer_claim_ids": ("C1",) if status == "supported_and_stated" else (),
        }
    )
    state = SimpleNamespace(
        task_plan=TaskPlan(needs=(original,)),
        ledger=SimpleNamespace(conflicting_aspects=["answer"] if status == "conflicted" else []),
    )
    result = _requirements(state, TaskPlan(needs=(delivered,)))
    assert result[0].status == status
