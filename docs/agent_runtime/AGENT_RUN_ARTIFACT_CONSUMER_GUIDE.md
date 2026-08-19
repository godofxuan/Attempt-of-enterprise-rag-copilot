# Agent Run Artifact Consumer Guide

## Contract

The artifact identifies itself as `enterprise.agent-run/1.0`. The normative
JSON Schema is `docs/agent_runtime/schemas/agent_run_artifact_v1.schema.json`;
the Pydantic producer and verifier live in
`app/agent_runtime/evalops_artifact.py`. Consumers must reject unknown major
versions and should retain the original bytes alongside parsed records.

## Top-level fields

| Field | Meaning |
|---|---|
| `run_id` | Producer-side run identity. In the current sample/exporter it equals `session_id`; this is a project simplification, not a universal EvalOps identity model. |
| `case_id` | Evaluation case or dataset example supplied by the exporter. It is not the interactive session ID. |
| `session_id`, `trace_id` | Agent session and trace correlation identities. |
| `git_sha`, `created_at` | Source revision and artifact creation time. |
| `input`, `output` | Redacted consumer-facing request and terminal output. |
| `trajectory` | Ordered semantic events with per-event chain hashes. |
| `retrieval`, `evidence` | Tool-step summaries and admitted evidence summaries. |
| `usage`, `terminal` | Recorded counts/cost fields and the terminal outcome. |
| `source_trajectory_root_hash` | Expected hash of the final source trajectory event. |
| `artifact_sha256` | SHA-256 over canonical JSON excluding this field. |

Future integration may split an EvalOps batch identity (`eval_run_id`) from an
Agent session identity (`agent_session_id`). Version 1.0 deliberately does not
make that schema change during closeout.

## Ordering and verification

`trajectory` is ordered by `sequence`, starting at 1 without gaps. Every event
must match the artifact `session_id` and `trace_id`. The first
`previous_hash` is null; every later value equals the preceding `event_hash`.
Recompute each event hash from canonical JSON with `event_hash` excluded, then
check the final hash against `source_trajectory_root_hash`. Finally recompute
`artifact_sha256` from canonical top-level JSON with `artifact_sha256`
excluded. The repository verifier performs all of these checks:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_agent_run_artifact `
  docs\agent_runtime\evidence\agent_run_artifact_sample_v1.json
```

Hash validity proves consistency of the supplied bytes; it does not prove that
the producer host was uncompromised or that storage is WORM.

## Expected consumer workflow

1. Validate JSON shape and exact schema name/version.
2. Enforce a maximum artifact size and event count before parsing deeply.
3. Verify event ordering, chain hashes, root hash, and artifact hash.
4. Index stable identities (`case_id`, `session_id`, `trace_id`, `git_sha`).
5. Derive metrics from typed event fields and terminal/retrieval summaries;
   never reinterpret missing values as zero.
6. Store verification status and the original artifact SHA with derived rows.
7. Quarantine invalid or unsupported artifacts instead of partially ingesting
   them.

## Privacy boundary

The current producer records semantic, consumer-facing payloads and expects
redaction before export. The schema permits open dictionaries in `input`,
`output`, event `payload`, `retrieval`, and `evidence`; schema validation alone
therefore does not prevent PII, secrets, source text, or tenant identifiers from
appearing. A real consumer must apply tenant-specific classification,
minimization, access control, retention, and deletion policy before durable
storage. The public sample contains synthetic content only.

## Known schema limitations

- `run_id == session_id` in the current producer; batch/eval and session IDs are
  not independently modeled.
- Payload dictionaries are intentionally open and not semantically versioned
  per event type.
- The hash chain is tamper-evident local evidence, not a signature, WORM store,
  or external timestamp authority.
- No encrypted envelope, tenant retention policy, distributed ordering, or
  cross-process durable execution guarantee is included.
- Cost and token fields are optional observations and may be zero when the
  deterministic runtime made no model call.
