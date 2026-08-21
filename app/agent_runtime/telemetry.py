from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final, Literal

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult, SpanProcessor
from opentelemetry.trace import Link, SpanContext, TraceFlags, TraceState
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic import BaseModel, ConfigDict, Field

TRACE_SCHEMA_VERSION: Final[Literal["enterprise.agent.telemetry/1.0"]] = (
    "enterprise.agent.telemetry/1.0"
)
OTEL_SEMCONV_VERSION = "1.44.0"
CONTENT_CAPTURE_POLICY: Final[Literal["off"]] = "off"

SpanOperation = Literal[
    "api",
    "agent",
    "model",
    "tool",
    "policy",
    "interrupt",
    "resume",
    "side_effect",
    "completion",
    "citation",
    "evalops",
]

_ATTRIBUTE_RULES: dict[SpanOperation, dict[str, str]] = {
    "api": {"case": "hash", "tenant": "hash", "http.status_code": "number"},
    "agent": {
        "case": "hash",
        "tenant": "hash",
        "user": "hash",
        "run": "hash",
        "runtime.mode": "runtime_mode",
    },
    "model": {"model.name": "hash"},
    "tool": {
        "tool.name": "tool_name",
        "tool.arguments.sha256": "sha256",
        "tenant": "hash",
        "user": "hash",
        "run": "hash",
        "tool.status": "status",
    },
    "policy": {
        "tool.name": "tool_name",
        "tenant": "hash",
        "user": "hash",
        "run": "hash",
        "policy.decision": "decision",
        "policy.reason_code": "hash",
    },
    "interrupt": {
        "tool.name": "tool_name",
        "run": "hash",
        "approval.status": "status",
    },
    "resume": {
        "tenant": "hash",
        "run": "hash",
        "approval.outcome": "status",
        "approval.version": "number",
    },
    "side_effect": {
        "tool.name": "tool_name",
        "side_effect.status": "status",
        "approval.version": "number",
    },
    "completion": {
        "completion.status": "status",
        "completion.event_count": "number",
        "approval.version": "number",
    },
    "citation": {"citation.count": "number"},
    "evalops": {
        "artifact.schema": "artifact_schema",
        "runtime.mode": "runtime_mode",
    },
}

_SAFE_TOOL_NAMES = {
    "search",
    "find",
    "open",
    "create_access_request_draft",
    "export_evidence_bundle",
}
_SAFE_STATUSES = {
    "PENDING",
    "RESUMING",
    "COMPLETED",
    "REJECTED",
    "EXPIRED",
    "FAILED_RECOVERABLE",
    "COMMITTED",
    "RECORDED",
    "DELIVERED",
    "ALREADY_RESUMING",
    "ALREADY_COMPLETED",
}


class TraceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    trace_schema_version: Literal["enterprise.agent.telemetry/1.0"] = TRACE_SCHEMA_VERSION
    content_capture_policy: Literal["off"] = CONTENT_CAPTURE_POLICY


class FailOpenSpanProcessor(SpanProcessor):
    """Exporter failures are telemetry loss, never business failure."""

    def __init__(self, exporter: SpanExporter) -> None:
        self.exporter = exporter
        self.export_failures = 0

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        return None

    def on_end(self, span: ReadableSpan) -> None:
        try:
            result = self.exporter.export((span,))
            if result == SpanExportResult.FAILURE:
                self.export_failures += 1
        except Exception:
            self.export_failures += 1

    def shutdown(self) -> None:
        try:
            self.exporter.shutdown()
        except Exception:
            self.export_failures += 1

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        try:
            return bool(self.exporter.force_flush(timeout_millis))
        except Exception:
            self.export_failures += 1
            return False


def build_tracer_provider(exporter: SpanExporter | None = None) -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "enterprise-rag-agent-runtime",
                "service.version": "vnext",
            }
        )
    )
    if exporter is not None:
        provider.add_span_processor(FailOpenSpanProcessor(exporter))
    return provider


class AgentTelemetry:
    def __init__(self, provider: TracerProvider | None = None) -> None:
        self.provider = provider or build_tracer_provider()
        self.tracer = self.provider.get_tracer(
            "app.agent_runtime",
            instrumenting_library_version="1.0",
            schema_url="https://opentelemetry.io/schemas/1.44.0",
        )
        self.propagator = TraceContextTextMapPropagator()

    @contextmanager
    def span(
        self,
        name: str,
        *,
        operation: SpanOperation,
        attributes: Mapping[str, Any] | None = None,
        traceparent: str | None = None,
        continuation: TraceIdentity | None = None,
    ) -> Iterator[TraceIdentity]:
        parent = self.extract(traceparent) if traceparent else None
        links = [Link(_span_context(continuation))] if continuation is not None else None
        token = otel_context.attach(parent) if parent is not None else None
        try:
            with self.tracer.start_as_current_span(
                name,
                links=links,
                attributes={
                    "gen_ai.operation.name": _gen_ai_operation(operation),
                    "enterprise.agent.operation": operation,
                    "enterprise.agent.trace_schema": TRACE_SCHEMA_VERSION,
                    "enterprise.agent.content_capture": CONTENT_CAPTURE_POLICY,
                    "enterprise.agent.otel_semconv_version": OTEL_SEMCONV_VERSION,
                    **sanitize_span_attributes(attributes or {}, operation=operation),
                },
            ) as current:
                context = current.get_span_context()
                yield TraceIdentity(
                    trace_id=format(context.trace_id, "032x"),
                    span_id=format(context.span_id, "016x"),
                )
        finally:
            if token is not None:
                otel_context.detach(token)

    def inject(self) -> str:
        carrier: dict[str, str] = {}
        self.propagator.inject(carrier)
        return carrier.get("traceparent", "")

    def extract(self, traceparent: str) -> Context:
        return self.propagator.extract({"traceparent": traceparent})

    @staticmethod
    def add_event(
        name: str,
        *,
        operation: SpanOperation,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        current = trace.get_current_span()
        if current.is_recording():
            current.add_event(
                name,
                sanitize_span_attributes(attributes or {}, operation=operation),
            )


def sanitize_span_attributes(
    values: Mapping[str, Any],
    *,
    operation: SpanOperation,
) -> dict[str, Any]:
    """Project only typed, operation-specific metadata into a span.

    Unknown keys and structured values are dropped. This allowlist is the
    privacy boundary; key-name denylisting is deliberately not used.
    """

    sanitized: dict[str, Any] = {}
    rules = _ATTRIBUTE_RULES[operation]
    for raw_key, raw_value in values.items():
        key = str(raw_key)[:128]
        rule = rules.get(key)
        if rule is None or raw_value is None:
            continue
        if rule == "hash" and isinstance(raw_value, str):
            sanitized[f"{key}.sha256"] = _sha256(raw_value)
        elif rule == "sha256" and isinstance(raw_value, str) and _is_sha256(raw_value):
            sanitized[key] = raw_value
        elif (
            rule == "number"
            and isinstance(raw_value, (int, float))
            and not isinstance(raw_value, bool)
        ):
            sanitized[key] = raw_value
        elif rule == "tool_name" and raw_value in _SAFE_TOOL_NAMES:
            sanitized[key] = raw_value
        elif rule == "runtime_mode" and raw_value in {"deterministic_mock", "local_ollama"}:
            sanitized[key] = raw_value
        elif rule == "decision" and raw_value in {"ALLOW", "ASK", "DENY"}:
            sanitized[key] = raw_value
        elif rule == "status" and raw_value in _SAFE_STATUSES:
            sanitized[key] = raw_value
        elif rule == "artifact_schema" and raw_value == "enterprise.agent-run/1.0":
            sanitized[key] = raw_value
        else:
            continue
    return sanitized


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _gen_ai_operation(operation: str) -> str:
    return {
        "agent": "invoke_agent",
        "model": "chat",
        "tool": "execute_tool",
        "citation": "retrieval",
    }.get(operation, operation)


def _span_context(identity: TraceIdentity) -> SpanContext:
    return SpanContext(
        trace_id=int(identity.trace_id, 16),
        span_id=int(identity.span_id, 16),
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )


__all__ = [
    "AgentTelemetry",
    "CONTENT_CAPTURE_POLICY",
    "FailOpenSpanProcessor",
    "OTEL_SEMCONV_VERSION",
    "SpanOperation",
    "TRACE_SCHEMA_VERSION",
    "TraceIdentity",
    "build_tracer_provider",
    "sanitize_span_attributes",
]
