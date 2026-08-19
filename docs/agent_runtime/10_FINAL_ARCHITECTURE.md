# Agent Runtime vNext Final Architecture

## 1. What changed

The baseline bounded Agent was not replaced. It was placed behind a stable
orchestrator contract and connected to the same guarded tool plane as a real
LangGraph alternative:

```text
FastAPI / local caller
        |
        v
AgentRunRequest + trusted UserContext
        |
        +-------------------------------+
        | AgentOrchestrator             |
        |  - BoundedControllerAdapter   |
        |  - LangGraphOrchestratorAdapter
        +-------------------------------+
                        |
                        v
                shared Tool Contract
                        |
            +-----------+-----------+
            |                       |
       direct session          official MCP SDK
            |                 (protocol adapter)
            +-----------+-----------+
                        v
                   ToolGateway
             identity / ACL / budget /
               deadline / allow-list
                        |
                        v
          existing search / find / open
                        |
           ACL -> retrieval -> Guard
                        |
             Evidence Ledger / claims
                        |
          citation gate -> safe terminal
                        |
       append-only trajectory + OTel link IDs
                        |
          replay -> Agent Run Artifact -> EvalOps
```

## 2. Stable public contracts

| Contract | File | Responsibility |
|---|---|---|
| orchestrator | `app/agent_runtime/orchestrator.py` | common run/result and interchangeable adapters |
| tool data | `app/agent_runtime/tool_contract.py` | strict definition/request/result/context/error models |
| tool authority | `app/agent_runtime/tool_gateway.py` | server-side session, identity, allow-list, budget, expiry |
| MCP adapter | `app/agent_runtime/mcp_adapter.py` | official SDK exposure without backend bypass |
| trajectory | `app/agent_runtime/trajectory.py` | ordered append-only semantic events and hash chain |
| replay | `app/agent_runtime/replay.py` | deterministic reconstruction without model/tool calls |
| evaluation | `app/agent_runtime/evaluation.py` | paired controller mechanism experiment |
| EvalOps artifact | `app/agent_runtime/evalops_artifact.py` | versioned export and verification |

## 3. Runtime choices

### BoundedControllerAdapter

This remains the default reference. It delegates planning and execution to the
existing `run_agent_v2`, so the established evidence, Guard, grounding, and
terminal behavior stay intact. Use it when a short, predictable path matters.

### LangGraphOrchestratorAdapter

This is a real `StateGraph`, not a renamed wrapper. Its nodes analyze, decide,
execute, optionally interrupt for review, and publish. Every tool call still
passes through `_ContractToolSession` and `ToolGateway`; node routing cannot
open arbitrary databases or files. Use it when explicit graph state or HITL is
needed, accepting measured orchestration overhead.

The controlled A/B produced identical outcomes on all 5 mechanism cases, but no
quality gain. LangGraph p95 was `6.838 ms` versus bounded `1.283 ms` in this tiny
local diagnostic. It is therefore retained as an alternative, not promoted as
the universally better default.

## 4. Semantic trajectory versus observability

The existing observability layer answers operational questions such as latency,
errors, and service health. `AgentEvent` answers semantic questions such as
which tool was requested, which evidence was admitted, why a terminal state was
chosen, and what a reviewer decided. They share `trace_id` and `session_id`, so
an operator can correlate the two without storing a second copy of private
retrieved content.

Current semantic events include session, user message, step, tool, retrieval,
evidence, claim, citation, budget, human review, terminal, and completion events.
No model call exists in the deterministic sample, so its `model_call_count` is
correctly zero rather than fabricated.

## 5. Replay and EvalOps

`replay_trajectory` verifies the complete event hash chain before reconstructing
input, tool calls/results, admitted evidence, final output, and terminal reason.
It does not call Ollama, retrieval, or tools. `build_agent_run_artifact` then
exports those layers under schema `enterprise.agent-run/1.0`, adds usage data,
and seals the complete artifact with another SHA-256 hash.

Reproduction:

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_agent_runtime_sample --git-sha 9ff917bdf99b971a59754b731176e85d61f570e6
.\.venv\Scripts\python.exe -m scripts.verify_agent_run_artifact docs\agent_runtime\evidence\agent_run_artifact_sample_v1.json
```

The generated private SQLite store lives under `.private/agent_runtime` and is
git-ignored. The public artifact contains metadata and bounded output, not raw
retrieval content.

## 6. Stage and commit ledger

| Stage | Commit | Result |
|---|---|---|
| A | `f01e1ce317b4d2075c9352f2c7dfbfd5b37622cc` | frozen baseline and architecture |
| B | `10b915485f74e6f0fe4665224b87e4b32c1f5565` | formal tool contract and gateway |
| C | `e7bbd2886a1bf38fbc975cbf7309f6f686078850` | official MCP adapter |
| D | `7dc60148cf21b47ce03177fbae63c59a7a36e795` | interchangeable orchestrators |
| E | `90e250f2493df100e79c12f27c136f8096c5cc1d` | append-only trajectory |
| F | `5ccabf0f88ac0fb8df2283317ad3e02009c73832` | verified replay |
| G | `03e46e8c93db2443363ddb537980f42041c9cfdd` | real HITL interrupt/resume |
| I | `d20382d111cc6ee5a54a1daad92454ecf0c501f3` | corrected paired A/B implementation |
| I evidence | `4a6bfb400f042f2a4417f7c74da9a16103604ac4` | accepted A/B artifact |
| J core | `907af5240d45224d30b1bed7363bd896ea363c5d` | EvalOps serializer/verifier |
| J tooling | `9ff917bdf99b971a59754b731176e85d61f570e6` | reproducible sample commands |

## 7. Deliberate non-features

Stage H did not produce a Skill abstraction because current trajectory evidence
does not show repeated complex policies that justify it. Multi-agent was not
implemented because no measured single-agent failure requires it. LangChain was
not used to wrap working custom retrieval. These omissions keep the authority
model inspectable and avoid adding framework names without measured value.

## 8. Remaining production work

The highest-value next work is not another framework. It is durable encrypted
trajectory storage with retention policy, network MCP authentication and
connection binding, persistent HITL checkpoints with concurrency tests, and a
larger external end-to-end Agent benchmark. Those are explicitly outside this
vNext evidence boundary.

