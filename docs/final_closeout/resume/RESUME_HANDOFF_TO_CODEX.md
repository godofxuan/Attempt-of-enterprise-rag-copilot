# Resume Handoff to Codex

## 项目一句话

面向企业内部资料查询的受控知识 Agent：员工在本人权限内调用检索工具，系统经证据和引用校验后返回带原文出处的回答或安全终态，并记录可验证执行轨迹用于回放与评测。

## 推荐项目名

- AI / Agent：**企业知识 Agent（受控 Agentic RAG Runtime）**
- Python 后端 / AI Infra：**企业知识 Agent 服务与受控运行时**
- 银行 / 央国企：**企业知识库智能问答与权限检索系统**

## 最值得写的 5 个事实

1. 从资料接入、版本化索引、权限检索到 Agent/evidence/citation/safe output 的完整系统。
2. 自研 bounded controller 保持默认，真实 LangGraph StateGraph 作为共享安全路径下的 alternative。
3. 官方 MCP SDK 的 `search/find/open` 仍经过 ToolGateway、ACL、预算和 Guard。
4. hash-chain trajectory、deterministic replay 与 `enterprise.agent-run/1.0` EvalOps Artifact。
5. WixQA 外部检索提升与 EnterpriseRAG-Bench 511,962 条公共记录索引。

## 最值得写的 3 个数字

1. WixQA Recall@5：42.75% -> 66.42%（200 道固定公开检索题）。
2. WixQA nDCG@5：32.15% -> 52.16%（同一协议）。
3. EnterpriseRAG-Bench：511,962 条公共记录，231.35 秒单机建库，峰值内存约 1.83 GiB。

## 框架关键词

Python, FastAPI, Pydantic, BGE-M3, BM25, FAISS, SQLite FTS5, LangGraph,
MCP, Agent Runtime, ToolGateway, ACL, Evidence Ledger, citation verification,
trajectory, replay, HITL, EvalOps, Docker, GitHub Actions.

关键词必须附属于问题和方案，不能拼成技术栈大礼包。

## 不允许写的 claim

- Agent/RAG/回答准确率 100% 或 66.42%
- LangGraph 提升质量、RAG accuracy 或 production latency
- production-ready、production SLO/QPS/HA
- production MCP、OAuth MCP server、network-isolated MCP
- durable/persistent HITL
- WORM、cryptographically immutable、production audit ledger
- 51 万真实企业数据
- universal Agent safety、full garak passed
- independent third-party reproduction

## 面试追问

- 为什么实现 LangGraph 却不设为默认？
- ToolGateway 如何阻止身份、ACL、预算和 deadline 绕过？
- 为什么 MCP 不能直接访问数据库？
- hash chain 能证明什么、不能证明什么？
- HITL 如何处理失败重试、同决策幂等和并发？
- 为什么 Dense 胜出而 equal RRF 被拒绝？
- FTS5 如何支持 511,962 条记录的构建、激活与恢复？
- 哪些生产缺口是有意保留的？

## Freeze identity

- final branch: `codex/agent-runtime-vnext`
- previous audited SHA: `f291019dc1df80ac741782365ebf6960d7f1de19`
- final runtime freeze SHA: `ab5c48735a69aec43e26abb240275f08004789e7`
- final runtime Actions run: `32274793459`
- run URL: <https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/32274793459>

The closeout documentation commit may be newer than the runtime freeze SHA; use
the branch tip from the final handoff report for repository bookkeeping. The
runtime/evidence claims above are bound to the recorded execution SHAs in
`RAG_RESUME_FACT_SHEET.md`.

