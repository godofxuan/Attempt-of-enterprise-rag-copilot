import pytest

from app.agent.answer_contract import answer_sufficiency
from app.agent.evidence_relevance import has_query_anchor_support
from app.agent.generation_v2 import GenerationV2ResponseBuilder
from tests.agent_v2.test_generation_v2 import state_with_evidence
from tests.v2_test_support import admitted_search_hit


@pytest.mark.parametrize(
    "question",
    [
        "删除快递报销制度后，还能确认每单上限吗？",
        "快递报销制度每单上限是多少？",
    ],
)
def test_unquoted_named_policy_is_an_anchor(question):
    hit = admitted_search_hit(
        matched_text="运费标准表。文件运费上限为 20 元。",
        context_text="运费标准表。文件运费上限为 20 元。",
    )
    assert not has_query_anchor_support(question, hit)


def test_same_subject_different_requested_relation_is_not_complete():
    assert (
        answer_sufficiency("出差申请需要谁审批？", ["出差申请必须提前 7 天提交。"])
        == "missing_requested_relation"
    )
    assert (
        answer_sufficiency("出差申请由谁批准？", ["出差申请由直属经理批准。"])
        != "missing_requested_relation"
    )


@pytest.mark.parametrize(
    "question,text",
    [
        ("当前制度每周最多允许远程办公几天？", "当前制度每周最多允许远程办公 3 天。"),
        ("《远程办公制度》允许多少天？", "远程办公制度允许每周 3 天。"),
        ("按照快递报销制度，每单最多报销多少？", "快递报销制度。每单上限为 40 元。"),
    ],
)
def test_legitimate_anchor_controls(question, text):
    assert has_query_anchor_support(
        question, admitted_search_hit(matched_text=text, context_text=text)
    )


def test_missing_duration_after_shape_valid_output_is_partial():
    import json

    builder = GenerationV2ResponseBuilder(
        model="stub",
        max_attempts=1,
        chat_fn=lambda *args, **kwargs: json.dumps(
            dict(
                answer="Remote work is permitted.",
                claims=[
                    dict(
                        claim_id="x",
                        text="Remote work is permitted.",
                        critical=True,
                        cited_source_ids=["S1"],
                    )
                ],
            )
        ),
    )
    response = builder.build(
        question="How many days is remote work permitted?",
        state=state_with_evidence(),
        mode="answered",
        stop_reason="completed",
        trace={},
    )
    assert response.mode == "partial"


@pytest.mark.parametrize(
    "claim,supported",
    [
        ("Only employees in the pilot may claim up to 20 yuan after approval.", True),
        ("  Only employees in the pilot may claim up to 20 yuan after approval.  ", True),
        ("Employees may claim up to 20 yuan.", False),
        ("Only employees in the pilot may claim up to 20 percent after approval.", False),
        ("Only contractors in the pilot may claim up to 20 yuan after approval.", False),
        ("Only employees in the pilot may claim at least 20 yuan after approval.", False),
        ("Only employees in the pilot may claim up to 20 yuan without approval.", False),
    ],
)
def test_numeric_scope_and_units_are_not_relaxed(claim, supported):
    from app.agent.citation_verifier import verify_claims
    from app.domain.evidence import Claim

    text = "Only employees in the pilot may claim up to 20 yuan after approval."
    evidence = admitted_search_hit(matched_text=text, context_text=text)
    result = verify_claims(
        [Claim(claim_id="c", text=claim, cited_chunk_ids=[evidence.hit.chunk_id])], [evidence]
    )[0]
    assert result.supported is supported
    if supported:
        assert result.supporting_spans[0].quote == text
