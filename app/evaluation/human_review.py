from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from typing import Any

from app.corpus.schemas import EvalCase
from app.evaluation.contracts import EvaluationCaseResult


HUMAN_JUDGEMENT_FIELDS: tuple[str, ...] = (
    "答案是否正确",
    "是否完整",
    "引用是否支持",
    "是否应重写",
    "是否应拒答",
    "是否越权",
    "主要失败阶段",
    "本人说明",
)


def build_human_review_rows(
    cases: Sequence[EvalCase],
    results: Sequence[EvaluationCaseResult],
    answer_by_case: Mapping[str, str],
    *,
    min_rows: int = 30,
    max_rows: int = 50,
) -> list[dict[str, Any]]:
    if min_rows < 1 or max_rows < min_rows:
        raise ValueError("human review row bounds are invalid")
    by_result = {result.case_id: result for result in results}
    if len(by_result) != len(results):
        raise ValueError("human review result case IDs must be unique")
    missing = [case.case_id for case in cases if case.case_id not in by_result]
    if missing:
        raise ValueError("human review is missing machine results")
    target = min(max_rows, len(cases))
    selected = _select_cases(cases, by_result, target)
    rows: list[dict[str, Any]] = []
    for case in selected:
        result = by_result[case.case_id]
        row: dict[str, Any] = {
            "case_id": case.case_id,
            "task_type": case.task_type,
            "question": case.question,
            "expected_mode": case.answer_mode,
            "actual_mode": result.actual_mode,
            "system_answer": answer_by_case.get(case.case_id, ""),
            "visible_source_doc_ids": ";".join(result.visible_doc_ids),
        }
        row.update({field: "" for field in HUMAN_JUDGEMENT_FIELDS})
        rows.append(row)
    return rows


def _select_cases(
    cases: Sequence[EvalCase],
    by_result: Mapping[str, EvaluationCaseResult],
    target: int,
) -> list[EvalCase]:
    failed = sorted(
        (case for case in cases if not by_result[case.case_id].passed),
        key=lambda case: case.case_id,
    )
    selected = failed[:target]
    selected_ids = {case.case_id for case in selected}
    if len(selected) == target:
        return selected

    groups: dict[str, deque[EvalCase]] = defaultdict(deque)
    for case in sorted(cases, key=lambda item: (item.task_type, item.case_id)):
        if case.case_id not in selected_ids:
            groups[case.task_type].append(case)
    task_types = sorted(groups)
    while len(selected) < target and task_types:
        remaining: list[str] = []
        for task_type in task_types:
            group = groups[task_type]
            if group and len(selected) < target:
                case = group.popleft()
                selected.append(case)
                selected_ids.add(case.case_id)
            if group:
                remaining.append(task_type)
        task_types = remaining
    return selected


__all__ = ["HUMAN_JUDGEMENT_FIELDS", "build_human_review_rows"]
