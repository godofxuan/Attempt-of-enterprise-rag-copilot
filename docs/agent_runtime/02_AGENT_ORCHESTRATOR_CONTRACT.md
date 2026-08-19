# Agent Orchestrator Contract

`AgentOrchestrator.run(AgentRunRequest) -> AgentRunResult` is the vNext runtime
entry point. The request carries the trusted `UserContext` and request, trace,
and session correlation IDs. The result always contains a typed
`AnswerResponse`, orchestrator name, node trace, and measured latency.

Two implementations exist:

- `BoundedControllerAdapter`: preserves the existing runner and controller.
- `LangGraphOrchestratorAdapter`: executes explicit StateGraph nodes.

Both create a per-run Tool Contract session and therefore use the same
`ToolGateway`, `V2ToolRegistry`, navigator, ACL, admission, Guard, budget, and
typed errors. The outer request ID identifies the Agent run; each tool keeps its
existing `agent-step-N` call ID.

The contract deliberately does not promise equivalent latency or quality.
Behavioral equivalence is tested on deterministic fixtures and formal A/B
evaluation is deferred to Stage I.

