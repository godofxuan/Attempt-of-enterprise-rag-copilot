from app.agent.tools_v2 import V2ToolRegistry
from app.domain.agent import AgentAction, BudgetState
from app.domain.queries import OpenRequest, QueryFilters
from app.retrieval.navigation import DocumentNavigator
from tests.v2_test_support import user_context


def test_window_reads_tail_and_rejects_forged_offset(
    chunk_factory, document_factory, snapshot_factory, monkeypatch
):
    text = "背景说明。" * 600 + "还需主管确认后交人事登记。"
    chunk = chunk_factory(chunk_id="anchor", text=text)
    snapshot = snapshot_factory([chunk], documents=[document_factory(text=text)], run_id="run-one")
    nav = DocumentNavigator(snapshot)
    request = OpenRequest(
        user=user_context(),
        target_type="chunk",
        target_id="anchor",
        start_char=3000,
        max_chars=100,
        anchor_chunk_id="anchor",
        filters=QueryFilters(),
    )
    result = nav.open(request)
    assert result.content == text[3000:3100]
    assert result.start_char == 3000 and result.truncated
    monkeypatch.setattr(nav, "open", lambda _: result.model_copy(update={"start_char": 0}))
    execution = V2ToolRegistry(nav, clock_ms=lambda: 1).run(
        AgentAction(sequence=1, tool="open", purpose="read located tail", open_request=request),
        BudgetState(deadline_at_ms=1000),
    )
    assert execution.status == "error" and execution.visible_count == 0


def test_offset_outside_resource_is_not_empty_evidence(
    chunk_factory, document_factory, snapshot_factory
):
    nav = DocumentNavigator(
        snapshot_factory(
            [chunk_factory(chunk_id="chunk-a", text="Short.")],
            documents=[document_factory(text="Short.")],
        )
    )
    result = nav.open(
        OpenRequest(
            user=user_context(),
            target_type="chunk",
            target_id="chunk-a",
            start_char=100,
            max_chars=10,
        )
    )
    assert result.code == "not_found"


def test_preview_window_preserves_complete_leading_condition():
    from app.retrieval.navigation import _preview_start

    text = "背景。" * 300 + "若未经主管确认，不得直接交人事登记。"
    start = _preview_start(text, "人事登记")
    assert start > 0
    assert "若未经主管确认，不得" in text[start:]
