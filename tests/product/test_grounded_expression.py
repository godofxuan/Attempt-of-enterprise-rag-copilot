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
