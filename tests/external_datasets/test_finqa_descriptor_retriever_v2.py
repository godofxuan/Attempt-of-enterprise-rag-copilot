from __future__ import annotations

from app.external_datasets.finqa_descriptor_retriever_v2 import (
    DeterministicFinQADescriptorRetrieverV2,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    build_safe_descriptor_catalog_v1,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.security.retrieved_content import RetrievedContentGuard


def _catalog(rows: tuple[tuple[str, str], ...]):
    candidates = tuple(
        extract_numeric_candidates_v2(
            source_id="report.pdf",
            evidence_id=f"table_{index}",
            text=value,
            kind="table_cell",
            table_id="facts",
            row_header=label,
            column_header="2017",
        )[0]
        for index, (label, value) in enumerate(rows, start=1)
    )
    return build_safe_descriptor_catalog_v1(
        candidates=candidates,
        admitted_evidence_ids={item.evidence_id for item in candidates},
        guard=RetrievedContentGuard(),
    ).catalog


def _skeleton(part_role: str, total_role: str) -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": part_role,
                    "period_role": "none",
                },
                {
                    "role_id": "role-02",
                    "semantic_role": total_role,
                    "period_role": "none",
                },
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "DIV",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"role_id": "role-02"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )


def _id(catalog, row_header: str) -> str:
    return next(
        item.descriptor_id
        for item in catalog.descriptors
        if item.row_header == row_header
    )


def test_financial_tokenizer_preserves_s_and_p_entity() -> None:
    catalog = _catalog(
        (
            ("31 dec s&p 500", "208.1"),
            ("31 dec citi", "193.5"),
            ("31 dec financials", "230.9"),
            ("gasoline", "100"),
            ("heavy fuel oil", "90"),
        )
    )

    result = DeterministicFinQADescriptorRetrieverV2().select(
        question="What was the ratio of S&P 500 compared to Citi?",
        skeleton=_skeleton("component", "component"),
        catalog=catalog,
    )

    selected = result.selections.selections[0].descriptor_ids
    assert _id(catalog, "dec s&p") in selected[:2]
    assert _id(catalog, "dec citi") in selected[:2]


def test_extended_percent_pattern_separates_that_was_clause() -> None:
    catalog = _catalog(
        (
            ("class a common stock issued and outstanding", "100"),
            ("class a common stock authorized", "200"),
            ("class b common stock", "50"),
        )
    )

    result = DeterministicFinQADescriptorRetrieverV2().select(
        question=(
            "What was the percent of the class a common stock authorized "
            "that was issued and outstanding?"
        ),
        skeleton=_skeleton("part", "total"),
        catalog=catalog,
    )

    part, total = result.selections.selections
    assert part.descriptor_ids[0] == _id(
        catalog, "class a common stock issued and outstanding"
    )
    assert total.descriptor_ids[0] == _id(
        catalog, "class a common stock authorized"
    )
