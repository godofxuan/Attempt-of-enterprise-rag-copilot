from __future__ import annotations

from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DeterministicFinQADescriptorRetrieverV1,
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
            column_header="2006",
        )[0]
        for index, (label, value) in enumerate(rows, start=1)
    )
    return build_safe_descriptor_catalog_v1(
        candidates=candidates,
        admitted_evidence_ids={item.evidence_id for item in candidates},
        guard=RetrievedContentGuard(),
    ).catalog


def _skeleton(*roles: str) -> SemanticProgramSkeletonV2:
    operation = "ADD" if len(roles) > 2 else "DIV"
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": f"role-{index:02d}",
                    "semantic_role": role,
                    "period_role": "none",
                }
                for index, role in enumerate(roles, start=1)
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": operation,
                    "arguments": [
                        {"role_id": f"role-{index:02d}"}
                        for index in range(1, len(roles) + 1)
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )


def _descriptor_id_by_row(catalog, row_header: str) -> str:
    return next(
        item.descriptor_id
        for item in catalog.descriptors
        if item.row_header == row_header
    )


def test_exact_financial_phrase_outranks_unrelated_product_rows() -> None:
    catalog = _catalog(
        (
            ("matching buy sell volumes", "35"),
            ("heavy fuel oil", "20"),
            ("feedstocks and special products", "15"),
            ("sales to jobbers and dealers", "10"),
            ("gasoline", "5"),
        )
    )

    result = DeterministicFinQADescriptorRetrieverV1().select(
        question="What was total matching buy/sell volumes in 2006?",
        skeleton=_skeleton("component", "component"),
        catalog=catalog,
    )

    expected = _descriptor_id_by_row(catalog, "matching buy sell volumes")
    assert all(
        selection.descriptor_ids[0] == expected
        for selection in result.selections.selections
    )
    assert result.generation_calls == 0


def test_part_total_roles_use_separate_question_anchors() -> None:
    catalog = _catalog(
        (
            ("goodwill", "258.9"),
            ("cash purchase price net of cash acquired", "320.1"),
            ("restructuring costs", "9.1"),
        )
    )

    result = DeterministicFinQADescriptorRetrieverV1().select(
        question=(
            "What percentage of cash purchase price net of cash acquired "
            "was goodwill?"
        ),
        skeleton=_skeleton("part", "total"),
        catalog=catalog,
    )

    part, total = result.selections.selections
    assert part.descriptor_ids[0] == _descriptor_id_by_row(
        catalog, "goodwill"
    )
    assert total.descriptor_ids[0] == _descriptor_id_by_row(
        catalog, "cash purchase price net of cash acquired"
    )


def test_retrieval_is_catalog_order_invariant() -> None:
    catalog = _catalog(
        (
            ("matching buy sell volumes", "35"),
            ("heavy fuel oil", "20"),
            ("gasoline", "5"),
        )
    )
    reversed_catalog = catalog.model_copy(
        update={"descriptors": tuple(reversed(catalog.descriptors))}
    )
    retriever = DeterministicFinQADescriptorRetrieverV1()
    kwargs = {
        "question": "What was matching buy/sell volumes?",
        "skeleton": _skeleton("component", "component"),
    }

    forward = retriever.select(catalog=catalog, **kwargs)
    reverse = retriever.select(catalog=reversed_catalog, **kwargs)

    assert forward.selections == reverse.selections
    assert forward.rankings == reverse.rankings
