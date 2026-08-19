# Agent Runtime / Harness 学习教程

本文面向会 Python、FastAPI 和基础 RAG，但还没有系统做过 Agent Runtime
的读者。阅读时建议同时打开 `app/agent_runtime/` 与
`tests/agent_runtime/`，按“契约 -> 执行 -> 记录 -> 验证”的顺序学习。

## 1. 从 RAG 到 Agent Runtime

普通 RAG 常被画成：问题 -> 检索 -> 拼 Prompt -> LLM 回答。这个流程能跑，
但企业系统还需要回答：谁能看哪份文档、一次请求最多调用几次工具、检索到的
文字如果包含恶意指令怎么办、回答依据是什么、失败后如何复盘。

Agent loop 是一个有状态循环：

```text
观察当前状态 -> 决定下一步 -> 调工具 -> 接收结果 -> 更新证据 -> 终止或继续
```

Harness 是包住这个循环的工程外壳。模型可以建议下一步，但 Harness 掌握工具、
权限、预算、超时、持久化和最终发布。这个项目的 Harness 主要在
`app/agent_runtime/`，原有 RAG 业务能力仍在 `app/agent/`、
`app/retrieval/` 和 `app/security/`。

## 2. Orchestrator 是什么

Orchestrator 负责“按什么顺序运行节点”，而不是“拥有全部业务权限”。统一接口
`AgentOrchestrator` 接收 `AgentRunRequest`，返回 `AgentRunResult`。

本项目保留两个实现：

- `BoundedControllerAdapter`：复用原来的 `run_agent_v2`，路径短、可预测；
- `LangGraphOrchestratorAdapter`：真实 `StateGraph`，适合显式状态和 HITL。

它们都不能直接查询 SQLite 或 FAISS，而是创建 `_ContractToolSession`，再走
`ToolGateway`。因此更换编排框架不会更换权限边界。这是“依赖倒置”的实际例子：
上层依赖稳定契约，下层实现可以替换。

阅读顺序：

1. 看 `AgentRunRequest` 的 question、trusted user、request/trace/session ID。
2. 看 `AgentRunResult` 如何区分 completed 与 needs_human_review。
3. 看两个 adapter 的 `run()`。
4. 看 `_ContractToolSession` 如何把业务工具调用转换成 ToolRequest。
5. 对照 `tests/agent_runtime/test_orchestrators.py` 看同一行为如何参数化测试。

## 3. Tool Contract 为什么重要

如果每个 Agent 节点直接调用任意 Python 函数，权限、错误和预算会散落在各处。
`tool_contract.py` 把边界固定为五个模型：

- `ToolDefinition`：工具名、说明、输入 schema；
- `ToolRequest`：本次 search/find/open 的严格参数；
- `ToolResult`：结构化成功/失败结果和最新预算；
- `ToolError`：安全错误码，不向客户端泄露内部异常；
- `ToolContext`：由服务端建立的身份、ACL、预算、deadline 和关联 ID。

`ToolGateway` 保存 active session。执行时依次检查 session 是否存在、context
是否完全匹配、是否过期、工具是否允许、参数是否有效、预算是否足够，再调用
既有 V2 工具。权限不是一句 Prompt，例如“只能访问本租户”，而是 Python
检查和检索层 ACL。

`context_request_id` 与工具步骤 `request_id` 被分开，是因为一次用户请求会产生
多个工具调用。前者绑定整次可信请求，后者定位单个步骤；把两者混在一起会让
第二个工具调用被误判为伪造上下文。

## 4. MCP 是什么，又不是什么

MCP 规定客户端怎样发现并调用工具。它解决互操作，不自动解决权限。

本项目路径是：

```text
MCP call -> EnterpriseKnowledgeMCP -> opaque handle -> ToolGateway -> V2 tools
```

`MCPContextBroker` 在服务端注册可信 `ToolContext`，返回随机 handle，只保存
handle 的 SHA-256。MCP 工具参数没有 tenant/user/groups；客户端无法靠修改
JSON 把自己变成另一个租户。`EnterpriseKnowledgeMCP` 使用官方 `mcp` SDK
注册 search/find/open，并将结构化结果返回给调用方。

当前测试是官方 SDK 的 in-process dispatch，不等于已部署网络 MCP。真正上线
还需要 TLS、OAuth/连接身份绑定、限流、审计和撤销策略。这一区分在面试中很
重要：协议适配完成，不代表生产身份系统完成。

## 5. LangGraph 在项目里做了什么

LangGraph adapter 的节点大致是：

```text
START -> analyze -> decide -> execute -> decide -> publish -> END
                              |
                              +-> human_review interrupt
```

状态包含 request、分析结果、工具执行、预算、节点轨迹和响应。图只编排；ACL、
Guard、Evidence Ledger 和 citation gate 仍是既有确定性代码。`recursion_limit`
和 `AgentBudget.max_steps` 是两层上限，避免错误路由形成无限循环。

为什么不直接删除自研 controller？因为框架迁移本身不会提高答案质量，而且会
扩大回归面。A/B 的结果正好验证了这一点：5 个机制案例结果一致，但 LangGraph
路径更慢。保留 alternative 的价值是可读状态图和 HITL，不是制造“用了框架就
更智能”的叙述。

## 6. Context engineering

Context engineering 不只是把更多文本塞进 Prompt。这里至少有四层：

1. 身份上下文：用户、租户、区域、组；只能由可信服务建立。
2. 执行上下文：session/trace/request、预算和 deadline。
3. 检索上下文：ACL 后可见候选，再经过 retrieved-content Guard。
4. 证据上下文：只有 admitted evidence 才能支持 claim 和 citation。

因此“检索到了”不等于“允许给模型”，“模型看到了”也不等于“允许发布”。
这种分层是企业 RAG 比普通 Demo 更重要的部分。

## 7. Trajectory 与 event sourcing

Trajectory 是一次 Agent 运行的语义日志。`AgentEvent` 有 session/trace/step、
递增 sequence、事件类型、时间、safe payload、latency/usage/error，以及
previous_hash 和 event_hash。

追加第 N 条事件时：

```text
event_hash_N = SHA256(canonical_json(event_N_without_hash))
previous_hash_N = event_hash_(N-1)
```

只要中间事件被改、删除或重排，后续链就不再一致。SQLite trigger 禁止普通
UPDATE/DELETE；hash chain 负责检测内容篡改。它是 tamper-evident，不是 WORM：
拥有机器权限的人仍能替换整个数据库。

Trajectory 不保存 raw `matched_text` / `context_text`，并对 secret/token/api_key
等键递归脱敏。事件的目标是复盘决策，不是复制敏感知识库。

## 8. Replay 不是重新运行

`replay_trajectory()` 先调用 store.verify，再按顺序恢复：用户输入、tool
requested/completed、evidence admitted、final output 和 terminal reason。它不
调用模型、Ollama、检索或网络，所以历史结果不会因为模型版本变化而改变。

“重新执行”会再次调用外部依赖，适合测试当前系统；“replay”读取已经发生的
事实，适合审计。当前项目只声明 deterministic replay，没有声明任意崩溃点的
durable resume。

## 9. HITL 为什么是一个安全流程

HITL 不是在 UI 放一个“确认”按钮。当前真实场景是：预算耗尽但只有 partial
evidence 时，LangGraph 产生 interrupt 和 `human_review.requested`。

恢复要求：

- reviewer 与原请求同 tenant；
- reviewer 有 `knowledge_reviewer` role；
- token 随机、服务端只存 hash；
- token 只能使用一次。

accept 只能发布已经受控的 partial response；reject 返回不含来源的安全结果。
`human_review.completed` 写入同一 trajectory。局限是 `InMemorySaver`：进程重启
后 pending review 丢失，因此不能叫 crash-safe durable HITL。

## 10. EvalOps Artifact

`AgentRunArtifactV1` 把一次运行封装成稳定 schema：input、output、trajectory、
retrieval steps、evidence metadata、usage、terminal。导出前必须通过 replay，
导出后再计算 artifact-level SHA-256。

运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_agent_runtime_sample --git-sha 9ff917bdf99b971a59754b731176e85d61f570e6
.\.venv\Scripts\python.exe -m scripts.verify_agent_run_artifact docs\agent_runtime\evidence\agent_run_artifact_sample_v1.json
```

第二个 EvalOps 项目无需理解本仓库数据库，只需读取 JSON schema 和 artifact。
这就是系统间 contract 的价值。

## 11. Agent Eval 怎样设计才可信

Stage I 固定同一 dataset、retrieval fixture、tools、budget、ACL、无模型的确定性
回答器，只改变 orchestrator。案例覆盖 answered、not_found、permission、unsafe
和 retrieved injection。

第一次实验出现 bounded 延迟异常高。原因不是 bounded 更慢，而是它先触发了
jieba 冷启动。修复不是删除异常数字，而是判定该 run 有 arm-order bias，增加
每个 arm 一次 discarded warm-up，再重新生成 artifact。这是实验工程中比“跑出
漂亮数字”更重要的能力。

最终 5/5 parity 只能说明迁移没有破坏这五种机制，不能说明真实问答准确率。
Graph p95 更高说明框架有成本。正确决策是保留可选实现，并继续以 bounded 为
默认参考。

## 12. Skill 和 Multi-Agent 为什么没做

Skill 应该封装重复出现的复杂 instruction、允许工具、证据要求、预算和终止
政策。当前五个机制案例不足以证明存在需要独立 Skill 的重复模式，所以 Stage H
没有实现。

Multi-Agent 会引入更多消息、权限传递、预算分配和失败组合。没有 single-agent
失败证据就加入它，只会扩大系统而无法证明价值。本轮明确不做，是工程取舍，
不是遗漏。

## 13. 建议的代码学习路线

1. `tool_contract.py` 和 `test_tool_contract.py`：理解数据与信任边界。
2. `tool_gateway.py`：理解授权、预算和 session state。
3. `orchestrator.py` 和 orchestrator tests：理解两种执行方式。
4. `trajectory.py`：理解 append-only 和 hash chain。
5. `replay.py`：理解历史事实的确定性恢复。
6. `evalops_artifact.py`：理解跨项目 schema。
7. `mcp_adapter.py`：理解协议层为什么不能绕过业务层。
8. `evaluation.py` 和 evidence JSON：理解 paired experiment。

## 14. 面试自检题

### Q1：为什么 MCP 不是安全边界？

因为 MCP 只定义工具发现和调用协议。客户端参数不可信，真正身份必须由服务端
会话提供，ACL/预算/Guard 必须在 MCP 后面的 Gateway 和业务层执行。

### Q2：为什么同时保留两个 controller？

自研 bounded controller 是已验证基线；LangGraph 提供显式图和 interrupt。
同契约 A/B 表明结果 parity、但 Graph 有额外延迟，因此不应无证据替换默认路径。

### Q3：hash chain 能防止管理员篡改吗？

它能检测事件内容、顺序和删除造成的不一致，但本地管理员可替换整库和程序。
更强保证需要外部签名、只追加存储、密钥管理和独立审计域。

### Q4：trajectory 和 OpenTelemetry 有何不同？

Trajectory 记录业务语义与决策；OTel 记录服务 span、延迟和错误。二者用
trace/session ID 关联，不应把完整敏感文档复制到任一系统。

### Q5：项目现在最该做什么？

若继续工业化，应优先做持久化 HITL、网络 MCP 身份绑定、trajectory retention
和更大外部端到端 Agent eval；不应先增加更多 Agent 或框架。

