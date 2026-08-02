from __future__ import annotations

import json

import pytest

from app.external_datasets.finqa_descriptor_selector_v1 import (
    LocalFinQADescriptorSelectorV1,
    parse_descriptor_selections_v1,
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


def _fixtures():
    candidates = tuple(
        extract_numeric_candidates_v2(
            source_id="report.pdf",
            evidence_id=f"table_{index}",
            text=str(value),
            kind="table_cell",
            table_id="debt",
            row_header=label,
            column_header="2017",
        )[0]
        for index, (label, value) in enumerate(
            (("goodwill", 2589), ("purchase price", 3201)),
            start=1,
        )
    )
    catalog = build_safe_descriptor_catalog_v1(
        candidates=candidates,
        admitted_evidence_ids={"table_1", "table_2"},
        guard=RetrievedContentGuard(),
    ).catalog
    skeleton = SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "part",
                    "period_role": "none",
                },
                {
                    "role_id": "role-02",
                    "semantic_role": "total",
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
    return skeleton, catalog


def test_local_descriptor_selector_uses_enum_only_contract() -> None:
    skeleton, catalog = _fixtures()
    descriptor_ids = [item.descriptor_id for item in catalog.descriptors]
    calls = []

    def fake_chat(model, messages, **kwargs):
        calls.append((model, messages, kwargs))
        return json.dumps(
            {
                "selection_version": "finqa_descriptor_selection_v1",
                "selections": [
                    {
                        "role_id": "role-01",
                        "descriptor_ids": [descriptor_ids[0]],
                    },
                    {
                        "role_id": "role-02",
                        "descriptor_ids": [descriptor_ids[1]],
                    },
                ],
            }
        )

    result = LocalFinQADescriptorSelectorV1(
        model="local-model",
        chat_fn=fake_chat,
    ).select(
        question="What percent of purchase price was goodwill?",
        skeleton=skeleton,
        catalog=catalog,
    )

    assert result.generation_calls == 1
    assert calls[0][2]["think"] is False
    schema_ids = calls[0][2]["response_format"]["properties"][
        "selections"
    ]["items"]["properties"]["descriptor_ids"]["items"]["enum"]
    assert set(schema_ids) == set(descriptor_ids)


def test_descriptor_selector_rejects_unknown_descriptor() -> None:
    skeleton, catalog = _fixtures()
    raw = json.dumps(
        {
            "selection_version": "finqa_descriptor_selection_v1",
            "selections": [
                {"role_id": "role-01", "descriptor_ids": ["desc-bad"]},
                {"role_id": "role-02", "descriptor_ids": ["desc-bad"]},
            ],
        }
    )

    with pytest.raises(ValueError):
        parse_descriptor_selections_v1(
            raw,
            skeleton=skeleton,
            catalog=catalog,
        )
