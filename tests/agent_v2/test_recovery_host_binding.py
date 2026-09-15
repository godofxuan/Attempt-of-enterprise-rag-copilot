import json

import pytest

from app.agent.controller_v2 import V2AgentController
from app.agent.evidence_ledger import evidence_view
from app.agent.query_analysis import RuleFirstQueryAnalyzer
from app.agent.task_advisor import TaskAdvisor
from app.agent.task_plan import build_task_plan
from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.retrieval import conftest as retrieval_fixtures
from tests.v2_test_support import admitted_search_hit, user_context

chunk_factory = retrieval_fixtures.chunk_factory
document_factory = retrieval_fixtures.document_factory
snapshot_factory = retrieval_fixtures.snapshot_factory


@pytest.mark.parametrize("kind", ["unique", "ambiguous", "unknown_id", "invented"])
def test_host_binds_only_unique_literal_quote_when_wire_id_is_blank(kind):
    text = "设备维修需要提前两个工作日提交工单。"
    evidence = [evidence_view(admitted_search_hit(matched_text=text, context_text=text))]
    if kind == "ambiguous":
        evidence.append(
            evidence_view(
                admitted_search_hit(chunk_id="other", matched_text=text, context_text=text)
            )
        )
    question = "设备修理啥时候交单子？"
    plan = build_task_plan(RuleFirstQueryAnalyzer().analyze(question, user_context()))
    wire = {
        "decision": "read",
        "need_id": "N1",
        "query": "",
        "evidence_id": "E999" if kind == "unknown_id" else "",
        "evidence_quote": "原文不存在的说法。" if kind == "invented" else text,
    }
    adviser = TaskAdvisor(
        model="stub", chat_fn=lambda *a, **kw: json.dumps(wire, ensure_ascii=False)
    )
    result = adviser.recover(question, plan, evidence, missing_ids=["N1"])
    assert (result.status == "accepted") == (kind == "unique")
    if kind == "unique":
        assert result.citation_id == evidence[0].citation_id


def test_controller_never_certifies_advisory_relevance_for_any_builder(
    snapshot_factory, document_factory, chunk_factory
):
    from app.agent.runner_v2 import ExtractiveResponseBuilder

    text = "设备维修需要提前两个工作日提交工单。"
    runner, _ = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text
    )
    wire = {
        "decision": "read",
        "need_id": "N1",
        "query": "",
        "evidence_id": "E1",
        "evidence_quote": text,
    }
    runner.controller = V2AgentController(
        recovery_advisor=TaskAdvisor(
            model="stub", chat_fn=lambda *a, **kw: json.dumps(wire, ensure_ascii=False)
        )
    )
    runner.response_builder = ExtractiveResponseBuilder()
    response = runner.run("设备修理啥时候交单子？", user_context())
    assert (
        response.mode == "partial"
        and response.trace["controller_stop_reason"] == "partial_evidence"
    )


@pytest.mark.parametrize(
    "question,text",
    [
        ("2026年设备维修的流程？", "2025年设备维修需要提交工单。"),
        ("《设备维修制度》怎么修？", "餐券制度说明设备维修无需申请。"),
        (
            "Berlin office grade G8 reimbursement?",
            "Paris office grade G8 reimbursement is available.",
        ),
    ],
)
def test_advisory_partial_does_not_override_literal_scope(question, text):
    from app.agent.evidence_relevance import has_query_anchor_support

    hit = admitted_search_hit(matched_text=text, context_text=text)
    assert not has_query_anchor_support(question, hit, advisory_partial=True)
