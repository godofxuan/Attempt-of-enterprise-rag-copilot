# External Harness Pattern Decisions

Review date: 2026-08-21
Implementation baseline: `909a9710932c6c4744c462db0e33ed0d222ecb1a`
Working branch: `codex/durable-agent-runtime-and-policy-v1`

This record separates public design inspiration from code provenance. No Claude
Code implementation was copied and Claude Code is not a runtime dependency.

| Source | Decision | Pattern used or rejected | Project value | Provenance/license boundary |
|---|---|---|---|---|
| [Claude Code hooks](https://code.claude.com/docs/en/hooks) and [permissions](https://code.claude.com/docs/en/permissions) | ADAPT | Lifecycle names and the idea that pre-tool policy can block a call | Motivated `pre_tool_use`, `post_tool_use`, `tool_error`, and `run_stop` | Documentation-level concept only. The project uses typed in-process Python callbacks, not Claude hooks, shell hooks, settings, schemas, or SDK code. License of the documentation was not relied on for code reuse. |
| [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) | REJECT | Adding the SDK as the agent harness | Avoids a second runtime and an unsupported Claude integration claim | No dependency and no copied code. |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | ADOPT API | Compile with a checkpointer and invoke with a stable `thread_id`; SQLite for local development and PostgreSQL for integration | Survives service reconstruction while retaining graph state | Uses published Python APIs through pinned dependencies. LangGraph is MIT licensed. |
| [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | ADAPT | JSON interrupt payload; resume with `Command`; isolate side effects after the interrupt | Prevents an approval pause from executing an irreversible action | Node re-execution is handled with a project-owned SQLite idempotency key and transaction. No example code was copied. |
| [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) | ADAPT | W3C propagation and selected operation naming | Correlates API, run, policy, tool, citation, resume, and EvalOps spans | OTel Python API/SDK is Apache-2.0. GenAI conventions are pinned to `1.44.0`; project attributes use `enterprise.agent.*` where stability is not assumed. |
| [OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html) | ADAPT | Least privilege, explicit approval for sensitive tools, output validation, and isolated identities | Defines the threat-driven acceptance criteria | Guidance only; no example code copied. |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | REJECT FOR THIS ROUND | Direct benchmark integration | Its workspace tools and task semantics do not map to this repository's `search/find/open` plus draft-only access request without inventing a second business system | AgentDojo is MIT licensed. No package, cases, or source code were added. See the adaptation decision. |

## Deliberate differences

1. Hooks cannot execute arbitrary shell commands, HTTP callbacks, prompts, or
   agents. A hook is a typed Python object registered by trusted application
   assembly.
2. A silent hook never grants permission. The deterministic policy produces the
   authoritative `ALLOW`, `ASK`, or `DENY` result first.
3. Human approval cannot turn an ACL denial into access. Approval only confirms
   a policy-approved `ASK` action.
4. Checkpoint persistence is not exactly-once execution. Replayed nodes are safe
   only because the supported side effect has a deterministic key and commits its
   command and result atomically.
5. OTel is operational telemetry. The append-only trajectory remains the
   integrity/replay record; neither substitutes for the other.

## Version policy

- LangGraph runtime: `1.2.11`.
- LangGraph checkpoint core: resolved through the pinned runtime packages;
  SQLite adapter `3.1.1`, PostgreSQL adapter `3.1.2`.
- OpenTelemetry API/SDK and adopted semantic-convention reference: `1.44.0`.
- Upgrades require contract tests for checkpoint recovery, interrupt payloads,
  W3C propagation, privacy filtering, and artifact verification.
