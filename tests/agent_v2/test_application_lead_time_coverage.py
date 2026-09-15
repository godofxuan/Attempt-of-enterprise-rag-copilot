import json

import pytest

from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.agent.question_parts import part_is_addressed
from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.retrieval import conftest as retrieval_fixtures
from tests.v2_test_support import user_context

chunk_factory = retrieval_fixtures.chunk_factory
document_factory = retrieval_fixtures.document_factory
snapshot_factory = retrieval_fixtures.snapshot_factory


@pytest.mark.parametrize("unit", ["5 个工作日", "五个工作日", "3个自然日", "2天"])
def test_application_lead_time_accepts_explicit_units(unit):
    assert part_is_addressed(
        "连续年假申请提前多久", [f"当前制度要求连续年假至少提前 {unit} 申请。"]
    )


@pytest.mark.parametrize(
    "text",
    [
        "远程办公需要提前5个工作日申请。",
        "连续年假申请尚未说明，远程办公提前5个工作日申请。",
        "连续年假无需提前5个工作日申请。",
        "连续年假申请未规定提前多少工作日。",
        "连续年假申请有效期5个工作日。",
    ],
)
def test_duration_for_wrong_subject_or_relation_cannot_cover_application(text):
    assert not part_is_addressed("连续年假申请提前多久", [text])


@pytest.mark.parametrize("paraphrase", [False, True])
def test_verified_workday_claim_does_not_get_a_missing_warning(
    paraphrase, snapshot_factory, document_factory, chunk_factory
):
    texts = [
        "当前制度要求连续年假至少提前 5 个工作日申请。",
        "当前制度要求至少提前 2 个工作日提交远程办公申请。",
    ]
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=texts, claim=texts[0]
    )
    wire = {
        "answer": "".join(texts),
        "claims": [
            {"claim_id": "C1", "text": texts[0], "critical": True, "cited_source_ids": ["S1"]},
            {
                "claim_id": "C2",
                "text": texts[1].replace("要求", "规定") if paraphrase else texts[1],
                "critical": True,
                "cited_source_ids": ["S2"],
            },
        ],
    }
    runner.response_builder = GenerationV2ResponseBuilder(
        model="stub", max_attempts=1, chat_fn=lambda *a, **kw: json.dumps(wire, ensure_ascii=False)
    )
    result = runner.run("连续年假申请提前多久，远程办公申请又提前多久？", user_context())
    assert texts[0] in result.answer
    assert "尚未核验这一问题：连续年假" not in result.answer
    assert all(c.supported for c in result.citations)
    if paraphrase:
        assert result.mode == "partial" and len(result.claims) == 1
        assert "尚未核验这一问题：远程办公" in result.answer
        assert result.trace["unsupported_claim_reasons"]["critical_fact_requires_bound_span"] == 1
    else:
        assert result.mode == "answered" and len(result.claims) == 2
        assert result.trace["task_coverage"]["answer_missing"] == 0
