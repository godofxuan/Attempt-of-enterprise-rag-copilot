# OpenTelemetry and GenAI Trace Policy

Implementation: `app/agent_runtime/telemetry.py`.

## Contract

- W3C `traceparent` is extracted at the harness/API boundary and injected for
  downstream calls.
- Spans cover API, agent run, tool, policy, interrupt/resume-capable operations,
  citation verification, and EvalOps export. Deterministic mode performs no LLM
  call and therefore does not fabricate a model span.
- Resume can create a new trace with a `Span Link` to the earlier trace/span.
- `enterprise.agent-run/1.0` includes a finite 32-hex trace ID, 16-hex root span
  ID, trace schema, content policy, and sanitized model/tool metadata.

## Semantic-convention pin

OTel API/SDK is pinned to `1.44.0`. The implementation uses
`gen_ai.operation.name` only for a small operation mapping and places project
semantics under `enterprise.agent.*`. Upgrade requires tests because GenAI
semantic conventions can evolve independently of this artifact schema.

## Privacy default

Content capture is `off`. Each operation has an exact typed attribute allowlist.
Unknown keys, nested objects, lists, and free text are dropped by default;
accepted string values are either finite enums or hashes. Tenant/user/run/case
and model names are hashed. A key such as `message`, `query`, `document`, or
`response_text` is rejected even when its name appears neutral, and a field
allowed for one operation is rejected on another operation. No prompt, answer,
evidence, exception message, or tool output body is sent to OTel by this
implementation.

High-cardinality trace and identity values are span attributes only; this work
does not expose them as Prometheus labels.

## Failure semantics

`FailOpenSpanProcessor` catches exporter export, flush, and shutdown exceptions.
With no exporter, the local SDK still creates valid trace/span IDs. Telemetry
loss must be monitored in a deployment, but it does not fail the RAG response or
approved draft transaction.

Trajectory and OTel have different jobs: trajectory is a hash-linked semantic
record; OTel is a best-effort distributed performance/correlation signal.
