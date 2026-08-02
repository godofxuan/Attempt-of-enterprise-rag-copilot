from __future__ import annotations

from pathlib import Path

from app.external_datasets.finqa_pairwise_residual_ranker_v1 import (
    PAIRWISE_FEATURE_NAMES,
    PairwiseRoleGroupV1,
)
from app.external_datasets.finqa_pairwise_residual_training_v1 import (
    PreparedPairwiseCaseV1,
)
from app.external_datasets.finqa_topk_ranker_protocol_v1 import (
    load_topk_ranker_protocol_v1,
)
from app.external_datasets.finqa_topk_ranker_training_v1 import (
    build_final_topk_artifact_v1,
    nested_company_cross_validate_v1,
)


def _features(value: float) -> tuple[float, ...]:
    return (value,) + tuple(0.0 for _ in PAIRWISE_FEATURE_NAMES[1:])


def _case(index: int) -> PreparedPairwiseCaseV1:
    group = PairwiseRoleGroupV1(
        descriptor_ids=tuple(
            f"desc-{index:08x}{item:08x}" for item in range(5)
        ),
        e8_scores=(4.0, 3.0, 2.0, 1.0, 0.0),
        features=tuple(
            _features(1.0 if item == 4 else 0.0) for item in range(5)
        ),
        labels=(False, False, False, False, True),
    )
    return PreparedPairwiseCaseV1(
        case_id=f"case-{index}",
        company_id=f"company-{index}",
        role_groups=(group,),
        source_candidate_count=5,
        descriptor_count=5,
        normalized_empty_table_cell_count=0,
        full_gold_evidence_covered=True,
        any_gold_evidence_covered=True,
    )


def test_nested_cv_selects_only_from_inner_folds_and_is_deterministic() -> None:
    root = Path(__file__).resolve().parents[2]
    protocol, protocol_sha256 = load_topk_ranker_protocol_v1(
        root / "docs/external_datasets/evidence/finqa_topk_ranker_protocol_v1.json"
    )
    cases = tuple(_case(index) for index in range(5))
    assignments = {case.company_id: index for index, case in enumerate(cases)}

    first = nested_company_cross_validate_v1(
        cases,
        company_folds=assignments,
        protocol=protocol,
    )
    second = nested_company_cross_validate_v1(
        cases,
        company_folds=assignments,
        protocol=protocol,
    )

    assert first == second
    assert len(first.outer_selections) == 5
    assert all(
        len(selection.candidate_metrics) == 18
        for selection in first.outer_selections
    )
    assert first.challenger_descriptor_recall_at_4 == 1.0
    artifact = build_final_topk_artifact_v1(
        cases,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
        final_config_id=first.final_config_id,
    )
    assert artifact.selected_config.config_id == first.final_config_id
    assert artifact.training_group_count == 5
