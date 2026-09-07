from __future__ import annotations

import pytest

from app.agent.generation_v2 import GenerationV2ResponseBuilder
from app.agent.runner_v2 import V2AgentRunner
from app.agent.tools_v2 import V2ToolRegistry
from tests.agent_v2.test_generation_v2 import CapturingChat, valid_payload
from tests.v2_test_support import RecordingNavigator, search_hit, search_result, user_context


@pytest.mark.parametrize(
    "payload,mode,reason",
    [
        (RuntimeError("fixture transport failure"), "system", "system_error"),
        (
            valid_payload(claim_text="Remote work is allowed for 99 days."),
            "partial",
            "partial_evidence",
        ),
        (valid_payload(), "answered", "completed"),
    ],
)
def test_runtime_trace_records_published_outcome_not_only_controller_intent(payload, mode, reason):
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])
    runner = V2AgentRunner(
        registry=V2ToolRegistry(navigator, clock_ms=lambda: 0.0),
        response_builder=GenerationV2ResponseBuilder(
            chat_fn=CapturingChat(payload),
            model="fixture",
            max_attempts=1,
        ),
        clock_ms=lambda: 0.0,
    )
    response = runner.run("What is the remote work limit?", user_context())
    assert response.mode == mode
    assert response.stop_reason == reason
    assert response.trace["stop_reason"] == reason
    assert response.trace["final_mode"] == mode
    assert response.trace["controller_stop_reason"] == "completed"
    assert response.trace["steps"][-1]["tool"] == "answer"
