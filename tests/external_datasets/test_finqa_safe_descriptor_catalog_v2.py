from __future__ import annotations

import json

from app.external_datasets.finqa_numeric_evidence_v2 import (
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v1 import (
    catalog_prompt_payload_v1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v2 import (
    build_contextual_safe_descriptor_catalog_v2,
)
from app.security.retrieved_content import RetrievedContentGuard


def _text_candidate(evidence_id: str, text: str):
    return extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id=evidence_id,
        text=text,
        kind="text",
    )[0]


def test_contextual_catalog_separates_unlabeled_text_numbers() -> None:
    first = _text_candidate("text_1", "$ 198")
    second = _text_candidate("text_2", "$ 119")
    context = {
        "text_1": "Cost reduction initiatives contributed $ 198 million.",
        "text_2": "Operating companies income increased by $ 119 million.",
    }

    build = build_contextual_safe_descriptor_catalog_v2(
        candidates=(first, second),
        admitted_evidence_ids=set(context),
        evidence_context_by_id=context,
        guard=RetrievedContentGuard(),
    )
    serialized = json.dumps(
        catalog_prompt_payload_v1(build.catalog),
        sort_keys=True,
    )

    assert build.catalog.descriptor_count == 2
    assert "cost reduction initiatives" in serialized
    assert "operating companies income" in serialized
    assert "198" not in serialized
    assert "119" not in serialized


def test_contextual_catalog_does_not_use_unadmitted_context() -> None:
    candidate = _text_candidate("text_1", "$ 198")

    try:
        build_contextual_safe_descriptor_catalog_v2(
            candidates=(candidate,),
            admitted_evidence_ids={"text_1"},
            evidence_context_by_id={"text_2": "unadmitted"},
            guard=RetrievedContentGuard(),
        )
    except ValueError as error:
        assert "not admitted" in str(error)
    else:
        raise AssertionError("unadmitted context was accepted")
