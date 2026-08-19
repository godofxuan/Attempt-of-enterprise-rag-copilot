# Acceptance Matrix

| Capability | Status | Code | Tests/evidence | Limitation |
|---|---|---|---|---|
| AgentOrchestrator | PASS | `app/agent_runtime/orchestrator.py` | `tests/agent_runtime/test_orchestrators.py` | Two implementations only; not distributed |
| Bounded adapter/default | PASS | orchestrator + `app/agent/controller_v2.py` | 5/5 A/B arm | Fixed mechanism cases are not external quality |
| Real LangGraph StateGraph | PASS | `LangGraphOrchestratorAdapter._compile` | orchestrator and A/B tests | Alternative; no demonstrated quality gain |
| Shared Tool Contract | PASS | `tool_contract.py` | `test_tool_contract.py` | In-process contract |
| Shared ACL | PASS | ToolContext, ToolGateway, retrieval pipeline | same/narrow PASS; expanded/unrelated FAIL | Depends on authenticated upstream identity |
| Retrieved-content Guard | PASS | `app/security/retrieved_content.py` | security tests; narrow garak evidence | Not universal prompt-injection safety |
| Evidence Ledger | PASS | `app/agent/evidence_ledger.py` | Agent v2 regression suite | Rule-based coverage semantics |
| Citation gate | PASS | generation/citation verifier | citation and final evidence tests | Not semantic entailment certification |
| ToolGateway | PASS | `tool_gateway.py` | contract/gateway tests | Process-local sessions |
| MCP adapter | PASS | `mcp_adapter.py` | `test_mcp_adapter.py` | In-process SDK dispatch, no network OAuth |
| Trajectory | PASS | `trajectory.py` | `test_trajectory.py` | Tamper-evident local SQLite; not WORM/encrypted ledger |
| Replay | PASS | `replay.py` | `test_replay.py` | Reconstructs records; not durable execution |
| HITL | PASS | LangGraph adapter resume state | `test_human_review.py` | Same-process only; restart loses state |
| Agent Run Artifact | PASS | `evalops_artifact.py`, schema | sample verifier; `test_evalops_artifact.py` | Open payload dictionaries; run/session IDs currently equal |
| Targeted tests | PASS | required-fix suites | 38 passed | Deterministic local scope |
| Full local tests | PASS | repository suite | 3,290 passed, 29 skipped | No live production services |
| CI | PASS | `.github/workflows/ci.yml` | run 32274793459 | Portfolio CI, not production deployment certification |

No matrix item is FAIL. Items whose mechanism is complete but deployment
boundary remains local are marked PASS with an explicit limitation rather than
being relabeled as production capability.

