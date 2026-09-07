import pytest

from app.agent.tools_v2 import V2ToolRegistry
from app.domain.agent import AgentAction, BudgetState
from app.domain.queries import FindRequest, OpenRequest
from app.retrieval.navigation import DocumentNavigator
from tests.retrieval.test_navigation import USER, _navigation_snapshot


@pytest.mark.parametrize(
    "changes",
    [
        {"content": "Obsolete policy permits 9000 yuan."},
        {"target_id": "another-target"},
        {"request_id": "another-request"},
        {"source_path": "another/source.md"},
        {"truncated": True},
    ],
)
def test_open_rejects_result_not_bound_to_requested_snapshot(
    chunk_factory, document_factory, snapshot_factory, monkeypatch, changes
):
    snapshot = _navigation_snapshot(chunk_factory, document_factory, snapshot_factory)
    navigator = DocumentNavigator(snapshot)
    request = OpenRequest(user=USER, target_type="document", target_id="doc-a")
    raw = navigator.open(request)
    monkeypatch.setattr(navigator, "open", lambda _: raw.model_copy(update=changes))
    execution = V2ToolRegistry(navigator, clock_ms=lambda: 1).run(
        AgentAction(sequence=1, tool="open", purpose="Inspect policy", open_request=request),
        BudgetState(deadline_at_ms=1000),
    )
    assert execution.status == "error"
    assert execution.visible_count == 0
    assert "9000" not in execution.model_dump_json()


def test_find_rejects_preview_not_in_bound_chunk(
    chunk_factory, document_factory, snapshot_factory, monkeypatch
):
    snapshot = _navigation_snapshot(chunk_factory, document_factory, snapshot_factory)
    navigator = DocumentNavigator(snapshot)
    request = FindRequest(user=USER, doc_id="doc-a", pattern="approval")
    raw = navigator.find(request)
    forged = raw.matches[0].model_copy(update={"preview": "Obsolete approval limit 9000"})
    monkeypatch.setattr(navigator, "find", lambda _: raw.model_copy(update={"matches": [forged]}))
    execution = V2ToolRegistry(navigator, clock_ms=lambda: 1).run(
        AgentAction(sequence=1, tool="find", purpose="Locate policy", find_request=request),
        BudgetState(deadline_at_ms=1000),
    )
    assert execution.status == "error"
    assert execution.visible_count == 0


@pytest.mark.parametrize(
    "tool,target_type,target_id",
    [
        ("open", "document", "doc-a"),
        ("open", "chunk", "chunk-a-1"),
        ("open", "parent", "parent-a"),
        ("find", None, None),
    ],
)
def test_matching_navigation_result_remains_available(
    chunk_factory, document_factory, snapshot_factory, tool, target_type, target_id
):
    snapshot = _navigation_snapshot(chunk_factory, document_factory, snapshot_factory)
    navigator = DocumentNavigator(snapshot)
    request = (
        OpenRequest(user=USER, target_type=target_type, target_id=target_id, max_chars=30)
        if tool == "open"
        else FindRequest(user=USER, doc_id="doc-a", pattern="approval")
    )
    action = AgentAction(
        sequence=1, tool=tool, purpose="Inspect policy", **{f"{tool}_request": request}
    )
    execution = V2ToolRegistry(navigator, clock_ms=lambda: 1).run(
        action, BudgetState(deadline_at_ms=1000)
    )
    assert execution.status == "ok"
    assert execution.visible_count > 0


def test_registry_rejects_replaced_snapshot_even_for_identical_content(
    chunk_factory, document_factory, snapshot_factory
):
    from dataclasses import replace

    snapshot = _navigation_snapshot(chunk_factory, document_factory, snapshot_factory)
    navigator = DocumentNavigator(snapshot)
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 1)
    navigator.snapshot = replace(snapshot)
    request = OpenRequest(user=USER, target_type="document", target_id="doc-a")
    result = registry.run(
        AgentAction(sequence=1, tool="open", purpose="Inspect policy", open_request=request),
        BudgetState(deadline_at_ms=1000),
    )
    assert result.status == "error"
    assert result.visible_count == 0


def test_old_authorized_response_cannot_cross_tenant_boundary(
    chunk_factory, document_factory, snapshot_factory, monkeypatch
):
    snapshot = _navigation_snapshot(chunk_factory, document_factory, snapshot_factory)
    navigator = DocumentNavigator(snapshot)
    request = OpenRequest(user=USER, target_type="document", target_id="doc-a")
    raw = navigator.open(request)
    other = request.model_copy(update={"user": USER.model_copy(update={"tenant_id": "other"})})
    monkeypatch.setattr(navigator, "open", lambda _: raw)
    result = V2ToolRegistry(navigator, clock_ms=lambda: 1).run(
        AgentAction(sequence=1, tool="open", purpose="Inspect policy", open_request=other),
        BudgetState(deadline_at_ms=1000),
    )
    assert result.status == "error"
    assert result.visible_count == 0
