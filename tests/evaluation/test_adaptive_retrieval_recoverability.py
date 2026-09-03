from app.evaluation.adaptive_retrieval_recoverability import (
    RecoverabilityProposal,
    classify_recovery,
    parse_assessor_response,
    validate_query_addendum,
)


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
