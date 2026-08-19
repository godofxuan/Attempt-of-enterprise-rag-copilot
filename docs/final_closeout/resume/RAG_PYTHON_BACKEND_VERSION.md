# 企业知识 Agent 服务与受控运行时

**技术栈：** Python / FastAPI / Pydantic / SQLite FTS5 / FAISS / LangGraph / MCP / Docker / GitHub Actions

构建面向企业资料查询的 FastAPI 服务与 Agent Runtime：文档经过校验、解析和版本化索引后，用户可在身份与 ACL 约束内调用检索工具，服务端统一完成证据准入、引用校验和安全终止，并输出可校验的运行工件。

- 针对 Agent 编排容易复制权限逻辑的问题，设计 `AgentOrchestrator`、严格 Tool Contract 与有状态 ToolGateway；集中校验 identity fingerprint、tenant、ACL narrowing、tool allow-list、预算、sequence 和 deadline，使 bounded 与 LangGraph 两种执行器共用同一权限路径。
- 基于官方 MCP SDK 接入 `search/find/open`，但以 opaque context handle 回到服务端 ToolGateway 执行，避免协议适配层直连数据库或绕过 Guard；异常统一返回结构化权限、超时、预算和系统错误。
- 为运行审计和下游 EvalOps 实现 append-only SHA-256 hash-chain trajectory、无网络 deterministic replay 与 `enterprise.agent-run/1.0` Artifact 校验；HITL 采用进程内 PENDING/RESUMING/COMPLETED 状态，支持失败重试、同决策幂等与并发单执行。
- 针对大语料词法索引的内存与恢复问题，采用 SQLite FTS5、不可变快照、原子激活和 rollback；在 511,962 条公共记录上生成 1.37 GiB 索引，231.35 秒完成建库。Python 3.11 跨平台 CI 覆盖 3,290 项测试及非 root、只读文件系统、readiness failure、rollback 和 SBOM。

