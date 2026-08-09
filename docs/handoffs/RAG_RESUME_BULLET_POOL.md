# RAG Resume Bullet Pool

Choose at most three or four bullets for one resume. Chinese and English lines
below are equivalent; keep the metric name, denominator, and evidence boundary.

## AI / RAG roles

### A1 External retrieval

**中文：** 在 200 条 WixQA ExpertWritten 匿名真实客服问题上对比 BM25、BGE-M3
Dense 与等权 RRF；Dense 将 Article Recall@5 从 42.75% 提升至 66.42%、nDCG@5
从 32.15% 提升至 52.16%，p95 仅由 151.8 ms 增至 157.4 ms，并基于质量/延迟门禁
拒绝退化的等权 RRF。

**English:** Benchmarked BM25, BGE-M3 Dense, and equal RRF on 200 anonymized
real-support WixQA ExpertWritten questions; Dense improved Article Recall@5
from 42.75% to 66.42% and nDCG@5 from 32.15% to 52.16%, with p95 moving from
151.8 to 157.4 ms, while the regressing equal-RRF arm was rejected.

Evidence: `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json`.
Boundary: fixed public-label retrieval, not blind or answer accuracy.

### A2 Reproducible evaluation

**中文：** 建立版本、模型 digest、协议、数据哈希和消费状态绑定的 RAG 证据链；在
全新 source/index/embedding-cache/eval 根目录重建 11,975 个 WixQA chunk，63 项
冻结质量指标在零容差下与历史证据完全一致。

**English:** Built a hash-bound RAG evidence pipeline covering dataset revision,
model digest, frozen protocol, and consumption state; rebuilt all 11,975 WixQA
chunks in fresh source/index/cache/eval roots and reproduced 63 frozen quality
values exactly at zero tolerance.

Evidence: `docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json`.
Boundary: clean local regression replay of consumed public labels.

### A3 Bounded Agent and evidence controls

**中文：** 实现受控 search/find/open Agent，将身份与 ACL、工具预算、检索内容注入
防护、Evidence Ledger 和引用过滤收归 Python host；通过同检索器成对评测发现外部
Agent 路径无质量增益并阻止上线，而非用“能调用工具”冒充 Agent 有效。

**English:** Implemented a bounded search/find/open Agent with host-owned
identity/ACL, tool budgets, retrieved-content admission, evidence ledger, and
citation filtering; paired evaluation rejected an external Agent route that ran
correctly but produced no quality gain.

Evidence: `docs/enterprise_eval/evidence/wixqa_agent_public_v1.json` and
`docs/architecture.md`. Boundary: do not claim Agent quality improvement.

### A4 Retrieved-content security

**中文：** 设计检索内容间接提示词注入 Guard 与 OFF/ON 成对协议；在固定 garak
子集上将 ASR 从 4/12 降至 0/12、上下文暴露从 12/12 降至 0/12，平均扫描 1.42 ms。

**English:** Designed an indirect prompt-injection Guard and paired OFF/ON
protocol; on a pinned garak subset, reduced ASR from 4/12 to 0/12 and context
exposure from 12/12 to 0/12 with 1.42 ms mean scan latency.

Evidence: `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json`.
Boundary: 12 attacks and 2 benign controls, not universal safety.

### A5 Citation correctness boundary

**中文：** 对可见来源、词法、数字、日期及中英文非对称否定建立确定性引用检查，修复
肯定句与否定证据未触发冲突的 polarity 缺陷，并以聚焦回归测试锁定行为。

**English:** Added deterministic visible-source, lexical, numeric, date, and
English/Chinese asymmetric-negation citation checks; fixed a polarity bug that
missed affirmative-versus-negative contradictions and locked it with focused tests.

Evidence: `app/agent/citation_verifier.py` and
`tests/agent_v2/test_citation_verifier.py`. Boundary: deterministic consistency,
not semantic entailment certification.

## Python backend roles

### B1 Large-corpus indexing

**中文：** 将预计占用 36.60 GiB 内存的 Python BM25 方案替换为可恢复 SQLite FTS5，
以约 1.83 GiB 峰值内存在 231.35 秒内构建并激活 511,962 行、9 类来源、1.37 GiB
的全量索引。

**English:** Replaced an estimated 36.60 GiB in-memory Python BM25 design with
resumable SQLite FTS5, building and activating a 1.37 GiB index over 511,962
rows from nine source types in 231.35 seconds at about 1.83 GiB peak RSS.

### B2 Safe index lifecycle

**中文：** 实现 single-writer、可恢复 staging、manifest/hash/count/integrity 校验和
原子 active pointer；故障注入证明中断、校验失败和并发 builder 不会替换在线版本。

**English:** Implemented single-writer resumable staging, manifest/hash/count/
integrity verification, and atomic active-pointer switching; fault injection
proves interruption, verification failure, and competing builders cannot replace
the active version.

Evidence for B1/B2: `app/external_datasets/enterprise_rag_bench_fts.py`,
`tests/external_datasets/test_enterprise_rag_bench_fts.py`, and
`docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json`.

### B3 API trust boundaries

**中文：** 基于 FastAPI/Pydantic 实现固定 RS256/JWKS 校验、服务端派生租户/区域/组
权限、receipt 绑定反馈、readiness、限界 trace 与模型重试，避免客户端自报 ACL。

**English:** Built FastAPI/Pydantic trust boundaries with pinned RS256/JWKS,
server-derived tenant/region/group scope, receipt-bound feedback, readiness,
bounded traces, and model retries, preventing client-asserted ACL expansion.

### B4 Delivery controls

**中文：** 建立聚合证据发布、SHA-256 绑定、路径/密钥/大文件审计及 Ubuntu、Windows、
Linux container CI，使公开仓库可在无私有语料和密钥条件下验收。

**English:** Added aggregate evidence publication, SHA-256 bindings, path/
secret/large-file audits, and Ubuntu/Windows/Linux-container CI so public clones
can be validated without private corpora or keys.

## Bank / state-owned enterprise roles

### C1

**中文：** 开发企业知识库智能问答与检索系统，以 Python/FastAPI 提供结构化接口，
将身份权限、文档可见性、引用和证据不足拒答放在服务端校验，降低越权与无依据回答风险。

**English:** Developed an enterprise knowledge retrieval and QA service with
Python/FastAPI, enforcing identity scope, document visibility, citations, and
insufficient-evidence refusals in trusted server code.

### C2

**中文：** 面向 511,962 行、9 类企业数据源构建可恢复 FTS5 索引，采用单写入、校验
后激活和原子版本切换，并用异常/并发测试验证旧版本在失败时保持可用。

**English:** Built a resumable FTS5 index for 511,962 rows across nine enterprise
source types, with single-writer operation, verify-before-activate, atomic
version switching, and failure/concurrency tests preserving the prior version.

### C3

**中文：** 对外部检索、安全和容量分别建立固定协议与证据文件，明确 Recall@5、
nDCG@5、攻击成功率及延迟的分母和适用边界，未将检索指标包装为业务准确率。

**English:** Established frozen protocols and evidence artifacts for external
retrieval, security, and capacity, preserving denominators and boundaries for
Recall@5, nDCG@5, ASR, and latency instead of presenting retrieval as business accuracy.

### C4

**中文：** 实现文档来源事件、幂等/冲突账本、隔离区、版本快照、删除 tombstone、
原子激活与回滚的知识生命周期，保留可追溯审计记录。

**English:** Implemented an auditable knowledge lifecycle with source events,
idempotency/conflict ledger, quarantine, versioned snapshots, deletion
tombstones, atomic activation, and rollback.

## Never write

Do not write “RAG accuracy 60.37%,” “answer accuracy 66.42%,” “Agent improved
quality,” “blind test,” “production-ready,” “100% safe,” “full Enterprise Dense,”
“SOTA,” “GraphRAG,” “MCP,” or production SLO/QPS.
