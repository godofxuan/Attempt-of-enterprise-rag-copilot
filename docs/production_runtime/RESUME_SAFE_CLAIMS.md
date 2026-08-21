# Resume-Safe Claims

Candidates become usable only when the final commit and CI evidence are linked.

## Evidence-supported candidates

1. Implemented a LangGraph checkpoint/interrupt workflow that reconstructs from
   file-backed SQLite after service-object restart, revalidates reviewer and
   tool-call bindings, and resumes a draft-only approval action.
2. Added deterministic `ALLOW/ASK/DENY` tool policy and typed lifecycle hooks to
   `ToolGateway`; sensitive draft creation requires approval, unknown/admin tools
   fail closed, and duplicate draft execution is idempotent in the tested SQLite
   transaction.
3. Added W3C Trace Context and privacy-default OTel spans connecting harness,
   Agent, policy, tool, citation, and EvalOps operations while retaining the
   separate hash-linked trajectory.
4. Added a versioned `enterprise.agent-harness-request/result` CLI contract with
   deterministic mock mode and optional local-model mode; both construct trusted
   identity fixtures and use the normal orchestrator, gateway, ACL, Guard, and
   citation path.

## Required qualifiers

- Say “service-object/process reconstruction test,” not production HA.
- Say “idempotent draft transaction,” not exactly-once.
- Say “PostgreSQL checkpointer integration test” only after its CI job passes.
- Say “local/in-process harness contract,” not hosted evaluation service.
- LangGraph is not an answer-quality or latency improvement.

## Forbidden claims

Do not claim Claude Code integration, production-ready HITL, distributed
exactly-once, production IAM, remote MCP, general prompt-injection safety,
production SLOs, or quality gains from this runtime work.
