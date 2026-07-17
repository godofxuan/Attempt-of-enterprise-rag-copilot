from __future__ import annotations

from app.agent.runner_v2 import V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from tests.v2_test_support import (
    RecordingNavigator,
    search_hit,
    search_result,
    user_context,
)


USER = user_context()


def test_denied_resource_never_enters_response_or_trace() -> None:
    denied_values = [
        "secret-board-chunk",
        "secret-board-doc",
        "Board Acquisition Secret",
        "vault/board-acquisition-secret.md",
        "Project NIGHTFALL acquisition price is 900 million",
        "board_only",
    ]
    navigator = RecordingNavigator(
        search_results=[
            search_result(
                [
                    search_hit(
                        chunk_id="visible-policy-chunk",
                        doc_id="visible-policy-doc",
                        source_path="documents/visible-policy.md",
                        matched_text="Visible policy requires manager approval.",
                        context_text="Visible policy requires manager approval.",
                    )
                ],
                denied_count=1,
            )
        ]
    )
    navigator.denied_debug_payload = dict(zip(denied_values, denied_values))
    runner = V2AgentRunner(
        registry=V2ToolRegistry(navigator, clock_ms=lambda: 0.0),
        clock_ms=lambda: 0.0,
    )

    response = runner.run("What approval is required?", USER)

    assert response.mode == "answered"
    serialized = response.model_dump_json()
    for denied in denied_values:
        assert denied not in serialized
    trace_json = str(response.trace)
    assert "visible-policy-chunk" not in trace_json
    assert "documents/visible-policy.md" not in trace_json
    assert "Visible policy requires" not in trace_json


def test_denied_only_outcome_has_no_denied_count_or_identifiers() -> None:
    navigator = RecordingNavigator(
        search_results=[
            search_result(
                [],
                stop_reason="no_visible_evidence",
                denied_count=7,
            )
        ]
    )
    runner = V2AgentRunner(
        registry=V2ToolRegistry(navigator, clock_ms=lambda: 0.0),
        clock_ms=lambda: 0.0,
    )

    response = runner.run("What is the restricted policy?", USER)

    assert response.mode == "permission"
    assert response.sources == []
    serialized = response.model_dump_json()
    assert "internal_denied_count" not in serialized
    assert "denied_count" not in serialized
    assert "7" not in str(response.trace)
