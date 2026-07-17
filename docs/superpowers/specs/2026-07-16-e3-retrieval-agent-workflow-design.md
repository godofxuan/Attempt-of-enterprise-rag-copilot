# E3 ACL-aware Retrieval and Agent Workflow Design

状态：已由本人使用精确门禁命令 `批准E2，执行E3检索与Agent工作流` 批准进入实施。

日期：2026-07-16

## 1. 目标

把 E2 已验证的 v2 index 变成一条真正消费 `UserContext`、ACL、版本、authority 和 parent-child metadata 的 Agent 工作流。`QueryAnalysis` 必须改变检索过滤、子查询、工具或回答模式；`EvidenceLedger` 必须决定继续检索、回答、部分回答、权限拒绝或预算停止，而不是只生成展示字段。

E3 完成后新增显式 `/agent/v2/chat`。旧 `/chat`、`/agent/chat`、legacy `hybrid_search/load_indexes` 保持默认行为，直到 E4 用分层评测比较后再决定迁移。

## 2. 已比较方案

### A. 原地替换旧 Agent

优点是 API 和文件改动少。缺点是 E2 保留的 legacy baseline 被覆盖，任何质量变化同时混入索引、ACL、query analysis 和 Agent loop，无法做可信消融。

### B. 并行 v2 垂直链路，采用

保留旧 API，新增 typed v2 domain、retrieval、navigation 和 runner。优点是可以逐层 RED/GREEN、显式切换和回滚；缺点是 E3 期间有 legacy/v2 两套入口，需要文档明确边界。

### C. 只实现 ACL retrieval

风险最低，但 search/find/open、ledger、claim citation 仍不驱动真实回答，不能达到“有行为价值的 Agent”目标。

## 3. 范围

### E3 必做

- `UserContext`、`QueryAnalysis`、typed filters/search/navigation/result contracts。
- ACL/tenant/region 在 fusion、context、sources 和 trace 前 fail closed。
- active v2 index snapshot：FAISS、BM25、chunks、parents、documents 和 manifest 绑定加载。
- BM25/dense/RRF 三种 mode；metadata/temporal/authority filter；doc diversity；parent expansion。
- bounded `search/find/open`，Pydantic args、allowlist、budget、deadline 和 structured errors。
- rule-first QueryAnalysis；可注入 model fallback；unsafe 决策不可被模型覆盖。
- EvidenceLedger 保存 required aspects、support、conflict、missing、coverage 和 next action。
- comparison 按实体拆成受控子查询；completeness/process 可打开 parent/document 上下文。
- answer modes：`answered/partial/not_found/permission/unsafe/system/budget`。
- claim citation presence、visible-reference correctness、lexical support signal和 unsupported claims。
- `/agent/v2/chat` 要求显式 `UserContext`，旧 API 不变。
- deterministic tests、真实 demo dev 行为证据和完整实施记录。

### E3 不做

- reranker、向量数据库、Redis、队列、多 Agent、长期记忆。
- 真实 IAM/OAuth；demo `UserContext` 只模拟身份边界。
- 增量 upsert/delete；继续使用 E2 versioned full rebuild。
- OCR、Docker、OpenTelemetry exporter、负载测试和 UI 重做。
- 用 frozen test 调参；E3 开发只使用 deterministic fixtures 与 v2 dev。
- 删除 legacy router/planner/evaluator；只标记为 legacy baseline。

## 4. 架构与数据流

```text
AgentV2ChatRequest(question, UserContext)
-> deterministic unsafe gate
-> QueryAnalysis(intent, entities, subqueries, filters, required aspects)
-> V2AgentController + AgentBudget
-> search/find/open via ToolRegistryV2
-> ACLPolicy before fusion/context/source/trace
-> HybridRetrievalPipeline(BM25/dense/RRF)
-> diversity + parent expansion
-> EvidenceLedger(required/support/conflict/missing/coverage)
-> more bounded navigation OR stop reason
-> answer generator using visible evidence only
-> CitationVerifier
-> AnswerResponse(mode, claims, citations, visible sources, redacted trace)
```

unsafe 请求必须在 active index load、embedding、retrieval 和 generation 前结束。Index unavailable、embedding failure 和 malformed artifacts 返回 `system`，不得回退到无 ACL 的 legacy retrieval。

## 5. Domain contracts

### `app/domain/queries.py`

- `UserContext(user_id, tenant_id, region, groups, roles=[])`：每个字段非空，groups 去重。
- `QueryFilters(departments, policy_ids, statuses, as_of, authoritative_only)`：不允许请求覆盖 tenant/region。
- `QueryAnalysis(intent, original_question, search_queries, entities, required_aspects, filters, risk_flags, source)`。
- `SearchRequest(query, user, filters, top_k, candidate_k, mode, include_parent, max_chunks_per_doc, timeout_ms)`。
- `SearchHit`：只含可见 chunk，保留 fused/dense/BM25 rank/score、matched text、context text和 locator。
- `SearchResult`：hits、index run/hash、stage counts、stop reason；过滤统计只给数量，不给 denied IDs/titles。
- `FindRequest/FindResult` 与 `OpenRequest/OpenResult`：只能在 caller 可访问的 snapshot 内导航。

### `app/domain/evidence.py`

- `EvidenceItem`：required aspect、visible chunk、support/conflict 状态、authority/version。
- `EvidenceLedger`：required/supported/conflicting/missing aspects、coverage、recommended action。
- `ClaimCitation`：claim ID/text、chunk IDs、presence、visible-reference correctness、support signal。
- `AnswerResponse`：answer mode、answer、claims、citations、visible sources、warnings、redacted trace。

### `app/domain/agent.py`

- `AgentBudget`：search/find/open/step/context/deadline 上限。
- `BudgetState`：不可负计数，消费动作返回新状态或 structured budget error。
- `AgentAction`：typed tool、purpose、args summary。
- `AgentStopReason` 与 `AnswerMode`。

## 6. Security boundary

`app/security/access.py` 是唯一运行时 ACL 判断入口：

```text
tenant_id exact match
AND region exact match
AND intersection(user.groups, chunk.acl_groups) is non-empty
```

roles 不隐式绕过 groups。未来管理员能力必须另加显式 policy 和测试。

顺序固定为：

```text
load validated snapshot
-> build visible index set
-> metadata/temporal/authority filters
-> score/rank visible candidates
-> fusion
-> context/source/trace projection
```

实现可让 FAISS 计算全 index 距离，但未授权 chunk object/ID/title/text 不得构造成 fusion candidate，也不得进入日志。Permission outcome 只返回泛化提示，不暴露被拒文档名称或数量。

## 7. Retrieval pipeline

`V2IndexSnapshot` 一次绑定 E2 active manifest 与 artifacts。`chunks.json` 顺序必须与 FAISS/BM25 行号相同；parents/documents 建只读 map。加载先复用 E2 hash/count validation，再反序列化 pickle。

`HybridRetrievalPipeline.search(request)`：

1. 根据 ACL 和 filters 计算 visible indices。
2. BM25 从全局 token corpus取分数，但只为 visible index 创建候选。
3. dense 通过 E2 manifest model/dimension 生成并 L2 normalize query；只把 visible index 写入候选。
4. RRF 在 filtered dense/BM25 rank 上融合。
5. 按 authority、active/current metadata做显式 deterministic tie-break/boost，不隐藏在 prompt。
6. 每 doc 限制 chunks，避免同一文档挤满 top-k。
7. child 命中时可把 parent text 作为 `context_text`，citation 仍指 child。

mode 支持 `bm25/dense/hybrid`，不实现 reranker。零 visible candidate 时内部区分 `no_visible_evidence` 与 `no_match`，对外 response 不泄露 denied metadata。

## 8. QueryAnalysis

`app/agent/query_analysis.py` 先执行 deterministic unsafe、comparison、completeness、process、historical/current 和实体提取规则。规则产生行为：

- comparison：每个比较实体生成独立 search query 和 required aspect。
- completeness：要求 policy coverage，并允许 `open` 扩展完整上下文。
- process：偏向 heading/parent context。
- historical/current：写入 status/as-of filter。
- unsafe：answer mode unsafe，零工具预算消费。

只有非 unsafe 且规则无法形成有用 entities/subqueries 时才调用可注入 fallback。fallback 输出必须重新经过 Pydantic、长度、实体保留和 filter allowlist 校验；不能改变 user tenant/region/groups，不能删除 risk flags。

## 9. Navigation tools

- `search`：跨可见 chunks 的 BM25/dense/hybrid retrieval。
- `find`：在一个已授权 doc 内按 token/substring找 section/chunk，返回有限 match。
- `open`：按 chunk ID 或 doc ID 打开有限字符的 parent/document 内容。

工具参数和输出都是 Pydantic。每次调用先消费 budget、检查 deadline 和 allowlist；失败返回 `ToolError(code, retryable, safe_message)`。Controller 只根据 structured code 决定下一步，不解析异常文本。

## 10. EvidenceLedger 与停止策略

每个 required aspect 至少需要一条当前可见 evidence。comparison 的两方是两个独立 aspect，只找到一方得到 `partial` 而不是 `answered`。Ledger 记录支持/冲突 chunk IDs、authority/version 和 missing aspects。

推荐动作：

```text
all aspects supported, no unresolved conflict -> answer
some supported, budget available -> search/find/open missing aspect
some supported, budget exhausted -> partial or budget
none supported, denied-only internal signal -> permission
none supported, no match -> not_found
conflict with resolvable authority/date -> resolve then answer
system/tool failure -> system
```

Controller 有显式状态机和最大 steps。模型不得自行增加预算或调用未注册工具。

## 11. Generation 与 citation verification

Generator 只接收 ledger 选出的 visible evidence，source 编号与 chunk ID 固定。v2 adapter 可以复用现有 Ollama chat transport，但不得调用 legacy `hybrid_search`。

CitationVerifier 将 answer 拆为 claims，检查：

- claim 是否有 citation；
- citation 是否引用本 request visible evidence；
- cited chunk 是否有最小 lexical support signal；
- unsupported claim 列表。

Referential correctness 是确定性边界，不冒充语义 entailment。若关键 claim 没有有效 citation，answer mode 降为 `partial` 或 `system`，并在 warnings 中说明，不把不可验证 claim 当成功回答。

## 12. API compatibility

保留：

- `/chat -> ChatResponse`
- `/agent/chat -> AgentChatResponse` legacy baseline

新增：

```text
POST /agent/v2/chat
request: question, top_k?, user_context(required)
response: AnswerResponse
```

不提供隐式管理员或默认全权限用户。缺少 `user_context` 由 FastAPI/Pydantic 返回 422。E3 不改变 startup 自动构建 legacy index 的行为。

## 13. Testing strategy

所有 production 行为先 RED 后 GREEN：

- `tests/domain_v2/`：类型、跨字段不变量、extra forbid。
- `tests/security/`：tenant/region/group、zero leak、redaction。
- `tests/retrieval/`：active snapshot、BM25/dense/RRF、filter-before-fusion、authority/current、diversity、parent expansion、Unicode path。
- `tests/agent_v2/`：analysis behavior、tool budget/deadline、comparison decomposition、ledger outcomes、citation verifier、API compatibility。

测试默认使用 E2 fake embedder 和临时 version store，不访问 Ollama。live model 只作为单独非门禁命令，并记录 NOT RUN/unstable。

阶段最终门禁：focused suites、legacy Agent regression、full pytest、frozen E1 test hash、CLI dry-run、pip check、compileall、git diff、Git lock 和后台进程。

## 14. Observability 与记录

E3 先实现 request-local redacted trace，不在本阶段接 OpenTelemetry exporter。Trace 可记录 action、latency、visible candidate count、budget 和 stop reason；不得记录 denied IDs、ACL 列表、完整 chunk text、密码/token 或模型原始敏感输出。

每个 Change/Incident/Experiment 更新：

- `docs/roadmap/e3_retrieval_agent_workflow_implementation.md`
- `docs/roadmap/engineering_decision_failure_ledger.md`
- `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`
- E3 beginner learning/interview card。

## 15. Git 与阶段边界

当前 E0-E2 工作树未提交。本人只批准 E3 实施，没有批准 commit、push、merge、tag、默认分支修改或仓库重命名，因此 E3 继续在当前工作树小步编辑并保留完整 diff。

E3 完成后停止在 E3/E4 边界，等待精确命令 `批准E3，执行E4评估与消融`。
