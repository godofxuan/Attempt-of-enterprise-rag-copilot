from __future__ import annotations

from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent_runtime.telemetry import (
    AgentTelemetry,
    FailOpenSpanProcessor,
    TraceIdentity,
    build_tracer_provider,
)


def test_w3c_traceparent_continues_and_nested_spans_share_trace() -> None:
    exporter = InMemorySpanExporter()
    telemetry = AgentTelemetry(build_tracer_provider(exporter))
    parent_trace = "1" * 32
    traceparent = f"00-{parent_trace}-{'2' * 16}-01"

    with telemetry.span("api", operation="api", traceparent=traceparent) as root:
        propagated = telemetry.inject()
        with telemetry.span("tool", operation="tool") as child:
            pass

    spans = exporter.get_finished_spans()
    assert root.trace_id == parent_trace
    assert child.trace_id == parent_trace
    assert child.span_id != root.span_id
    assert propagated.startswith(f"00-{parent_trace}-{root.span_id}-")
    assert next(span for span in spans if span.name == "tool").parent.span_id == int(
        root.span_id, 16
    )


def test_resume_uses_explicit_span_link_not_forged_parent() -> None:
    exporter = InMemorySpanExporter()
    telemetry = AgentTelemetry(build_tracer_provider(exporter))
    previous = TraceIdentity(trace_id="3" * 32, span_id="4" * 16)

    with telemetry.span("resume", operation="resume", continuation=previous) as resumed:
        pass

    span = exporter.get_finished_spans()[0]
    assert resumed.trace_id != previous.trace_id
    assert len(span.links) == 1
    assert format(span.links[0].context.trace_id, "032x") == previous.trace_id


def test_span_attributes_never_capture_content_or_credentials() -> None:
    exporter = InMemorySpanExporter()
    telemetry = AgentTelemetry(build_tracer_provider(exporter))

    with telemetry.span(
        "privacy",
        operation="model",
        attributes={
            "prompt.content": "PRIVATE QUESTION",
            "tool.output": "PRIVATE OUTPUT",
            "authorization": "Bearer TEST-SECRET",
            "tenant": "tenant-one",
            "model.name": "mock-model",
            "runtime": "deterministic_mock",
        },
    ):
        pass

    serialized = str(exporter.get_finished_spans()[0].attributes)
    assert "PRIVATE" not in serialized
    assert "TEST-SECRET" not in serialized
    assert "tenant-one" not in serialized
    assert "tenant.sha256" not in serialized
    assert "mock-model" not in serialized
    assert "model.name.sha256" in serialized
    assert "deterministic_mock" not in serialized


def test_typed_allowlist_drops_neutral_nested_list_and_exception_secrets() -> None:
    exporter = InMemorySpanExporter()
    telemetry = AgentTelemetry(build_tracer_provider(exporter))
    secrets = (
        "NEUTRAL-MESSAGE-SECRET",
        "QUERY-SECRET",
        "DOCUMENT-SECRET",
        "NESTED-SECRET",
        "LIST-SECRET",
        "EXCEPTION-SECRET",
        "TOOL-METADATA-SECRET",
    )

    with telemetry.span(
        "privacy-allowlist",
        operation="tool",
        attributes={
            "tool.name": "search",
            "tool.arguments.sha256": "a" * 64,
            "message": secrets[0],
            "query": secrets[1],
            "document": secrets[2],
            "nested": {"message": secrets[3]},
            "items": [secrets[4]],
            "exception.message": secrets[5],
            "tool.metadata": secrets[6],
        },
    ):
        pass

    serialized = str(exporter.get_finished_spans()[0].attributes)
    assert all(secret not in serialized for secret in secrets)
    assert "tool.name" in serialized
    assert "tool.arguments.sha256" in serialized


def test_attribute_allowed_for_one_span_type_is_denied_for_another() -> None:
    exporter = InMemorySpanExporter()
    telemetry = AgentTelemetry(build_tracer_provider(exporter))

    with telemetry.span(
        "wrong-surface",
        operation="citation",
        attributes={"tool.name": "search", "citation.count": 2},
    ):
        pass

    attributes = exporter.get_finished_spans()[0].attributes
    assert "tool.name" not in attributes
    assert attributes["citation.count"] == 2


def test_exporter_failure_is_fail_open_and_no_exporter_still_returns_ids() -> None:
    class BrokenExporter(SpanExporter):
        def export(self, spans):
            raise RuntimeError("collector unavailable")

        def shutdown(self):
            raise RuntimeError("collector unavailable")

    provider = build_tracer_provider(BrokenExporter())
    telemetry = AgentTelemetry(provider)
    with telemetry.span("business", operation="agent") as identity:
        business_result = "completed"

    processor = next(
        item
        for item in provider._active_span_processor._span_processors
        if isinstance(item, FailOpenSpanProcessor)
    )
    assert business_result == "completed"
    assert len(identity.trace_id) == 32
    assert processor.export_failures == 1

    without_exporter = AgentTelemetry()
    with without_exporter.span("local", operation="agent") as local:
        pass
    assert len(local.trace_id) == 32
    assert len(local.span_id) == 16
