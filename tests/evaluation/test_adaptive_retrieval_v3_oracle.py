from app.evaluation.adaptive_retrieval_v3 import select_oracle_case_ids


def test_oracle_membership_depends_only_on_first_pass_evidence() -> None:
    first_pass = [
        {
            "question_id": "complete",
            "gold_document_ids": ["a"],
            "post_guard_document_ids": ["a"],
        },
        {
            "question_id": "miss",
            "gold_document_ids": ["a", "b"],
            "post_guard_document_ids": ["a"],
        },
    ]
    assert select_oracle_case_ids(first_pass) == ("miss",)


def test_oracle_selection_has_no_corrective_arm_parameter() -> None:
    assert "s4" not in select_oracle_case_ids.__code__.co_varnames
