# 企业知识 Agent（受控 Agentic RAG Runtime）

**技术栈：** Python / FastAPI / BGE-M3 / FAISS / SQLite FTS5 / LangGraph / MCP

面向企业制度、Wiki、工单、邮件和会议记录等内部资料，开发可按用户权限检索的企业知识 Agent。系统打通文档接入、版本化索引、Agent 工具调用、证据与引用校验，最终返回带原文出处的回答、信息不足时的部分回答或安全拒答，并可保留执行轨迹用于回放和评测。

- 将资料接入、BM25/BGE-M3 检索、ACL 过滤、Evidence Ledger 与 citation gate 串成完整 Agentic RAG 路径，身份、资料权限和最终发布策略由服务端控制，避免把安全边界交给 Prompt。
- 为避免编排框架与权限逻辑耦合，将原有 bounded controller 抽象为可替换 Agent Runtime，并实现真实 LangGraph StateGraph alternative；两条路径共用 ToolGateway、检索 Guard 与引用校验，保留更轻量的 bounded controller 为默认实现。
- 将 `search/find/open` 通过官方 MCP SDK 标准化暴露，请求仍经过服务端身份、ACL、预算和 deadline 校验；实现 hash-chain trajectory、deterministic replay 与 `enterprise.agent-run/1.0` Artifact，为 EvalOps 提供可验证运行记录。
- 在 WixQA ExpertWritten 200 道固定公开检索题上，BGE-M3 Dense 将 Recall@5 从 42.75% 提升至 66.42%、nDCG@5 从 32.15% 提升至 52.16%；并在公共 EnterpriseRAG-Bench 语料上完成 511,962 条记录的单机 SQLite FTS5 建库（231.35 秒，峰值内存约 1.83 GiB）。

## 10 秒检查

企业资料进入系统，员工在本人权限内提问，Agent 返回带出处的回答或安全终态；技术差异是受控 Runtime、LangGraph/MCP 与可验证 trajectory；可核验结果是 WixQA 检索提升和 511,962 条公共记录索引。

