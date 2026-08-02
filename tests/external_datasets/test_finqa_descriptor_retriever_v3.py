from __future__ import annotations

import numpy as np

from app.external_datasets.finqa_descriptor_retriever_v3 import (
    HybridFinQADescriptorRetrieverV3,
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


def _catalog():
    rows = (
        ("balance at december", "373"),
        ("additions for current year tax positions", "7"),
        ("effects of foreign currency translation", "2"),
        ("settlements", "19"),
        ("lapse of statute of limitations", "7"),
    )
    candidates = tuple(
        extract_numeric_candidates_v2(
            source_id="report.pdf",
            evidence_id=f"table_{index}",
            text=value,
            kind="table_cell",
            table_id="tax-benefits",
            row_header=label,
            column_header="2015",
        )[0]
        for index, (label, value) in enumerate(rows, start=1)
    )
    catalog = build_safe_descriptor_catalog_v1(
        candidates=candidates,
        admitted_evidence_ids={item.evidence_id for item in candidates},
        guard=RetrievedContentGuard(),
    ).catalog
    target_id = next(
        item.descriptor_id
        for item in catalog.descriptors
        if item.row_header == "balance at december"
    )
    return catalog, target_id


def _skeleton() -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
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


def test_hybrid_retriever_recovers_semantic_descriptor_without_token_overlap() -> None:
    catalog, target_id = _catalog()
    calls = []

    def fake_embed(texts: list[str]) -> np.ndarray:
        calls.append(texts)
        vectors = []
        for text in texts:
            vectors.append(
                [1.0, 0.0]
                if "balance at december" in text or text.startswith("query:")
                else [0.0, 1.0]
            )
        return np.asarray(vectors, dtype="float32")

    result = HybridFinQADescriptorRetrieverV3(
        embed_batch=fake_embed,
        model_identifier="fake-bge",
        model_sha256="a" * 64,
        embedding_dimension=2,
    ).select(
        question=(
            "What was the percentage change in unrecognized tax benefits "
            "from 2014 to 2015?"
        ),
        skeleton=_skeleton(),
        catalog=catalog,
    )

    assert len(calls) == 1
    assert len(calls[0]) == len(_skeleton().roles) + catalog.descriptor_count
    serialized_batch = "\n".join(calls[0])
    assert "desc-" not in serialized_batch
    assert "candidate_id" not in serialized_batch
    assert "evidence_id" not in serialized_batch
    assert "373" not in serialized_batch
    assert all(
        selection.descriptor_ids[0] == target_id
        for selection in result.selections.selections
    )
    assert result.embedding_request_count == 1
    assert result.generation_calls == 1


def test_hybrid_retriever_is_catalog_order_invariant() -> None:
    catalog, _ = _catalog()

    def fake_embed(texts: list[str]) -> np.ndarray:
        return np.asarray(
            [[float(index + 1), 1.0] for index in range(len(texts))],
            dtype="float32",
        )

    retriever = HybridFinQADescriptorRetrieverV3(
        embed_batch=fake_embed,
        model_identifier="fake-bge",
        model_sha256="b" * 64,
        embedding_dimension=2,
    )
    kwargs = {
        "question": "What was the change in unrecognized tax benefits?",
        "skeleton": _skeleton(),
    }

    forward = retriever.select(catalog=catalog, **kwargs)
    reverse = retriever.select(
        catalog=catalog.model_copy(
            update={"descriptors": tuple(reversed(catalog.descriptors))}
        ),
        **kwargs,
    )

    assert forward.selections == reverse.selections
    assert forward.rankings == reverse.rankings
