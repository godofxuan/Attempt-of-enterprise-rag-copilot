from __future__ import annotations

from app.corpus.schemas import EvalCase, EvalUserContext
from app.evaluation.contracts import (
    EvaluationCaseResult,
    FailureSignal,
    LayerResult,
)
from app.evaluation.human_review import (
    HUMAN_JUDGEMENT_FIELDS,
    build_human_review_rows,
)


TASK_TYPES = [
    "fact_lookup",
    "version_conflict",
    "completeness",
    "comparison",
    "no_answer",
    "permission",
]


def eval_case(index: int) -> EvalCase:
    task = TASK_TYPES[index % len(TASK_TYPES)]
    answer_mode = "permission" if task == "permission" else "not_found" if task == "no_answer" else "answered"
    return EvalCase(
        case_id=f"case-{index:03d}",
        question=f"Review question {index}",
        task_type=task,
        answer_mode=answer_mode,
        user_context=EvalUserContext(
            user_id="reviewer",
            tenant="tenant-one",
            region="cn",
            groups=["employees"],
        ),
        required_fact_ids=[] if answer_mode != "answered" else [f"fact-{index}"],
        gold_doc_ids=[] if answer_mode != "answered" else [f"doc-{index}"],
        distractor_doc_ids=[],
        forbidden_doc_ids=[f"hidden-{index}"] if task == "permission" else [],
        expected_answer=None if answer_mode != "answered" else f"answer-{index}",
        expected_filters={},
        expected_authority_doc_ids=[] if answer_mode != "answered" else [f"doc-{index}"],
        tags=[task],
    )


def case_result(case: EvalCase, *, passed: bool) -> EvaluationCaseResult:
    failures = [] if passed else [
        FailureSignal(
            stage="retrieval",
            code="gold_missing",
            message="Gold document missing.",
        )
    ]
    layer = LayerResult(
        layer="retrieval",
        applicable=True,
        passed=passed,
        metrics={},
        failures=failures,
    )
    return EvaluationCaseResult(
        case_id=case.case_id,
        task_type=case.task_type,
        expected_mode=case.answer_mode,
        actual_mode=case.answer_mode if passed else "not_found",
        passed=passed,
        visible_doc_ids=case.gold_doc_ids,
        layers=[layer],
        primary_failure=None if passed else "retrieval",
        latency_ms=1.0,
        model_calls=0,
        tool_calls=1,
        context_chars=100,
    )


def test_human_review_selects_at_most_fifty_and_keeps_judgements_blank() -> None:
    cases = [eval_case(index) for index in range(60)]
    results = [case_result(case, passed=index >= 10) for index, case in enumerate(cases)]
    answers = {case.case_id: f"System answer for {case.case_id}" for case in cases}

    rows = build_human_review_rows(cases, results, answers)

    assert len(rows) == 50
    assert {row["task_type"] for row in rows} == set(TASK_TYPES)
    assert all(row[field] == "" for row in rows for field in HUMAN_JUDGEMENT_FIELDS)
    assert all(row["system_answer"] for row in rows)
    assert all("hidden-" not in row["visible_source_doc_ids"] for row in rows)


def test_human_review_prioritizes_failures_before_passing_fillers() -> None:
    cases = [eval_case(index) for index in range(40)]
    results = [case_result(case, passed=index >= 5) for index, case in enumerate(cases)]

    rows = build_human_review_rows(cases, results, {})

    selected_ids = [row["case_id"] for row in rows]
    for index in range(5):
        assert f"case-{index:03d}" in selected_ids[:10]


def test_human_review_uses_all_cases_when_fewer_than_thirty_exist() -> None:
    cases = [eval_case(index) for index in range(8)]
    results = [case_result(case, passed=True) for case in cases]

    rows = build_human_review_rows(cases, results, {})

    assert len(rows) == 8
