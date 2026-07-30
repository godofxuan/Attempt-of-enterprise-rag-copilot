from __future__ import annotations

import pytest

from app.external_datasets.finqa_numeric_evidence_shortlist_v2 import (
    MAX_INPUT_CANDIDATES,
    MAX_OUTPUT_CANDIDATES,
    question_conditioned_numeric_evidence_shortlist_v2,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_typed_program import (
    extract_numeric_candidates,
)


def _candidates(count: int):
    result = []
    for index in range(count):
        result.extend(
            extract_numeric_candidates(
                source_id="report.pdf",
                evidence_id=f"table_{index // 4}",
                text=str(index + 2),
                kind="table_cell",
                table_id="table-main",
                row_header="Revenue",
                column_header="2020",
            )
        )
    return tuple(result)


def test_shortlist_accepts_frozen_128_input_budget_and_returns_24():
    candidates = _candidates(MAX_INPUT_CANDIDATES)
    evidence_ids = {candidate.evidence_id for candidate in candidates}

    result = question_conditioned_numeric_evidence_shortlist_v2(
        question="What was 2020 revenue?",
        candidates=candidates,
        admitted_evidence_ids=evidence_ids,
        intent=extract_financial_question_intent_v2(
            "What was 2020 revenue?"
        ),
    )

    assert len(result) == MAX_OUTPUT_CANDIDATES
    assert len({item.candidate_id for item in result}) == len(result)


def test_shortlist_fails_closed_above_frozen_input_budget():
    candidates = _candidates(MAX_INPUT_CANDIDATES + 1)
    evidence_ids = {candidate.evidence_id for candidate in candidates}

    with pytest.raises(
        ValueError,
        match="numeric evidence candidate budget exceeded",
    ):
        question_conditioned_numeric_evidence_shortlist_v2(
            question="What was 2020 revenue?",
            candidates=candidates,
            admitted_evidence_ids=evidence_ids,
            intent=extract_financial_question_intent_v2(
                "What was 2020 revenue?"
            ),
        )
