from __future__ import annotations

from app.external_datasets.finqa_descriptor_candidate_reranker_v1 import (
    rerank_descriptor_candidates_v1,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    build_retrievable_safe_descriptor_catalog_v3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.security.retrieved_content import RetrievedContentGuard


def _skeleton(
    left_period: str = "none",
    right_period: str = "none",
) -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "comparison_left",
                    "period_role": left_period,
                },
                {
                    "role_id": "role-02",
                    "semantic_role": "comparison_right",
                    "period_role": right_period,
                },
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "SUB",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"role_id": "role-02"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )


def _candidate(index: int, row: str, year: str):
    return extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id=f"table_{index}",
        text=str(100 + index),
        kind="table_cell",
        table_id="facts",
        row_header=row,
        column_header=year,
    )[0]


def test_round_robin_prevents_early_broad_descriptors_from_crowding() -> None:
    rows = ("revenue", "assets", "inventory", "tax benefits")
    candidates = tuple(
        _candidate(index, row, year)
        for index, (row, year) in enumerate(
            (
                (row, year)
                for row in rows
                for year in ("2015", "2016", "2017")
            ),
            start=1,
        )
    )
    contexts = {
        item.evidence_id: (
            f"{item.row_header} | {item.column_header} | {item.raw_text}"
        )
        for item in candidates
    }
    build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids=set(contexts),
        evidence_context_by_id=contexts,
        guard=RetrievedContentGuard(),
    )
    descriptor_by_metric = {
        item.metric: item.descriptor_id for item in build.catalog.descriptors
    }
    selected = tuple(descriptor_by_metric[row] for row in rows)

    result = rerank_descriptor_candidates_v1(
        question="What was the difference between revenue and tax benefits?",
        role=_skeleton().roles[0],
        skeleton=_skeleton(),
        selected_descriptor_ids=selected,
        catalog_build=build,
        candidates=candidates,
        intent=extract_financial_question_intent_v2(
            "What was the difference between revenue and tax benefits?"
        ),
        evidence_context_by_id=contexts,
    )

    assert {
        item.descriptor_id for item in result.ranked_candidates
    } == set(selected)
    assert len(result.ranked_candidates) == 8


def test_exact_period_wins_inside_selected_descriptor() -> None:
    question = "What was the change in revenue from 2016 to 2017?"
    candidates = (
        _candidate(1, "revenue", "2015"),
        _candidate(2, "revenue", "2016"),
        _candidate(3, "revenue", "2017"),
    )
    contexts = {
        item.evidence_id: (
            f"{item.row_header} | {item.column_header} | {item.raw_text}"
        )
        for item in candidates
    }
    build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids=set(contexts),
        evidence_context_by_id=contexts,
        guard=RetrievedContentGuard(),
    )
    skeleton = _skeleton("start", "end")

    result = rerank_descriptor_candidates_v1(
        question=question,
        role=skeleton.roles[0],
        skeleton=skeleton,
        selected_descriptor_ids=(build.catalog.descriptors[0].descriptor_id,),
        catalog_build=build,
        candidates=candidates,
        intent=extract_financial_question_intent_v2(question),
        evidence_context_by_id=contexts,
    )

    expected = next(item for item in candidates if item.column_header == "2016")
    assert result.ranked_candidates[0].candidate_id == expected.candidate_id
    assert "exact_period" in result.ranked_candidates[0].score_reasons


def test_reranker_is_candidate_and_context_order_invariant() -> None:
    question = "What was the difference between revenue and tax benefits?"
    candidates = tuple(
        _candidate(index, row, year)
        for index, (row, year) in enumerate(
            (
                (row, year)
                for row in ("revenue", "assets", "tax benefits")
                for year in ("2016", "2017")
            ),
            start=1,
        )
    )
    contexts = {
        item.evidence_id: (
            f"{item.row_header} | {item.column_header} | {item.raw_text}"
        )
        for item in candidates
    }
    kwargs = {
        "admitted_evidence_ids": set(contexts),
        "guard": RetrievedContentGuard(),
    }
    forward_build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        evidence_context_by_id=contexts,
        **kwargs,
    )
    reverse_contexts = dict(reversed(tuple(contexts.items())))
    reverse_build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=tuple(reversed(candidates)),
        evidence_context_by_id=reverse_contexts,
        **kwargs,
    )
    selected = tuple(
        item.descriptor_id for item in forward_build.catalog.descriptors
    )
    skeleton = _skeleton()
    common = {
        "question": question,
        "role": skeleton.roles[0],
        "skeleton": skeleton,
        "selected_descriptor_ids": selected,
        "intent": extract_financial_question_intent_v2(question),
    }

    forward = rerank_descriptor_candidates_v1(
        catalog_build=forward_build,
        candidates=candidates,
        evidence_context_by_id=contexts,
        **common,
    )
    reverse = rerank_descriptor_candidates_v1(
        catalog_build=reverse_build,
        candidates=tuple(reversed(candidates)),
        evidence_context_by_id=reverse_contexts,
        **common,
    )

    assert forward == reverse


def test_reranker_returns_structured_empty_result_when_all_are_incompatible() -> None:
    question = "What was the change in revenue from 2016 to 2017?"
    candidates = (_candidate(1, "revenue", "2015"),)
    contexts = {
        candidates[0].evidence_id: "revenue | 2015 | 101",
    }
    build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids=set(contexts),
        evidence_context_by_id=contexts,
        guard=RetrievedContentGuard(),
    )
    skeleton = _skeleton("start", "end")

    result = rerank_descriptor_candidates_v1(
        question=question,
        role=skeleton.roles[0],
        skeleton=skeleton,
        selected_descriptor_ids=(build.catalog.descriptors[0].descriptor_id,),
        catalog_build=build,
        candidates=candidates,
        intent=extract_financial_question_intent_v2(question),
        evidence_context_by_id=contexts,
    )

    assert result.considered_candidate_count == 0
    assert result.ranked_candidates == ()


def test_candidate_local_context_breaks_same_evidence_numeric_ties() -> None:
    question = "What was the difference between credit capacity and service fees?"
    context = (
        "Credit capacity was $ 20 million. "
        + "operational discussion " * 30
        + "Service fees were $ 30 million."
    )
    candidates = tuple(
        item
        for item in extract_numeric_candidates_v2(
            source_id="report.pdf",
            evidence_id="text_1",
            text=context,
            kind="text",
        )
        if item.role == "operand"
    )
    build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids={"text_1"},
        evidence_context_by_id={"text_1": context},
        guard=RetrievedContentGuard(),
    )
    skeleton = _skeleton()

    result = rerank_descriptor_candidates_v1(
        question=question,
        role=skeleton.roles[0],
        skeleton=skeleton,
        selected_descriptor_ids=(build.catalog.descriptors[0].descriptor_id,),
        catalog_build=build,
        candidates=candidates,
        intent=extract_financial_question_intent_v2(question),
        evidence_context_by_id={"text_1": context},
    )

    expected = next(item for item in candidates if item.raw_text == "$ 20 million")
    assert result.ranked_candidates[0].candidate_id == expected.candidate_id
    assert "candidate_local_role_anchor_overlap" in (
        result.ranked_candidates[0].score_reasons
    )
