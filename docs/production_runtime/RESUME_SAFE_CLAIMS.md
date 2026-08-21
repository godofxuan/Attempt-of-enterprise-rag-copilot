# Resume-Safe Claims

Candidates become usable only when the final commit and CI evidence are linked.

## Evidence-supported candidates

1. Implemented a restart-recoverable `DurableAccessRequestWorkflow` for one
   access-request DRAFT operation; resume revalidates tenant, reviewer, role,
   ACL/policy, expiry, and tool-argument hash.
2. Added database CAS ownership, expiring leases, and owner-token/version
   fencing so concurrent resume attempts cannot both finalize one approval.
3. Atomically records the local draft effect command, one immutable completion
   outbox envelope, and approval final state; retries project completion events
   with stable idempotency keys.
4. Added deterministic `DENY > ASK > ALLOW` tool policy and typed lifecycle hooks to
   `ToolGateway`; sensitive draft creation requires approval, unknown/admin tools
   fail closed, and duplicate draft execution is idempotent in the tested SQLite
   transaction.
5. Added operation-specific typed OTel allowlists: unknown/free-text attributes
   are dropped, identity is hashed, and content capture remains off.
6. Added a versioned `enterprise.agent-harness-request/result` CLI contract with
   deterministic mock mode and optional local-model mode; both construct trusted
   identity fixtures and use the normal orchestrator, gateway, ACL, Guard, and
   citation path.

## Required qualifiers

- Say “service-object/process reconstruction test,” not production HA.
- Say “atomic local draft/completion/approval transaction plus idempotent
  trajectory projection,” not distributed exactly-once.
- Say “PostgreSQL checkpointer integration test” only after its CI job passes.
- Say “local/in-process harness contract,” not hosted evaluation service.
- LangGraph is not an answer-quality or latency improvement.

## Forbidden claims

Do not claim a general durable Agent runtime, arbitrary-tool durability,
Claude Code integration, production-ready HITL, distributed exactly-once,
multi-host HA, production IAM, remote MCP, general prompt-injection safety,
production SLOs, or quality gains from this runtime work.
