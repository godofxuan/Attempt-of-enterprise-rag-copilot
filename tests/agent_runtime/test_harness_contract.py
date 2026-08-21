from __future__ import annotations

import json
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from app.agent_runtime.evalops_artifact import AgentRunArtifactV1, verify_agent_run_artifact
from app.agent_runtime.harness_contract import (
    AgentHarnessRunner,
    HarnessRequestV1,
)
from app.agent_runtime.telemetry import AgentTelemetry, build_tracer_provider


ROOT = Path(__file__).resolve().parents[2]


def test_deterministic_harness_uses_gateway_guard_trajectory_and_trace(tmp_path) -> None:
    exporter = InMemorySpanExporter()
    runner = AgentHarnessRunner(
        state_root=tmp_path,
        git_sha="a" * 40,
        telemetry=AgentTelemetry(build_tracer_provider(exporter)),
    )

    output = runner.run(
        HarnessRequestV1(
            case_id="case-one",
            question="What is the remote policy?",
        )
    )

    artifact = AgentRunArtifactV1.model_validate(output.trajectory_artifact)
    assert output.terminal_state == "answered"
    assert output.attempt_id
    assert output.citations
    assert any(event["event_type"] == "tool.completed" for event in output.tool_events)
    assert output.policy_decisions[0]["decision"] == "ALLOW"
    assert output.policy_decisions[0]["tool_name"] == "search"
    assert output.trace_id == artifact.trace_context.trace_id
    assert output.root_span_id == artifact.trace_context.root_span_id
    assert output.propagated_traceparent.startswith(f"00-{output.trace_id}-")
    assert verify_agent_run_artifact(artifact) is True
    assert {
        "agent.harness.api",
        "agent.run",
        "agent.policy.decision",
        "agent.tool.search",
        "agent.citation.verify",
        "agent.evalops.export",
    }.issubset({span.name for span in exporter.get_finished_spans()})


def test_harness_contract_rejects_client_selected_identity_and_extra_secrets() -> None:
    with pytest.raises(ValidationError):
        HarnessRequestV1.model_validate(
            {
                "case_id": "case-one",
                "question": "policy?",
                "tenant_fixture": "attacker-tenant",
            }
        )
    with pytest.raises(ValidationError):
        HarnessRequestV1.model_validate(
            {
                "case_id": "case-one",
                "question": "policy?",
                "api_key": "TEST-SECRET",
            }
        )


def test_harness_serialized_output_has_versions_and_no_policy_identity_plaintext(tmp_path) -> None:
    output = AgentHarnessRunner(state_root=tmp_path, git_sha="b" * 40).run(
        HarnessRequestV1(case_id="case-two", question="What is the remote policy?")
    )
    serialized = output.model_dump_json()

    assert '"schema_version":"1.0"' in serialized
    assert "authorization" not in serialized.lower()
    assert "api_key" not in serialized.lower()
    assert all("tenant_hash" not in item for item in output.policy_decisions)


def test_same_case_can_run_twice_without_reusing_trajectory_identity(tmp_path) -> None:
    runner = AgentHarnessRunner(state_root=tmp_path, git_sha="c" * 40)
    request = HarnessRequestV1(
        case_id="repeatable-case",
        question="What is the remote policy?",
    )

    first = runner.run(request)
    second = runner.run(request)

    assert first.terminal_state == second.terminal_state == "answered"
    assert first.attempt_id != second.attempt_id
    assert (
        first.trajectory_artifact["session_id"]
        != second.trajectory_artifact["session_id"]
    )


def test_public_harness_schemas_exactly_match_code_contracts() -> None:
    schema_root = ROOT / "docs" / "production_runtime" / "schemas"

    assert json.loads(
        (schema_root / "agent_harness_request_v1.schema.json").read_text(
            encoding="utf-8"
        )
    ) == HarnessRequestV1.model_json_schema()
    from app.agent_runtime.harness_contract import HarnessOutputV1

    assert json.loads(
        (schema_root / "agent_harness_result_v1.schema.json").read_text(
            encoding="utf-8"
        )
    ) == HarnessOutputV1.model_json_schema()
