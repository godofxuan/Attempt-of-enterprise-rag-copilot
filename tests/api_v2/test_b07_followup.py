import json

import pytest

from app.agent.answer_contract import bounded_answer_slots
from app.agent.evidence_ledger import _numeric_conflicts
from tests.agent_v2.test_evidence_ledger import hit
from tests.api_v2 import test_runtime_closure_flow as original
from tests.api_v2.test_bounded_correctness_matrix import consistent, observe

service = original.service
WHO = "这笔报销由谁审批？"
CASES = [
    ("N01", WHO, "这笔报销不是由财务审批。", "partial"),
    ("N02", WHO, "这笔报销不由财务审批。", "partial"),
    ("N03", "Who approves this expense?", "This expense is not approved by finance.", "partial"),
    ("N04", WHO, "必须审批。", "partial"),
    ("N05", WHO, "不能认定无需审批。", "partial"),
    ("N06", WHO, "采购合同由法务审批。", "not_found"),
    ("C01", "超过100元的报销由谁审批？", "不超过100元，由直属经理审批。", "not_found"),
    ("C02", WHO, "不超过100元，无需审批；超过100元，由部门负责人审批。", "partial"),
    ("P01", WHO, "这笔报销由财务审批。", "answered"),
    ("P02", WHO, "这笔报销需要审批。", "partial"),
    ("P03", WHO, "这笔报销按流程审批。", "partial"),
    ("P04", WHO, "这笔报销材料未说明审批人。", "partial"),
    ("P05", WHO, "这笔报销无需审批。", "answered"),
    ("P06", WHO, "这笔报销无需经理审批，仍需部门负责人审批。", "answered"),
    ("P07", "超过100元的报销由谁审批？", "超过100元，由部门负责人审批。", "answered"),
    ("P08", WHO, "不超过100元无需审批；超过100元由部门负责人审批。", "partial"),
]


@pytest.mark.parametrize("case,question,text,mode", CASES, ids=[r[0] for r in CASES])
def test_component(case, question, text, mode):
    slots = bounded_answer_slots(question, [text])
    assert ("approver" in slots.satisfied) == (mode == "answered")
    assert bool(slots.retained) == (mode != "not_found")
    if case in {"C02", "P08"}:
        assert slots.conditional


@pytest.mark.parametrize("case,question,text,mode", CASES, ids=[r[0] for r in CASES])
def test_http(service, case, question, text, mode):
    start, seen, _ = service
    with start([dict(id="policy", text=text)]) as client:
        response = client.post("/agent/v2/chat", json={"question": question})
    data = response.json()
    observe("HTTP_" + case, question, text, data, seen)
    assert response.status_code == 200
    consistent(data)
    if not seen["llm"] and data["mode"] == "not_found":
        # A component counterexample may be blocked earlier by relevance.
        assert data["sources"] == data["claims"] == data["citations"] == []
        return
    assert data["mode"] == mode
    assert data["trace"]["answered_aspect_count"] == int(mode == "answered")
    assert data["trace"]["missing_answer_aspect_count"] == int(mode != "answered")
    if mode == "partial":
        assert any(s in data["answer"] for s in ["尚未确定", "not yet determined"])


@pytest.mark.parametrize(
    "case,question,text,mode", [r for r in CASES if r[0] in {"N01", "N05", "C02", "P01"}]
)
def test_http_fallback(service, monkeypatch, case, question, text, mode):
    start, seen, _ = service

    def wrong_citation(model, messages, **kwargs):
        seen["llm"].append(messages)
        records = json.loads(
            next(
                line
                for line in messages[1]["content"].splitlines()
                if line.startswith("[{") and '"source_id"' in line
            )
        )
        other = next(r for r in records if text not in r["matched_text"])
        return json.dumps(
            dict(
                answer=text,
                claims=[
                    dict(
                        claim_id="fixed",
                        text=text,
                        critical=True,
                        cited_source_ids=[other["source_id"]],
                    )
                ],
            )
        )

    monkeypatch.setattr("app.agent.generation_v2.chat_with_ollama", wrong_citation)
    rows = [dict(id="a-policy", text=text), dict(id="z-other", text="这笔报销需要审批。")]
    with start(rows, "safe_dense_raw20_bge") as client:
        response = client.post("/agent/v2/chat", json={"question": question})
    data = response.json()
    observe("FALLBACK_" + case, question, rows, data, seen)
    assert response.status_code == 200
    consistent(data)
    assert data["mode"] == "partial"
    assert data["trace"]["generation_error_category"] == "unsupported"
    assert data["trace"]["answered_aspect_count"] == int(mode == "answered")
    assert text in data["answer"]
    if mode != "answered":
        assert "尚未确定" in data["answer"]


SCOPES = [
    ("object", "本规定适用于报销退款。", "本规定适用于采购退款。"),
    ("condition", "仅限境内退款。", "仅限跨境退款。"),
    ("context", "本规定仅适用于报销退款。", "本规定仅适用于采购退款。"),
]


@pytest.mark.parametrize("case,left,right", SCOPES)
def test_real_domain_scope(case, left, right):
    values = []
    for i, (scope, number) in enumerate([(left, 7), (right, 30)]):
        text = f"处理期限为{number}天。"
        values.append(
            hit(
                chunk_id=str(i),
                doc_id=str(i),
                policy_id=str(i),
                matched_text=text if case == "context" else scope + text,
                context_text=scope + text,
                context_from_parent=case == "context",
            )
        )
    assert not _numeric_conflicts({"deadline": values})


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("case,left,right", SCOPES[:2])
def test_scope_http(service, case, left, right, reverse):
    start, seen, _ = service
    rows = [
        dict(id="a", text=left + "处理期限为7天。"),
        dict(id="b", text=right + "处理期限为30天。"),
    ]
    if reverse:
        rows.reverse()
    question = "退款处理期限是多少天？"
    with start(rows, "safe_dense_raw20_bge") as client:
        response = client.post("/agent/v2/chat", json={"question": question})
    data = response.json()
    observe("SCOPE_" + case + str(reverse), question, rows, data, seen)
    assert response.status_code == 200
    consistent(data)
    assert data["mode"] == "partial"
    assert "范围" in data["answer"] and "不足以比较" in data["answer"]
    assert "潜在不一致" not in data["answer"]
    assert {s["doc_id"] for s in data["sources"]} == {"a", "b"}
    assert not seen["llm"]
    assert "7天" in data["answer"] and "30天" in data["answer"]
