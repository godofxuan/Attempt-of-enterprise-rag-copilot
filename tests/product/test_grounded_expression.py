"""Bound explanation is not raw unverified model prose or a new publisher."""

import json
import pytest
from app.agent.answer_blocks import retained_blocks, bind_generated_blocks
from app.agent.generation_v2 import _parse_generated_answer
from app.domain.evidence import AnswerBlock, Claim


def test_sparse_uses_parse_one_representation_and_keep_necessary_sources():
    wire = {
        "unit_uses": [
            {"unit_id": "S1U1", "need_refs": ["N1"]},
            {"unit_id": "S1U2", "need_refs": ["N1"]},
        ],
        "need_status": {
            "N1": {
                "status": "supported",
                "subject_matches": True,
                "attribute_matches": True,
                "conditions_preserved": True,
                "selection_scope": "linked_units",
            }
        },
        "answer_blocks": [
            {
                "kind": "explanation",
                "text": "借用最长14天，仍受维修资格条件限制。",
                "source_unit_ids": ["S1U1", "S1U2"],
            }
        ],
    }
    parsed = _parse_generated_answer(json.dumps(wire))
    assert len(parsed.claims) == 2 and parsed._unit_decision_ids is None
    assert parsed._answer_blocks[0].claim_ids == ["C1", "C2"]
    wire["answer_blocks"][0]["source_unit_ids"] = ["S9U1"]
    with pytest.raises(ValueError, match="bind"):
        _parse_generated_answer(json.dumps(wire))


def test_paraphrase_keeps_binding_and_rejects_invented_number_or_lost_source():
    claims = [
        Claim(
            claim_id="C1",
            text="借用期限为1至14天，开始日期不得早于申请当天。",
            critical=True,
            cited_chunk_ids=["doc"],
            need_refs=["N1"],
        )
    ]
    good = AnswerBlock(text="借用的最长时限是14天，开始日期不得早于申请当天。", claim_ids=["C1"])
    kept, errors = retained_blocks([good], claims, "借用最长多少天？")
    assert kept == [good] and not errors
    omitted_condition = AnswerBlock(text="借用的最长时限是14天。", claim_ids=["C1"])
    assert retained_blocks([omitted_condition], claims, "借用最长多少天？")[1]
    bad = AnswerBlock(text="借用的最长时限是30天。", claim_ids=["C1"])
    assert (
        retained_blocks([bad], claims, "借用最长多少天？")[1][0]["reason"]
        == "scalar_or_date_mismatch"
    )
    assert (
        retained_blocks([good], [], "借用最长多少天？")[1][0]["reason"]
        == "unbound_or_discarded_evidence"
    )


def test_source_ids_cannot_be_empty_or_unselected():
    with pytest.raises(ValueError, match="bind"):
        bind_generated_blocks([{"kind": "rule", "text": "任意内容", "source_unit_ids": []}], [])


def test_one_block_binding_drives_both_claims_and_coverage_and_strips_only_known_labels():
    wire = {
        "answer_blocks": [
            {
                "kind": "rule",
                "text": "最长14天 [S1U1]，开始日期不得早于申请当天。",
                "source_unit_ids": ["S1U1"],
                "need_refs": ["N1"],
                "assumptions": [],
            }
        ],
        "need_status": {
            "N1": {
                "status": "supported",
                "subject_matches": True,
                "attribute_matches": True,
                "conditions_preserved": True,
                "selection_scope": "linked_units",
            }
        },
    }
    result = _parse_generated_answer(json.dumps(wire))
    assert len(result.claims) == 1 and result.request_coverage[0].claim_ids == ["C1"]
    assert "S1U1" not in result._answer_blocks[0].text and "14天" in result._answer_blocks[0].text
    wire["answer_blocks"][0]["text"] = "最长14天 [S9U9]"
    with pytest.raises(ValueError, match="unbound source label"):
        _parse_generated_answer(json.dumps(wire))


def test_conditional_premise_requires_exact_user_quote_and_remains_hypothetical():
    claims = [
        Claim(
            claim_id="C1",
            text="只有存在有效维修记录的员工可以申请临时电脑。",
            critical=True,
            cited_chunk_ids=["doc"],
            need_refs=["N1"],
        )
    ]
    question = "假设我没有有效维修记录，按制度是否可以申请？"
    block = AnswerBlock(
        kind="conditional",
        text="没有有效维修记录就不满足制度的申请条件。",
        claim_ids=["C1"],
        assumptions=["我没有有效维修记录"],
    )
    assert retained_blocks([block], claims, question)[0] == [block]
    forged = block.model_copy(update={"assumptions": ["我已经被批准"]})
    assert retained_blocks([forged], claims, question)[1][0]["reason"] == "unbound_user_premise"


def test_formatting_numbers_and_presentation_kind_do_not_become_business_facts():
    wire = {
        "answer_blocks": [
            {
                "kind": "conditional",
                "text": "1. 最长14天 [S1]。开始日期不得早于申请当天。",
                "source_unit_ids": ["S1U1"],
                "need_refs": ["N1"],
                "assumptions": [],
            }
        ],
        "need_status": {
            "N1": {
                "status": "supported",
                "subject_matches": True,
                "attribute_matches": True,
                "conditions_preserved": True,
                "selection_scope": "linked_units",
            }
        },
    }
    parsed = _parse_generated_answer(json.dumps(wire))
    assert (
        parsed._answer_blocks[0].kind == "explanation" and not parsed._answer_blocks[0].assumptions
    )
    claims = [
        Claim(
            claim_id="C1",
            text="借用期限为1至14天，开始日期不得早于申请当天。",
            critical=True,
            cited_chunk_ids=["doc"],
            need_refs=["N1"],
        )
    ]
    assert retained_blocks(parsed._answer_blocks, claims, "最长几天？")[0]
    wrong = parsed._answer_blocks[0].model_copy(
        update={"text": "最长30天，开始日期不得早于申请当天。"}
    )
    assert (
        retained_blocks([wrong], claims, "是不是最长30天？")[1][0]["reason"]
        == "scalar_or_date_mismatch"
    )
    version = parsed._answer_blocks[0].model_copy(
        update={"text": "依据loan-policy-v1，最长14天，开始日期不得早于申请当天。"}
    )
    assert retained_blocks([version], claims, "最长几天？", {"C1": "规则版本loan-policy-v1。"})[0]
    assert (
        retained_blocks([version], claims, "最长几天？")[1][0]["reason"]
        == "unbound_source_identifier"
    )


def test_compound_expression_checks_each_bound_clause_without_mixing_polarities():
    claims = [
        Claim(claim_id="C1", text="会议室每日开放时间为09:00至18:00。", cited_chunk_ids=["d"]),
        Claim(claim_id="C2", text="每次预订不得超过2小时。", cited_chunk_ids=["d"]),
    ]
    text = "会议室每日开放时间为09:00至18:00，单次预订不得超过2小时。"
    block = AnswerBlock(text=text, claim_ids=["C1", "C2"])
    assert retained_blocks([block], claims, "开放时间和时长？")[0] == [block]
    reversed_limit = block.model_copy(update={"text": text.replace("不得超过", "可以超过")})
    assert retained_blocks([reversed_limit], claims, "开放时间和时长？")[1]
    # Keeping a separate negative sentence cannot conceal a reversed limit.
    hidden = reversed_limit.model_copy(update={"text": reversed_limit.text + "不得代订。"})
    assert retained_blocks([hidden], claims, "开放时间和时长？")[1]


def test_bound_symbolic_value_cannot_disappear_from_an_explanation():
    claim = Claim(claim_id="C1", text="用户确认后保存OPEN待受理工单。", cited_chunk_ids=["d"])
    incomplete = AnswerBlock(text="用户确认后保存为", claim_ids=["C1"])
    assert retained_blocks([incomplete], [claim], "保存为什么状态？")[1][0]["reason"] == "missing_bound_symbol"
    complete = incomplete.model_copy(update={"text": "用户确认后保存为OPEN待受理工单。"})
    assert retained_blocks([complete], [claim], "保存为什么状态？")[0] == [complete]
