import json

import pytest

from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.retrieval import conftest as fixtures
from tests.v2_test_support import user_context

chunk_factory = fixtures.chunk_factory
document_factory = fixtures.document_factory
snapshot_factory = fixtures.snapshot_factory


@pytest.mark.parametrize("mixed", [True, False])
def test_bad_sibling_never_removes_valid_claim_or_creates_answered(
    mixed, snapshot_factory, document_factory, chunk_factory
):
    text = "出差申请由直属经理审批。"
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text
    )
    good = {"claim_id": "C1", "text": text, "critical": True, "cited_source_ids": ["S1"]}
    bad = {"claim_id": "C2", "text": "未知要求。", "critical": True, "cited_source_ids": []}
    calls = []

    def chat(*args, **kwargs):
        calls.append(1)
        return json.dumps({"answer": text, "claims": [good, bad] if mixed else [bad]})

    runner.response_builder.chat_fn = chat
    response = runner.run("出差申请由谁审批？", user_context())
    assert len(calls) == 1
    if mixed:
        assert response.mode == "partial" and response.claims[0].text == text
        assert response.trace["invalid_claim_rows_quarantined"] == 1
        assert response.warnings
    else:
        assert response.mode == "system" and response.claims == []
