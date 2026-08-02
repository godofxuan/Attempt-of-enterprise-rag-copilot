from __future__ import annotations

from app.external_datasets.finqa_descriptor_retriever_v5 import (
    DeterministicFinQADescriptorRetrieverV5,
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
from app.security.retrieved_content import RetrievedContentGuard


def _skeleton() -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "comparison_left",
                    "period_role": "none",
                },
                {
                    "role_id": "role-02",
                    "semantic_role": "comparison_right",
                    "period_role": "none",
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


def _table_candidate(index: int, row_header: str):
    return extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id=f"table_{index}",
        text=str(100 + index),
        kind="table_cell",
        table_id="facts",
        row_header=row_header,
        column_header="2017",
    )[0]


def test_topic_hint_recovers_generic_tax_balance_descriptor() -> None:
    rows = (
        "balance at december",
        "ending carrying amount",
        "closing reserve",
        "ending liability",
        "period end assets",
        "closing inventory",
    )
    candidates = tuple(
        _table_candidate(index, row)
        for index, row in enumerate(rows, start=1)
    )
    contexts = {
        candidate.evidence_id: f"{row} | 2017 | {candidate.raw_text}"
        for candidate, row in zip(candidates, rows, strict=True)
    }
    contexts.update(
        {
            "text_20": (
                "The reconciliation of unrecognized tax benefits had a "
                "balance at December 31, 2017."
            ),
            "text_21": "The closing reserve relates to insurance claims.",
            "text_22": "Closing inventory includes finished goods.",
        }
    )
    build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids=set(contexts),
        evidence_context_by_id=contexts,
        guard=RetrievedContentGuard(),
    )
    target_descriptor = next(
        item.descriptor_id
        for item in build.catalog.descriptors
        if item.metric == "balance at december"
    )

    result = DeterministicFinQADescriptorRetrieverV5().select(
        question=(
            "What was the difference between unrecognized tax benefits "
            "and closing inventory?"
        ),
        skeleton=_skeleton(),
        catalog=build.catalog,
    )

    assert result.selections.selections[0].descriptor_ids[0] == target_descriptor


def test_local_context_hint_recovers_right_side_business_term() -> None:
    snippets = (
        ("$ 34", "The company operated in $ 34 countries."),
        ("$ 19", "The company closed $ 19 distribution centers."),
        ("$ 81", "The company sold $ 81 products."),
        ("$ 42", "The company served $ 42 markets."),
        ("$ 12", "The company owned $ 12 facilities."),
    )
    candidates = tuple(
        extract_numeric_candidates_v2(
            source_id="report.pdf",
            evidence_id=f"text_{index}",
            text=raw,
            kind="text",
        )[0]
        for index, (raw, _) in enumerate(snippets, start=1)
    )
    contexts = {
        candidate.evidence_id: context
        for candidate, (_, context) in zip(candidates, snippets, strict=True)
    }
    build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids=set(contexts),
        evidence_context_by_id=contexts,
        guard=RetrievedContentGuard(),
    )
    target_descriptor = next(
        item.descriptor_id
        for item in build.catalog.descriptors
        if item.local_context_hint and "countries" in item.local_context_hint
    )

    result = DeterministicFinQADescriptorRetrieverV5().select(
        question="What was the difference between countries and facilities?",
        skeleton=_skeleton(),
        catalog=build.catalog,
    )

    assert result.selections.selections[0].descriptor_ids[0] == target_descriptor


def test_primary_role_anchor_outweighs_broad_topic_hint() -> None:
    candidates = (
        _table_candidate(1, "unrecognized tax benefits"),
        _table_candidate(2, "ending liability"),
        _table_candidate(3, "closing inventory"),
        _table_candidate(4, "other reserve"),
        _table_candidate(5, "total assets"),
    )
    contexts = {
        candidate.evidence_id: (
            f"{candidate.row_header} | 2017 | {candidate.raw_text}"
        )
        for candidate in candidates
    }
    contexts["text_20"] = (
        "A broad discussion mentions unrecognized tax benefits, inventory, "
        "liabilities, reserves and assets."
    )
    build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids=set(contexts),
        evidence_context_by_id=contexts,
        guard=RetrievedContentGuard(),
    )
    target_descriptor = next(
        item.descriptor_id
        for item in build.catalog.descriptors
        if item.metric == "unrecognized tax benefits"
    )

    result = DeterministicFinQADescriptorRetrieverV5().select(
        question=(
            "What was the difference between unrecognized tax benefits "
            "and total assets?"
        ),
        skeleton=_skeleton(),
        catalog=build.catalog,
    )

    assert result.selections.selections[0].descriptor_ids[0] == target_descriptor
