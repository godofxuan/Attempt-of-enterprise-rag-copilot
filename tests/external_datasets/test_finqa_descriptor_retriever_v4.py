from __future__ import annotations

from app.external_datasets.finqa_descriptor_retriever_v4 import (
    StructuredFinQADescriptorRetrieverV4,
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


def _catalog(rows):
    candidates = tuple(
        extract_numeric_candidates_v2(
            source_id="report.pdf",
            evidence_id=f"table_{index}",
            text=value,
            kind="table_cell",
            table_id="facts",
            row_header=label,
            column_header=period,
        )[0]
        for index, (label, period, value) in enumerate(rows, start=1)
    )
    return build_safe_descriptor_catalog_v1(
        candidates=candidates,
        admitted_evidence_ids={item.evidence_id for item in candidates},
        guard=RetrievedContentGuard(),
    ).catalog


def _id(catalog, row_header: str) -> str:
    return next(
        item.descriptor_id
        for item in catalog.descriptors
        if item.row_header == row_header
    )


def test_percent_change_prefers_balance_descriptors_without_lexical_signal() -> None:
    catalog = _catalog(
        (
            ("balance at december", "2015", "373"),
            ("balance at december", "2014", "394"),
            ("additions for current year tax positions", "2015", "7"),
            ("settlements", "2015", "19"),
            ("foreign currency translation", "2015", "2"),
            ("statute of limitations", "2015", "7"),
        )
    )
    skeleton = SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "new_value",
                    "period_role": "end",
                },
                {
                    "role_id": "role-02",
                    "semantic_role": "old_value",
                    "period_role": "start",
                },
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "PERCENT_CHANGE",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"role_id": "role-02"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )

    result = StructuredFinQADescriptorRetrieverV4().select(
        question=(
            "What was the percentage change in unrecognized tax benefits "
            "from 2014 to 2015?"
        ),
        skeleton=skeleton,
        catalog=catalog,
    )

    target = _id(catalog, "balance at december")
    assert all(
        selection.descriptor_ids[0] == target
        for selection in result.selections.selections
    )


def test_multi_operand_add_prefers_descriptor_covering_role_cardinality() -> None:
    maturity_rows = tuple(
        ("amount in thousands", str(year), str(value))
        for year, value in zip(
            range(2016, 2020), (270852, 766801, 1324616, 1000000)
        )
    )
    catalog = _catalog(
        (
            *maturity_rows,
            ("interest rate", "2016", "4.8"),
            ("lease obligations", "2016", "149"),
            ("fair value", "2016", "500"),
            ("pollution control bonds", "2016", "200"),
        )
    )
    skeleton = SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": f"role-{index:02d}",
                    "semantic_role": "component",
                    "period_role": "none",
                }
                for index in range(1, 5)
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "ADD",
                    "arguments": [
                        {"role_id": f"role-{index:02d}"}
                        for index in range(1, 5)
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )

    result = StructuredFinQADescriptorRetrieverV4().select(
        question="What was the sum of annual debt maturities due in four years?",
        skeleton=skeleton,
        catalog=catalog,
    )

    target = _id(catalog, "amount in thousands")
    assert all(
        selection.descriptor_ids[0] == target
        for selection in result.selections.selections
    )
    assert result.generation_calls == 0
