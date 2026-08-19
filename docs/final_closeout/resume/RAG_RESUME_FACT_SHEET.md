# RAG Resume Fact Sheet

## Claim 1: controlled enterprise knowledge Agent

**Claim:** End-to-end enterprise knowledge Agent from document ingestion to
permission-aware cited/safe output.

**Code:** `app/ingestion`, `app/indexing`, `app/retrieval`, `app/agent`,
`app/agent_runtime`, `app/security`.

**Tests:** Full repository suite; Agent v2, ACL, Guard, citation, lifecycle tests.

**Evidence:** README architecture and final acceptance matrix.

**Dataset:** In-repo public synthetic corpus for mechanism tests; external
retrieval evidence is separate.

**Sample count:** Not a single metric claim.

**SHA:** Runtime freeze `ab5c48735a69aec43e26abb240275f08004789e7`.

**Allowed wording:** “打通资料接入、版本化索引、权限检索、Agent 工具调用、证据与引用校验，返回带出处回答或安全终态。”

**Forbidden wording:** “production-ready enterprise platform”; “已服务真实企业生产流量”.

**Best target role:** All three versions.

## Claim 2: replaceable Agent Runtime

**Claim:** Bounded default plus real LangGraph StateGraph alternative sharing
one authority/tool path.

**Code:** `app/agent_runtime/orchestrator.py`, `tool_contract.py`,
`tool_gateway.py`.

**Tests:** `tests/agent_runtime/test_orchestrators.py`,
`test_ab_evaluation.py`, `test_tool_contract.py`.

**Evidence:** `docs/agent_runtime/evidence/agent_runtime_ab_v1.json`.

**Dataset:** Five fixed in-repo mechanism cases.

**Sample count:** 5 cases x 2 arms.

**SHA:** A/B execution `d20382d111cc6ee5a54a1daad92454ecf0c501f3`;
final runtime fix `ab5c487...`.

**Allowed wording:** “实现可替换 Runtime 与真实 LangGraph alternative，两条路径共享 ToolGateway/ACL/Guard/citation gate；bounded 保持默认。”

**Forbidden wording:** “Agent accuracy 100%”; “LangGraph improves quality/RAG accuracy”; “production latency”.

**Best target role:** AI Agent, Python backend/AI infra.

## Claim 3: MCP, trajectory, replay, EvalOps

**Claim:** Official MCP SDK adapter stays behind ToolGateway; verified semantic
trajectory can be replayed and exported as `enterprise.agent-run/1.0`.

**Code:** `mcp_adapter.py`, `trajectory.py`, `replay.py`,
`evalops_artifact.py`.

**Tests:** MCP, trajectory, replay, EvalOps artifact test modules.

**Evidence:** `docs/agent_runtime/evidence/agent_run_artifact_sample_v1.json`;
artifact SHA `f9d32f1bff44a27bbde1bf92b47800d396c9700a8120c135abf9b842b8108233`.

**Dataset:** Synthetic public sample run.

**Sample count:** 13 trajectory events in the published sample.

**SHA:** Artifact execution `9ff917bdf99b971a59754b731176e85d61f570e6`.

**Allowed wording:** “官方 MCP SDK adapter”; “append-only hash-chain trajectory”; “deterministic replay”; “可验证 Agent Run Artifact”.

**Forbidden wording:** “production MCP deployment/OAuth server”; “WORM/cryptographically immutable audit ledger”; “durable execution”.

**Best target role:** AI Agent, Python backend/AI infra.

## Claim 4: WixQA retrieval improvement

**Claim:** BGE-M3 Dense improved Recall@5 42.75% -> 66.42% and nDCG@5
32.15% -> 52.16% versus BM25.

**Code:** WixQA download/index/evaluation scripts and retrieval pipeline.

**Tests:** `tests/test_portfolio_handoff_evidence.py`, final evidence tests.

**Evidence:** `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json`.

**Dataset:** WixQA ExpertWritten, fixed consumed public labels.

**Sample count:** 200 retrieval questions; 52 multi-article cases.

**SHA:** Execution `234734657fe354a0ecd767022c6f7c22cdc329da`;
dataset revision `d662dc42479c14e202eccd832f8c4b66a035c4cc`.

**Allowed wording:** “在 WixQA ExpertWritten 200 道固定公开检索题上，Recall@5 从 42.75% 提升至 66.42%，nDCG@5 从 32.15% 提升至 52.16%。”

**Forbidden wording:** “回答准确率 66.42%”; “blind holdout”; “Agent quality improved”.

**Best target role:** AI/RAG/Agent; bank/SOE evaluation bullet.

## Claim 5: 511,962-record FTS5 index

**Claim:** One-host SQLite FTS5 build over 511,962 public records produced a
1.37 GiB artifact in 231.35 seconds with about 1.83 GiB peak RSS.

**Code:** `scripts/build_enterprise_rag_bench_fts.py`, SQLite FTS lifecycle.

**Tests:** EnterpriseRAG-Bench FTS and lifecycle tests.

**Evidence:** `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json`;
artifact SHA `e2de7adf996d18b3908bd372c65f78909a3f62ab161e1fd9b1844b8f8d7817cf`.

**Dataset:** EnterpriseRAG-Bench public synthetic enterprise corpus, nine
source types.

**Sample count:** 511,962 records; 470 retrieval questions.

**SHA:** Execution `955d86f1ca244bc90025c89806fd786f978b98ff`.

**Allowed wording:** “在公共 EnterpriseRAG-Bench 语料上完成 511,962 条记录的单机 SQLite FTS5 建库，约 231 秒，峰值内存约 1.83 GiB。”

**Forbidden wording:** “51 万真实企业数据”; “production scale/high QPS”; “distributed index”.

**Best target role:** All three, strongest for backend/bank.

## Claim 6: clean reproduction

**Claim:** Fresh local roots rebuilt 11,975 embeddings and reproduced 63/63
frozen quality observations with zero tolerance.

**Code:** `scripts/reproduce_wixqa_retrieval.py`,
`scripts/verify_wixqa_clean_reproduction.py`.

**Tests:** Final evidence/reproduction tests.

**Evidence:** `docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json`.

**Dataset:** Consumed WixQA Synthetic, Simulated, and ExpertWritten labels.

**Sample count:** 63 comparisons; 11,975 embeddings.

**SHA:** Candidate execution `4d07d6a4f14bf4eaded8ff1bd6987b8a094dc064`.

**Allowed wording:** “从全新本地 source/cache/index/output 根目录精确复现 63/63 冻结质量值。”

**Forbidden wording:** “independent third-party replication”; “new blind test”.

**Best target role:** Interview, AI infra/reproducibility.

## Interview-only facts

The five-case latency/parity values, pinned garak 12-attack result, RRF negative
result, multi-document candidate rejection, and detailed hash/invariant design
belong in interviews or specialized security versions, not the ordinary resume.

