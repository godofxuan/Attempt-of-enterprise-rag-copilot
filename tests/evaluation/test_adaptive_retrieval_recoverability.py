from app.evaluation.adaptive_retrieval_recoverability import (
    RecoverabilityProposal,
    build_assessor_messages,
    build_assessor_request_fingerprints,
    classify_recovery,
    parse_assessor_response,
    validate_query_addendum,
)
from scripts.diagnose_adaptive_retrieval_recoverability import _assessor_seed


def test_sufficient_proposal_cannot_request_retry() -> None:
    try:
        RecoverabilityProposal(
            verdict="sufficient",
            reason_code="all_aspects_supported",
            query_addendum="extra term",
        )
    except ValueError as error:
        assert "must not propose" in str(error)
    else:
        raise AssertionError("invalid sufficient proposal was accepted")


def test_insufficient_proposal_cannot_claim_all_aspects_supported() -> None:
    try:
        RecoverabilityProposal(
            verdict="insufficient",
            reason_code="all_aspects_supported",
        )
    except ValueError as error:
        assert "require an insufficiency" in str(error)
    else:
        raise AssertionError("invalid insufficient proposal was accepted")


def test_addendum_is_appended_and_duplicate_queries_are_rejected() -> None:
    accepted = validate_query_addendum(
        original_query="expense policy",
        addendum="  reimbursement   receipt ",
        attempted_queries=["expense policy"],
    )
    assert accepted.accepted is True
    assert accepted.query == "expense policy reimbursement receipt"

    rejected = validate_query_addendum(
        original_query="expense policy",
        addendum="reimbursement receipt",
        attempted_queries=["expense policy reimbursement receipt"],
    )
    assert rejected.accepted is False
    assert rejected.rejection_reason == "duplicate_query"


def test_control_characters_are_rejected_without_repair() -> None:
    result = validate_query_addendum(
        original_query="expense policy",
        addendum="receipt\npolicy",
        attempted_queries=[],
    )
    assert result.accepted is False
    assert result.rejection_reason == "control_character"


def test_invalid_model_json_fails_closed() -> None:
    assert parse_assessor_response("not-json").status == "parse_error"


def test_recovery_metrics_keep_union_gain_separate_from_rank_churn() -> None:
    result = classify_recovery(
        baseline_gold_recall=0.5,
        retry_gold_recall=0.0,
        union_gold_recall=0.5,
    )
    assert result == {
        "retry_improved": False,
        "retry_fully_recovered": False,
        "retry_no_change": True,
        "retry_worse": True,
    }


def test_question_seed_is_stable_and_independent_of_python_hash_randomization() -> None:
    assert _assessor_seed("wixqa:expertwritten:a") == _assessor_seed(
        "wixqa:expertwritten:a"
    )
    assert _assessor_seed("wixqa:expertwritten:a") != _assessor_seed(
        "wixqa:expertwritten:b"
    )


def test_assessor_message_builder_returns_the_complete_structured_request() -> None:
    messages = build_assessor_messages(
        original_question="What changed?",
        retrieval_query="What changed?",
        intent="fact",
        required_aspects=["answer"],
        evidence=[{"document_id": "doc-1", "title": "Title", "text": "Body"}],
    )

    assert [item["role"] for item in messages] == ["system", "user"]
    assert "assessment_input" in messages[1]["content"]


def test_request_fingerprint_changes_when_material_request_configuration_changes() -> None:
    common = {
        "model_name": "qwen3:8b",
        "model_digest": "a" * 64,
        "messages": [{"role": "user", "content": "test"}],
        "schema": {"type": "object"},
        "temperature": 0.0,
        "think": False,
        "max_output_tokens": 160,
        "timeout_seconds": 30.0,
    }
    first = build_assessor_request_fingerprints(seed=1, **common)
    same = build_assessor_request_fingerprints(seed=1, **common)
    changed = build_assessor_request_fingerprints(seed=2, **common)

    assert first == same
    assert first["request_sha256"] != changed["request_sha256"]
    assert first["input_messages_sha256"] == changed["input_messages_sha256"]
