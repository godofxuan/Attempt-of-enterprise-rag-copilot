"""Task/evidence flow acceptance probes, independent of real model quality."""

import json

from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.retrieval import conftest as retrieval_fixtures
from tests.v2_test_support import user_context

chunk_factory = retrieval_fixtures.chunk_factory
document_factory = retrieval_fixtures.document_factory
snapshot_factory = retrieval_fixtures.snapshot_factory


def test_generic_process_tail_is_read_without_completeness_keyword(
    snapshot_factory,
    document_factory,
    chunk_factory,
):
    def choose(records):
        item = next((r for r in records if "主管确认" in r["matched_text"]), records[0])
        return item["matched_text"], item["source_id"]

    runner, packets = runner_fixture(
        snapshot_factory,
        document_factory,
        chunk_factory,
        texts=["年假申请需要提交申请。", "还需主管确认后交人事登记。"],
        claim=choose,
    )
    response = runner.run("年假怎么申请？", user_context())
    assert any("主管确认" in r["matched_text"] for p in packets for r in p)
    assert "主管确认" in response.answer
    assert response.trace["budget"]["find_calls"] <= 1
    assert response.trace["budget"]["open_calls"] <= 2


def test_generation_receives_same_task_ids_as_controller(
    snapshot_factory,
    document_factory,
    chunk_factory,
):
    runner, _ = runner_fixture(
        snapshot_factory,
        document_factory,
        chunk_factory,
        texts=["入职需要身份证。入职试用期为三个月。"],
        claim="入职需要身份证。",
    )
    captured = []
    original = runner.response_builder.chat_fn

    def capture(model, messages, **kwargs):
        captured.append(json.loads(messages[1]["content"].splitlines()[1]))
        return original(model, messages, **kwargs)

    runner.response_builder.chat_fn = capture
    response = runner.run("入职需要哪些材料，试用期多久？", user_context())
    assert len(captured[0]["request_needs"]) == 2
    assert [n["id"] for n in captured[0]["request_needs"]] == ["N1", "N2"]
    coverage = response.trace["task_coverage"]
    assert coverage["requested"] == 2 and coverage["answer_missing"] == 1
    assert coverage["search_attempts"] >= 1
    assert response.mode == "partial"


def test_plan_keeps_unknown_distinct_from_search_attempts():
    from app.agent.controller_v2 import V2AgentController
    from app.agent.query_analysis import RuleFirstQueryAnalyzer

    user = user_context()
    analysis = RuleFirstQueryAnalyzer().analyze("入职需要哪些材料，试用期多久？", user)
    state = V2AgentController().initialize(analysis, user)
    assert [n.need_id for n in state.task_plan.needs] == ["N1", "N2"]
    assert all(not n.evidence_ids and not n.answer_claim_ids for n in state.task_plan.needs)
    assert all(n.search_attempts == 0 for n in state.task_plan.needs)


def test_open_evidence_has_packet_room_before_redundant_search_hits():
    from app.agent.evidence_ledger import build_ledger
    from app.agent.generation_v2 import _build_prompt_sources
    from tests.agent_v2.test_generation_v2 import state_with_evidence
    from tests.v2_test_support import admitted_search_hit

    state = state_with_evidence(include_open=True)
    evidence = {"answer": [admitted_search_hit(chunk_id=f"chunk-{i}") for i in range(8)]}
    state = state.model_copy(
        update={"evidence_by_aspect": evidence, "ledger": build_ledger(state.analysis, evidence)}
    )
    sources = _build_prompt_sources(state)
    assert any(source.delivered.opened for source in sources)
    assert len(sources) <= 8


def test_single_process_relation_cannot_match_only_topic_or_other_subject():
    from app.agent.evidence_relevance import has_query_anchor_support
    from tests.v2_test_support import admitted_search_hit

    for text in ["年假按规定执行。", "采购需要提交申请。", "年假记录归档。"]:
        hit = admitted_search_hit(matched_text=text, context_text=text)
        assert not has_query_anchor_support("年假怎么申请？", hit)


def test_controller_opens_located_window_inside_long_hit(
    snapshot_factory,
    document_factory,
    chunk_factory,
):
    question = "年假怎么申请？"
    text = "年假申请需要提交申请。" + "背景说明。" * 700 + question + "还需主管确认后交人事登记。"

    def choose(records):
        item = next(
            (record for record in records if "主管确认" in record["matched_text"]), records[0]
        )
        return item["matched_text"], item["source_id"]

    runner, packets = runner_fixture(
        snapshot_factory,
        document_factory,
        chunk_factory,
        texts=[text],
        claim=choose,
    )
    response = runner.run(question, user_context())
    assert any("主管确认" in record["matched_text"] for packet in packets for record in packet)
    assert response.trace["budget"]["open_calls"] == 1
    assert response.mode == "partial"
