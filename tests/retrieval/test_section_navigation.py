import pytest
from pydantic import ValidationError

from app.agent.tools_v2 import V2ToolRegistry
from app.domain.agent import AgentAction, BudgetState
from app.domain.queries import FindMatch, FindRequest, QueryFilters
from app.retrieval.navigation import DocumentNavigator
from tests.v2_test_support import user_context


def test_section_mode_requires_anchor():
    with pytest.raises(ValidationError, match="anchor"):
        FindRequest(
            user=user_context(), doc_id="doc-a", pattern="materials", match_mode="anchor_section"
        )


def test_section_mode_does_not_require_repeated_topic_and_binding_rejects_other_section(
    chunk_factory,
    document_factory,
    snapshot_factory,
    monkeypatch,
):
    chunks = [
        chunk_factory(chunk_id="anchor", text="报销需要发票。"),
        chunk_factory(chunk_id="tail", text="还需提供行程单。"),
        chunk_factory(chunk_id="other", text="OTHER_SECTION_SENTINEL", section_path=["Other"]),
    ]
    snapshot = snapshot_factory(
        chunks, documents=[document_factory(text="Policy")], run_id="run-one"
    )
    navigator = DocumentNavigator(snapshot)
    request = FindRequest(
        user=user_context(),
        doc_id="doc-a",
        pattern="报销",
        max_results=20,
        match_mode="anchor_section",
        anchor_chunk_id="anchor",
        filters=QueryFilters(),
    )
    raw = navigator.find(request)
    assert {match.chunk_id for match in raw.matches} == {"anchor", "tail"}
    forged = FindMatch(
        doc_id="doc-a", chunk_id="other", section_path=["Other"], preview="OTHER_SECTION_SENTINEL"
    )
    monkeypatch.setattr(navigator, "find", lambda _: raw.model_copy(update={"matches": [forged]}))
    result = V2ToolRegistry(navigator, clock_ms=lambda: 1).run(
        AgentAction(sequence=1, tool="find", purpose="Read same section", find_request=request),
        BudgetState(deadline_at_ms=1000),
    )
    assert result.status == "error" and result.visible_count == 0
    assert "OTHER_SECTION_SENTINEL" not in result.model_dump_json()
