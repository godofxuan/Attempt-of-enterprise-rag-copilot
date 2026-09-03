from pathlib import Path

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


def test_runtime_modules_do_not_reference_evaluation_gold_labels() -> None:
    app_root = Path(__file__).resolve().parents[2] / "app"
    runtime_paths = [app_root / "agent", app_root / "agent_runtime"]
    for runtime_path in runtime_paths:
        for source_path in runtime_path.rglob("*.py"):
            assert "gold_document_ids" not in source_path.read_text(encoding="utf-8"), source_path
