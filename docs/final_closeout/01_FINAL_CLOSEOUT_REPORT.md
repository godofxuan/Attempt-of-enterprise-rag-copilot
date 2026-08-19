# Final Closeout Report

## 1. What the project is

The project is a controlled enterprise knowledge Agent / Agentic RAG Runtime.
It accepts enterprise documents and authenticated questions, retrieves evidence
inside the caller's permissions, and returns a cited answer, bounded partial
answer, or safe refusal. It also records a verifiable semantic trajectory for
replay and evaluation.

## 2. How far it moved beyond a RAG demo

The implemented path covers validated document ingestion, parsing, chunking,
versioned and recoverable indexes, BM25/BGE-M3/FAISS/SQLite FTS5 retrieval,
identity and ACL filtering, retrieved-content Guard, an Evidence Ledger,
bounded Agent tool use, claim/citation verification, safe terminal modes,
trajectory/replay, and an EvalOps artifact. These mechanisms share one server-
owned authority path instead of relying on prompts for security.

## 3. Current Agent Runtime

`AgentOrchestrator` separates orchestration from authority. Both implementations
receive the same request shape and use the same Tool Contract, ToolGateway,
retrieval/Guard pipeline, Evidence Ledger, response builder, and citation gate.

## 4. Bounded controller

`BoundedControllerAdapter` remains the default and baseline. It uses explicit
budgets, required-aspect search, deterministic terminal policy, and a small
auditable state surface. No evidence shows that replacing it improves quality.

## 5. LangGraph alternative

`LangGraphOrchestratorAdapter` is a real `StateGraph`, retained for explicit
state transitions and HITL interrupt/resume. On five fixed mechanism cases both
arms passed 5/5 with behavioral parity and zero permission violations, while
LangGraph diagnostic p95 was higher. This is not an external quality benchmark.

## 6. ToolGateway

ToolGateway owns server-issued session context, identity fingerprint, tenant,
ACL scope, tool allow-list, budgets, deadlines, sequence, and lifecycle. The
final invariant defines `acl_scope` as an optional narrowing of authenticated
groups; expanded or unrelated groups fail validation.

## 7. MCP

The official MCP SDK adapter exposes `search`, `find`, and `open`, but dispatch
still passes through ToolGateway and the guarded registry. This demonstrates
protocol integration, not a production network MCP service or OAuth deployment.

## 8. Trajectory

The SQLite trajectory is append-only at the application layer and links ordered
semantic events with SHA-256 hashes. It supports tamper-evidence and local
verification. It is not WORM, externally signed, encrypted-at-rest by this
module, or a production audit ledger.

## 9. Replay

Deterministic replay verifies the hash chain and reconstructs recorded inputs,
tool steps, evidence, and terminal output without network/model calls. Replay is
not a durable execution engine and does not rerun external side effects.

## 10. HITL

LangGraph partial-evidence HITL binds review to tenant and reviewer role and uses
an opaque one-time token. The final in-process state machine is `PENDING ->
RESUMING -> COMPLETED`: graph failure returns to PENDING, the same completed
decision is idempotent, a different decision is rejected, and concurrent resume
executes the graph once. Process restart still loses pending state.

## 11. EvalOps artifact

`enterprise.agent-run/1.0` exports input/output, ordered trajectory, retrieval,
evidence, usage, terminal state, source root hash, and artifact SHA. The sample
verifies successfully. `run_id == session_id` is a current producer
simplification documented for consumers, not a final cross-project identity
model.

## 12. Retrieval, indexing, and security baseline

The closeout preserves ingestion and parsing, BM25, BGE-M3, FAISS, SQLite FTS5,
revision/tombstone lifecycle, atomic activation/rollback, identity/ACL,
retrieved-content Guard, Evidence Ledger, and citation verification. No fix
bypasses or replaces these paths.

## 13. Tests

Targeted required-fix suite: 38 passed after including the CI configuration
contract. Full local regression: 3,290 passed and 29 skipped. Evidence-focused
suite: 53 passed. Skips are existing environment/optional cases, not new
required-fix failures.

## 14. CI

Run `32274793459` on runtime fix SHA `ab5c487...` passed Ubuntu, Windows, and
`linux-container-contract`. The container job passed pinned builds, non-root
identity, read-only filesystem, in-image gates, readiness success and expected
failure, rollback drill, SBOM generation, and artifact upload.

## 15. Evidence

- WixQA ExpertWritten, 200 fixed public-label retrieval questions: Recall@5
  42.75% to 66.42%; nDCG@5 32.15% to 52.16% for BM25 versus BGE-M3 Dense.
- EnterpriseRAG-Bench public corpus: 511,962 rows; 1.37 GiB SQLite FTS5 index;
  231.35 seconds active build; about 1.83 GiB peak RSS on one host.
- Clean WixQA replay: 11,975 embeddings and 63/63 frozen quality comparisons
  reproduced exactly at tolerance 0.0.
- Agent Runtime diagnostic: both adapters 5/5 on fixed mechanism cases; this is
  interview evidence, not a resume headline.

## 16. Claims that remain disallowed

Do not claim production readiness/SLO/QPS/HA, answer accuracy of 66.42%, a
quality gain from LangGraph, universal Agent safety, full garak coverage,
production network MCP/OAuth, durable HITL, WORM audit storage, independent
third-party reproduction, or real private enterprise data at 511,962 rows.

## 17. Why feature development stops here

The system already demonstrates a complete product path, replaceable runtime,
controlled tools, traceability, reproducible evaluation, and negative-result
engineering judgment. Another framework or distributed component would add
surface area without closing a measured gap. The correct next step is review
and interview use, or production hardening only when a real deployment supplies
requirements for storage, identity, networking, SLOs, and operations.

