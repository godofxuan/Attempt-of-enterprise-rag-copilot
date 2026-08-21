# Enterprise Agentic RAG Copilot - 中文简历终稿

数字唯一权威源：`docs/handoffs/RESUME_METRIC_LEDGER.md`。本页只做岗位选材，
不得脱离 ledger 的数据集、分母和限制单独改写数字。

## 推荐项目标题

**Enterprise Agentic RAG Copilot｜受控 Agent Runtime 与企业知识检索系统**

## 一句话定位

面向企业知识问答的本地 RAG/Agent 工程项目：由宿主程序控制身份、ACL、工具、
证据准入与引用发布，并以可回放轨迹、冻结评测和失败门禁约束功能上线。

## 技术栈

Python / FastAPI / Pydantic / BGE-M3 / BM25 / FAISS / SQLite FTS5 /
LangGraph StateGraph / MCP Python SDK / Pytest / Docker / GitHub Actions

可选运行时关键词：LangGraph SQLite/PostgreSQL Checkpointer / OpenTelemetry /
W3C Trace Context。只有目标分支 CI 通过后再放进已投递版本。

## AI Agent / RAG 岗推荐三条

1. 抽象统一 `AgentOrchestrator`，让默认 bounded controller 与真实 LangGraph
   `StateGraph` alternative 共用 `ToolGateway`、ACL、Retrieved-content Guard、
   Evidence Ledger 和 citation gate；框架仅替换编排层，不获得扩权路径，也不写
   “LangGraph 提升答案质量”。
2. 将 `search/find/open` 建模为强类型工具合同，并通过官方 MCP SDK 做本地/
   in-process 适配；使用服务端签发的 opaque context handle 绑定身份、租户、
   ACL、预算与 deadline，MCP 调用仍回到同一个 `ToolGateway` 执行。
3. 在 WixQA ExpertWritten 200 道固定 public-label 检索题上，BGE-M3 Dense
   相比 BM25 将 Recall@5 从 `42.75%` 提升至 `66.42%`、nDCG@5 从
   `32.15%` 提升至 `52.16%`；这些是检索排序指标，不是回答准确率。

### Agent Runtime 候选替换条目

可用它替换上面第 2 条，不要让单个版本堆四条：

基于确定性 `ALLOW/ASK/DENY` Tool Policy 和 typed lifecycle hooks，将敏感
访问申请限制为人工批准后的 draft-only 操作；使用 LangGraph file-backed
checkpoint 支持服务对象重启恢复，以 tenant/reviewer/role/expiry/argument hash
重新授权，并通过幂等 SQLite command 防止故障重试重复建单；它不是 arbitrary
workflow durable execution，也不是 exactly-once。

## Python / AI 平台岗推荐三条

1. 将超出原内存预算的词法检索改造成 SQLite FTS5 single-writer 构建链路，
   在单机处理 `511,962` 条、9 类记录，`231.35 s` 生成并原子激活
   `1.37 GiB` 索引，峰值 RSS 约 `1.83 GiB`；实现 staging、校验、不可变
   snapshot、tombstone、增量失效与回滚。
2. 设计 append-only SHA-256 hash-chain trajectory、确定性 no-network replay
   与版本化 `enterprise.agent-run/1.0` 工件，使 Agent 的工具、证据和终态可被
   EvalOps 消费和复核；不宣称 WORM、生产审计认证或外部平台采用。
3. 建立证据驱动发布门禁，覆盖依赖、编译、冻结指标、Agent/ACL/Guard 回归和
   公开仓库泄漏审计；保留 equal-RRF 与多文档候选的负结果，未达到预注册质量
   条件时拒绝集成，而不是为了技术栈完整度上线。

## 安全岗替换条目

在固定 12 条 garak retrieved-content injection 子集上进行 Guard OFF/ON 成对
评测，将观测 ASR 从 `4/12` 降至 `0/12`、上下文暴露从 `12/12` 降至
`0/12`；仅代表该固定子集，不能写“100% 安全”或推广为通用防注入能力。

## 代码、测试与证据映射

| 简历条目 | 源码 | 测试 | 证据/权威说明 |
|---|---|---|---|
| Agent Runtime / Harness | `app/agent_runtime/orchestrator.py`; `tool_gateway.py` | `tests/agent_runtime/test_orchestrators.py`; `test_ab_evaluation.py` | `docs/agent_runtime/evidence/agent_runtime_ab_v1.json`; 仅机制验证 |
| Durable policy/runtime candidate | `app/agent_runtime/tool_policy.py`; `durable_orchestrator.py`; `side_effects.py`; `telemetry.py`; `harness_contract.py` | `test_tool_policy.py`; `test_durable_orchestrator.py`; `test_side_effects.py`; `test_telemetry.py`; `test_harness_contract.py` | `docs/production_runtime/RESULTS.md`; SQLite local evidence, PostgreSQL CI 待确认 |
| MCP 工具边界 | `app/agent_runtime/tool_contract.py`; `mcp_adapter.py` | `tests/agent_runtime/test_tool_contract.py`; `test_mcp_adapter.py` | `docs/agent_runtime/04_MCP_ARCHITECTURE.md`; local/in-process |
| trajectory / replay / EvalOps | `app/agent_runtime/trajectory.py`; `replay.py`; `evalops_artifact.py` | `tests/agent_runtime/test_trajectory.py`; `test_replay.py`; `test_evalops_artifact.py`; `test_human_review.py` | `docs/agent_runtime/evidence/agent_run_artifact_sample_v1.json` |
| WixQA 检索 | `app/external_datasets/wixqa_retrieval.py` | `tests/external_datasets/test_wixqa_public_evidence.py` | `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json` |
| 单机 FTS5 | `app/external_datasets/enterprise_rag_bench_fts.py` | `tests/external_datasets/test_enterprise_rag_bench_fts.py`; `tests/test_final_evidence_closure.py` | `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json` |
| Retrieved-content Guard | `app/security/retrieved_content.py` | `tests/security/test_retrieved_content_guard.py`; `tests/evaluation/test_garak_latent_report.py` | `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json` |

## 禁止表述

- 不把 Recall@5 或 nDCG@5 写成“回答准确率”或“RAG 准确率”。
- 不写“Agent 效果优于固定 RAG”或“LangGraph 提升质量”。
- 不写“100% 安全”“SOTA”“production-ready”或“企业真实线上部署”。
- 不把 in-process MCP 写成生产网络 MCP/OAuth。
- 不把旧 partial-answer 同进程 HITL 写成 durable；不把新的 draft-only restart
  测试外推为完整 production HITL、distributed exactly-once 或任意副作用恢复。
- 不把五例 parity test 写成答案质量或生产性能实验。

完整限定、证据 SHA 和禁止口径见 `docs/handoffs/PROJECT_EVIDENCE_MAP.md` 与
`docs/handoffs/RESUME_METRIC_LEDGER.md`。
