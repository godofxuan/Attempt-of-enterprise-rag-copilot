# E3 ACL-aware Retrieval 与 Agent 工作流实施记录

最后更新：2026-07-16

状态：complete，等待用户验收；尚未进入 E4

批准命令：`批准E2，执行E3检索与Agent工作流`

## 1. 本阶段要解决什么

E2 已经能把企业文档安全地解析、治理、切块并构建为可回滚的 v2 index，但 production `hybrid_search` 和旧 Agent 仍读取 legacy index，也没有显式 UserContext/ACL pre-filter。

E3 新增一条兼容的 v2 垂直链路：

```text
question + required UserContext
-> unsafe gate
-> QueryAnalysis
-> ACL/metadata-aware retrieval
-> bounded search/find/open
-> EvidenceLedger
-> answer mode + claim citations
-> redacted trace
```

旧 `/chat`、`/agent/chat` 和 legacy `hybrid_search` 保持不变，作为 E4 消融基线。

## 2. 权威设计与计划

- 详细设计：`docs/superpowers/specs/2026-07-16-e3-retrieval-agent-workflow-design.md`
- TDD 计划：`docs/superpowers/plans/2026-07-16-e3-retrieval-agent-workflow.md`
- 当前断点：`docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`
- 跨阶段索引：`docs/roadmap/engineering_decision_failure_ledger.md`

## 3. 开工基线

```text
workspace: <repo-root>
branch: codex/rag-eval-system
HEAD: 7aec4b950e012d3f24b8e1877d6391201e9b8f90
checkout: normal checkout, not linked worktree
project background Python/pip: 0
git index.lock: absent
full pytest: 225 passed, 5 warnings
commit/push/merge/tag: not authorized
```

不创建新 worktree：E0-E2 是当前 checkout 中未提交的前置代码，新 worktree 只包含 HEAD，无法看到这些 contracts。该选择来自已有 handoff 约束，不是忽略隔离原则。

## 4. 安全不变量

1. unsafe 在 index load、embedding、retrieval、generation 前短路。
2. tenant、region、group 三项都满足才可见；roles 不绕过 groups。
3. denied chunk 不进入 fusion、context、sources、response trace 或 public error。
4. 模型不执行 ACL、budget、allowlist 或 stop decision。
5. v2 失败不回退到无 ACL 的 legacy retrieval。
6. frozen test 不读取、不调参、不修改。

## 5. Change 状态

| ID | 行为变化 | 状态 | RED | GREEN/证据 |
|---|---|---|---|---|
| `E3-C01` | typed query/evidence/agent domain contracts | complete | 3 x `ModuleNotFoundError: app.domain.*` | 25 domain tests；77 E2 regression tests passed |
| `E3-C02` | ACL policy 与 trace redaction | complete | `ModuleNotFoundError: app.security` | 13 security；115 combined regression tests passed |
| `E3-C03` | validated active v2 snapshot | complete | `ModuleNotFoundError: app.retrieval` | 6 snapshot；56 combined regression tests passed |
| `E3-C04` | ACL-aware BM25/dense/RRF pipeline | complete | 3 x `ModuleNotFoundError: app.retrieval.pipeline` | 12 pipeline；133 combined regression tests passed |
| `E3-C05` | typed search/find/open navigation | complete | 2 x `ModuleNotFoundError: app.retrieval.navigation` | 13 navigation；146 combined regression tests passed |
| `E3-C06` | rule-first QueryAnalysis | complete | `ModuleNotFoundError: app.agent.query_analysis` | 20 analyzer；34 legacy-focused；171 combined passed |
| `E3-C07` | EvidenceLedger 与 citation verifier | complete | 2 x `ModuleNotFoundError: app.agent.evidence_ledger/citation_verifier` | 9 ledger；7 citation；187 combined passed |
| `E3-C08` | bounded v2 controller/tools/runner | complete | 3 x module-missing RED (`tools_v2/controller_v2/runner_v2`) + config helper RED | 25 C08；77 agent/security；22 legacy；234 combined passed |
| `E3-C09` | generation adapter 与 `/agent/v2/chat` | complete | generation module-missing + 5 API contract failures | 9 generation；5 API/security；19 compatibility；250 combined passed |
| `E3-C10` | dev evidence、学习卡与阶段验收 | complete | evaluator module-missing；initial dev 20/24；writer transient rename RED | anchor-gate dev 24/24；focused 155；legacy 24；full 380 passed |

## 6. Incident/Experiment 状态

| ID | 类型 | 症状/问题 | 判断 | 结果 |
|---|---|---|---|---|
| `E3-I01` | workflow | linked worktree 会看不到 E0-E2 未提交前置代码 | 继续当前 checkout，小步 TDD、禁止 Git 写操作 | baseline 225 passed |
| `E3-I02` | code edit | 首次 GREEN collection 报 `app/domain/__init__.py:65 IndentationError` | patch 把部分 `__all__` 名称插到 list 结束符之后 | 只修导出列表结构；25 domain + 77 E2 tests passed |
| `E3-I03` | test fixture | C04 首轮 GREEN 为 11 passed、1 `TypeError` | 参数化 case 同时显式传 `doc_id` 和通过 `**parent_updates` 再传一次；失败发生在 fixture 调用前，不是 pipeline | 改为默认 dict 后 `update()` 覆盖，原 ACL 断言不变；12 pipeline + 133 combined passed |
| `E3-I04` | pytest fixture scope | C05 首轮 GREEN 为 10 passed、3 setup errors：security 目录找不到 `chunk_factory` | fixture 定义在 sibling `tests/retrieval/conftest.py`，Pytest 只向该目录子树提供 | 根级 `tests/conftest.py` 显式共享同一 fixtures；13 navigation + 146 combined passed |
| `E3-I05` | contract gap | 既定 `verify_claims(claims, visible_hits)` 无法知道每条 claim 声称引用哪些 chunk | C01 `Claim` 缺 citation candidate 字段；只有 verifier 输出 `ClaimCitation` | 给 `Claim` 增加默认空 `cited_chunk_ids`，旧构造兼容，verifier 去重并做 hard checks；26 C07/domain + 187 combined passed |
| `E3-I06` | plan/artifact mismatch | C10 计划示例写 `demo_dev.jsonl/metadata.json`，仓库实际不存在 | E1 canonical contract 是 `eval/dev.json` JSON array + `test_manifest.sha256` | evaluator 读取真实 dev contract，不另造重复数据，不读取 frozen test |
| `E3-I07` | Windows artifact promotion | 第二个 dev run 计算完成，staging rename 报 `WinError 5`；target 不存在 | 后台 0、ACL 可写、staging 已清理，最可信是瞬时目录 rename 拒绝 | 绝对路径 + 只对 PermissionError 有界重试 + 并发 target 检查；writer 6 tests，重跑成功 |
| `E3-I08` | final gate diagnostics | 并行门禁先显示 frozen hash mismatch、后台进程 1 和 pytest cache WinError 5 | manifest 比较误含文件名；进程检查把并行 pytest 自己计入；旧 `.pytest_cache` 关闭 ACL 继承，Python sandbox SID 无目录访问权 | 按首 token 比 hash、测试结束后查进程、只对 cache 恢复 ACL 继承；复现命令转绿，全量回到 380 passed/5 warnings |

## 7. 实时实施日志

### E3 启动

读取了总体 E3 plan、E0 architecture、legacy router/planner/controller/tools/evidence/runner、API schemas 和既有 Agent tests。确认旧 Agent 已有“最多重试一次”的状态机，但主要问题是：

- route/planner 与 `classify_question_type` 重复猜意图；
- retrieval tool 直接调用 legacy `hybrid_search(question, top_k)`，没有 UserContext；
- evidence assessment 只有 sufficient/insufficient/error，不能表达 required aspects、冲突和 partial；
- tools 仍是 dict context，没有 typed args/budget/deadline；
- trace 可能保存 output summary，但没有统一 redaction contract；
- `/agent/chat` request 没有身份上下文。

选用并行 `/agent/v2/chat`，不原地替换旧 endpoint。E3-C01 从独立 domain contracts 开始，避免安全状态继续依赖任意 dict key。

### E3-C01：typed domain contracts

先新增三组 tests，不创建 production modules：

```text
tests/domain_v2/test_query_models.py
tests/domain_v2/test_evidence_models.py
tests/domain_v2/test_agent_models.py
```

RED 是三个明确的 import failure：`app.domain.queries`、`app.domain.evidence`、`app.domain.agent` 不存在。这证明新 tests 没有误用 legacy `app.agent.schemas`。

新增 production files：

```text
app/domain/queries.py
app/domain/evidence.py
app/domain/agent.py
```

`queries.py` 把身份、分析和 retrieval I/O 分开：

- `UserContext` 要求 user/tenant/region/至少一个 group，拒绝 duplicate groups 和额外 `is_admin` 字段；roles 不能替代 groups。
- `QueryFilters` 不包含 tenant/region，因此调用者不能通过检索参数覆盖身份作用域；as-of 与 temporal scope 有跨字段校验。
- `QueryAnalysis` 让 unsafe 零 search work；safe analysis 必须有 query/aspect；comparison 至少两实体和两子查询。
- `SearchRequest` 限制 top-k/candidate/mode/timeout；`candidate_k >= top_k`。
- `SearchHit/Result` 绑定同一 index run，拒绝 duplicate chunk IDs；`internal_denied_count` 使用 `exclude=True`，可供 controller 内部区分 permission，但不会被普通 `model_dump()` 带到公共 trace。
- `Find/Open` 不接受 filesystem path，只接受 doc/chunk/parent ID 和 caller UserContext。

`evidence.py` 把证据状态变成可验证集合：supported 与 missing 必须恰好划分 required aspects，coverage 必须等于 supported/required；unresolved conflict 必须留在 missing；只有 full non-conflicting coverage 才能推荐 answer。

`AnswerResponse` 明确七种 answer mode。answered 必须有 claims/citations/sources，unsafe/permission/not_found/system/budget 不得暴露 sources。`ClaimCitation` 区分 citation presence、是否引用 visible evidence 和 lexical support；它仍不冒充语义 entailment。

`agent.py` 定义 hard budget、used counters、structured `ToolError` 和 typed `AgentAction`。search action 必须且只能携带 SearchRequest，terminal action 不能夹带任何 tool request。

第一次 GREEN 没有进入 validators，而是 `app/domain/__init__.py:65 IndentationError`。读取带行号文件后发现 `__all__` 的九个名称落在 `]` 后面。只移动这些名称回 list，再运行：

```text
tests/domain_v2                 25 passed
tests/ingestion + tests/indexing 77 passed, 3 existing FAISS warnings
compileall                      ok
git diff --check                clean
```

这一步只建立“哪些状态允许存在”的 contract，尚未实现 ACL decision 或 retrieval。

### E3-C02：ACL policy 与 trace redaction

RED：`tests/security/test_access_policy.py` 和 `test_trace_redaction.py` 都在 collection 阶段报 `ModuleNotFoundError: app.security`。

新增 `app/security/access.py` 作为唯一 ACL decision 入口。当前 demo 规则是三项同时成立：

```text
user.tenant_id == chunk.tenant_id
AND user.region == chunk.region
AND intersection(user.groups, chunk.acl_groups) non-empty
```

roles 被保留在 UserContext，但当前 policy 明确不让 `admin` role 绕过 group。缺 tenant/region/groups、空 group 或 ACL 不是 list 都返回 malformed 并 fail closed。

`visible_chunks/visible_indices` 只返回 allowed objects/indices 和 denied count，不保存 denied object。输入经 deepcopy 对比证明没有被修改。`safe_access_error` 把 tenant/region/group/malformed 四类内部原因统一投影为：

```text
code=permission
The requested resource is unavailable for this identity.
```

public message 不出现目标 tenant、group 或文档存在性。

`redact_trace_payload` 递归创建新结构并删除 chunk/doc/parent ID、title、source path、ACL、text/context/preview/content 和 internal/denied fields；同时掩码常见 password/token/api_key 赋值。它不是 DLP 系统，只是 E3 request-local trace 的最小 fail-closed projection。

GREEN：

```text
tests/security                              13 passed
domain/security/ingestion/indexing combined 115 passed
compileall                                  ok
git diff --check                            clean
```

当前还没有 retrieval candidate，因此 C02 只证明单资源判断和 projection contract；C04 才验证 denied high-score chunk 不进入 fusion。

### E3-C03：validated active v2 snapshot

新增 `tests/retrieval/conftest.py`，用 E1 demo corpus、parent-child chunker 和 fake 4D embedder 在 pytest 临时目录构建并激活 E2 run。RED 为 `ModuleNotFoundError: app.retrieval`。

新增 `app/retrieval/snapshot.py`。`V2IndexSnapshot.load(root)` 的顺序不能交换：

```text
E2 load_index_version
-> active pointer + manifest/artifact hash/count validation
-> manifest algorithm allowlist
-> JSON -> DocumentRecord/ChunkRecord
-> pickle/FAISS deserialize
-> row/ID/parent/document cross-check
-> immutable tuple + MappingProxyType maps
```

当前只允许 E2 builder 已证明的 `IndexFlatIP + inner_product + l2 + jieba`。manifest 写其他算法时不静默猜测兼容性。

Snapshot 保留 `chunk_index_by_id`，它把 `chunks.json` 的顺序固定映射到 FAISS/BM25 row；parent 与 indexed chunk ID 不能冲突；每个 child parent 和每个 chunk document 都必须存在。

篡改测试翻转 `bm25_tokens.pkl` 一个字节，并 monkeypatch `pickle.load` 为一旦执行就抛 AssertionError。实际得到 artifact hash mismatch，证明危险反序列化没有发生。Unicode `中文索引` store 也能加载。

GREEN：

```text
tests/retrieval/test_snapshot.py             6 passed
snapshot + E2 store/builder + domain/security 56 passed
compileall                                   ok
git diff --check                             clean
```

C03 只加载快照，不计算 query embedding 或检索分数。

### E3-C04：ACL-aware hybrid retrieval pipeline

先新增三组测试：

```text
tests/retrieval/test_pipeline_acl.py
tests/retrieval/test_pipeline_ranking.py
tests/retrieval/test_pipeline_parent.py
```

三组测试在 production module 不存在时分别 collection 失败，RED 都是 `ModuleNotFoundError: app.retrieval.pipeline`。随后新增 `app/retrieval/pipeline.py` 和 `HybridRetrievalPipeline` 导出。

管线执行顺序不是“先搜到再删掉”，而是：

```text
validated immutable snapshot
-> ACL visible row indices
-> metadata/version filters
-> BM25 and/or dense candidates restricted to visible rows
-> RRF fusion or single-channel score
-> deterministic authority/current/chunk-id tie break
-> per-document diversity
-> authorized same-document parent context expansion
-> typed SearchResult with aggregate-only diagnostics
```

关键安全边界：

- denied chunk 即使 BM25 或 dense 分数最高，也不进入 fusion、hits、parent context 或 `model_dump()`。
- `internal_denied_count` 只供后续 controller 判断“无结果还是无权限”，Pydantic 字段设置为 `exclude=True`，不能成为 API/trace 输出。
- parent 只有在同一 `doc_id`、通过同一 ACL 和元数据过滤时才扩展 `context_text`；citation 仍指向命中的 child。
- BM25-only 路径不调用 embedding；dense query 会检查维度、有限值和非零向量。
- stable sort 和每文档上限避免相同分数时顺序随机，也避免一个长文档占满 top-k。

首轮 GREEN 出现的唯一失败不是 production failure：参数化 parent test 同时显式传入默认 `doc_id` 和覆盖 `doc_id`，Python 在调用 fixture 前抛 `TypeError`。修复只改变测试输入的合并方式，没有改变断言或检索实现。

验证证据：

```text
pipeline ACL/ranking/parent                    12 passed
retrieval + security + domain_v2 + E2 modules 133 passed
```

这一步证明的是 synthetic snapshot 下的检索与零泄漏 contract；还没有证明真实问答质量，也还没有把 v2 pipeline 接到 API。C05 将在同一 snapshot 上实现受控 `search/find/open` 文档导航。

### E3-C05：typed and bounded document navigation

测试先扩展 `tests/retrieval/conftest.py`：增加 `document_factory`，并允许 `snapshot_factory` 携带 `DocumentRecord` map。这样 document open 使用真实 E2 domain contract，而不是在测试中拼临时 dict。

新增：

```text
app/retrieval/navigation.py
tests/conftest.py
tests/retrieval/test_navigation.py
tests/security/test_navigation_zero_leak.py
```

两个测试模块最初都以 `ModuleNotFoundError: app.retrieval.navigation` 正确 RED。实现后的职责分工：

```text
search(request)
  -> 调用同一 HybridRetrievalPipeline
  -> 把 timeout / ValueError / unexpected exception 映射为固定 ToolError

find(request)
  -> snapshot.documents_by_id 精确定位 document
  -> document ACL
  -> 只扫描同 doc 的 snapshot chunks/parents
  -> 每个 chunk 再做 ACL
  -> substring 或 tokenizer token-set match
  -> locator + chunk_id 稳定排序，受 max_results 限制

open(request)
  -> target_type 决定只查 chunk_index / parents / documents map
  -> resource ACL
  -> 返回最多 max_chars，标记 truncated
```

工具参数没有 filesystem path 字段，也不从 `target_id` 拼路径。授权用户可以看到可见资源自身的 `source_path`；拒绝或不存在时只返回固定安全消息，不回显 ID、title、path、text 或底层异常。内部 `permission` 与 `not_found` code 供后续 Python controller 决策，但两者 `safe_message` 完全相同。

deadline 使用可注入 monotonic clock：调用前后检查；search 还把 pipeline 的 timeout stop reason 投影为 retryable timeout error。`ValueError` 映射为 non-retryable `invalid_args`，其他 `Exception` 映射为 retryable `system`，异常字符串不会成为用户或模型输入。

首轮 GREEN 的 3 个 errors 来自 Pytest fixture scope，而不是 navigator：`tests/retrieval/conftest.py` 对 sibling `tests/security` 不可见。增加根级 fixture export 后，安全测试与检索测试复用同一 synthetic model factory。

验证证据：

```text
navigation focused                              13 passed
retrieval + security + domain_v2 + E2 modules  146 passed
compileall app/tests                            ok
git diff --check                                exit 0 (only existing CRLF notices)
```

C05 证明了受控导航 primitives，还没有证明 Agent 会在正确时机选择它们。C06 将先做 deterministic query analysis，C08 才由 controller 按 budget/allowlist 调用这些工具。

### E3-C06：rule-first QueryAnalysis

新增：

```text
app/agent/query_analysis.py
tests/agent_v2/test_query_analysis.py
```

RED 是 `ModuleNotFoundError: app.agent.query_analysis`。新 `RuleFirstQueryAnalyzer` 没有修改 legacy `route_query`，而是为 v2 生成强类型 `QueryAnalysis`。

执行顺序：

```text
strip/validate question
-> deterministic risk rules
-> unsafe: zero search_queries / zero required_aspects / no fallback
-> temporal language -> QueryFilters
-> comparison entity extraction
-> completeness/process/fact behavior
-> only ambiguous comparison may call injected fallback
-> validate and merge candidate under Python invariants
```

风险规则输出类别而非单个布尔值：`prompt_injection`、`policy_bypass`、`credential_exfiltration`、`data_exfiltration`、`fabrication`。英文凭证规则使用 word boundary，所以 `tokenizer` 不会因为包含 `token` 子串被误判；这修正了 legacy keyword list 的一个已知粗粒度问题，但 C06 没有反向修改 baseline。

行为字段示例：

- `《差旅政策》` vs `《费用报销政策》` -> `comparison`、两个 entities、两个独立 search queries、两个 required aspects。
- “列出全部材料” -> `completeness` + `complete_policy_coverage`。
- “如何办理” -> `process` + `process_steps`。
- “截至 2025-06-30” -> `temporal_scope=as_of` 和真实 `date`。
- “历史版本/历次版本” -> `historical/all`，而不是只写 prompt 标签。

fallback 是 protocol，可在未来由 LLM adapter 实现，但当前测试用 fake。它只在规则看出 comparison、却提取不到两个有意义实体时调用。候选输出重新经过 `QueryAnalysis.model_validate()`，并强制：

- `original_question` 必须逐字保持；
- 不能通过 extra fields 注入 tenant/region/group；
- search queries 不能超过 domain 上限；
- deterministic as-of/all/historical/current 显式约束优先；
- deterministic unsafe 在 fallback 前返回，模型没有把 unsafe 改为 safe 的机会；
- fallback exception 不透传敏感异常文本，降级为可执行的 rule-only fact analysis。

测试证据：

```text
query analysis focused                          20 passed
analyzer + legacy router + query domain         34 passed
agent_v2 + retrieval/security/domain/E2/legacy 171 passed
```

当前局限：规则只覆盖明确中英文模式；无引号且句法复杂的多实体比较可能降级或依赖 fallback；风险分类是输入侧 deterministic guard，不等于完整内容安全模型。C07 不再判断“用户想做什么”，而判断“每个 required aspect 是否有可见证据、是否冲突、能否回答”。

### E3-C07：EvidenceLedger and claim citation verification

新增：

```text
app/agent/evidence_ledger.py
app/agent/citation_verifier.py
tests/agent_v2/test_evidence_ledger.py
tests/agent_v2/test_citation_verifier.py
```

并向 `Claim` 增加默认空的 `cited_chunk_ids`。这是实现 `verify_claims(claims, visible_hits)` 必需的候选输入，不是最终可信结果；最终状态仍由 `ClaimCitation` 保存。

#### Ledger 如何建账

`build_ledger()` 不从 answer 文本或模型自报字段推断 support。它只接受：

1. `QueryAnalysis.required_aspects`，定义题目必须覆盖什么；
2. controller/tool purpose 形成的 `evidence_by_aspect` mapping；
3. 已经过 ACL 的 typed `SearchHit`。

mapping 出现不属于 required aspects 的 key 会失败，不能让模型在检索后改写验收目标。每个 hit 转成 `EvidenceItem(aspect, chunk/doc/version, authority, status, relation)`。

决策示例：

```text
comparison only A visible       -> supported [A], missing [B], coverage 0.5, search
A and B visible                 -> coverage 1.0, answer
equal authority/status conflict -> aspect remains missing, search
higher authority/current winner -> conflict deterministically resolved
zero visible + denied-only      -> permission
zero visible + no denied        -> not_found
budget + partial evidence       -> partial
budget + no evidence            -> budget
```

冲突优先级当前只比较 `(authority_level, active-over-retired)`。不同优先级可确定性选择；完全相同则不猜测，留在 `conflicting_aspects` 和 `missing_aspects`。这不是语义冲突检测器，`conflicts` 仍需 controller 从多次检索/版本关系传入。

#### Citation verifier 检查什么

按顺序执行：

```text
citation present?
-> every cited chunk ID belongs to this request's visible hits?
-> claim tokens overlap cited visible evidence tokens?
-> ClaimCitation
```

missing citation、unknown/denied-like ID、visible-but-zero-overlap 分别产生固定 unsupported reason。unknown 与 denied 不查询全局 snapshot，因此 verifier 无法也不会告诉模型某个不可见 ID 是否真实存在。重复 citation 只在 verifier 输出中稳定去重；重复 visible hit ID 则拒绝，避免同一 ID 映射到不同内容。

`lexical_support = overlap(claim_tokens, evidence_tokens) / claim_tokens`。它只说明词面有交集：不能处理同义词、否定、单位换算、数值蕴含或跨句逻辑，因此命名为 heuristic support signal，不能宣传成 factuality/entailment judge。C09 仍需在关键 claim 不通过时降级 answer mode。

验证证据：

```text
ledger focused                                  9 passed
citation focused                                7 passed
C07 + evidence domain                          26 passed
agent_v2 + retrieval/security/domain/E2/legacy 187 passed
```

C07 已决定“证据是否覆盖要求”，但还没有执行循环。C08 将把 analyzer、navigator 和 ledger 放入 Python 强制的 tool allowlist、budget 和 bounded state machine。

### E3-C08：bounded tools, controller and runner

新增：

```text
app/agent/tools_v2.py
app/agent/controller_v2.py
app/agent/runner_v2.py
tests/v2_test_support.py
tests/agent_v2/test_tools_v2.py
tests/agent_v2/test_controller_v2.py
tests/agent_v2/test_runner_v2.py
tests/security/test_agent_trace_zero_leak.py
```

并在 `app/config.py` 增加六个受 Pydantic 范围约束的 v2 budget settings。每层都先出现独立 module-missing RED；配置映射另以 `budget_from_settings` import error 证明 RED。

#### Registry：执行边界

`V2ToolRegistry.run(action, budget_state)` 只接受 typed `AgentAction`，allowlist 固定为 `search/find/open`。任意字符串工具名无法通过 AgentAction；`answer/refuse/stop` 是 controller terminal action，送入 registry 会得到 `invalid_args`，不会执行 navigator。

预算语义：

- search/find/open 分别计数，另有全局 tool steps、context chars、deadline。
- call/step/context 已耗尽或 deadline 已到：执行前拒绝，state 不变。
- result content 大小只能执行后知道；若新增字符会越界，丢弃 payload、返回 budget error，但已发生的 call/step 仍计数，context chars 不增加。
- navigator exception 只变成固定 retryable system error，不透传异常文本。

#### Controller：显式状态机

接口是：

```text
initialize(QueryAnalysis, UserContext, budget)
-> ControllerState
next_decision(state)
-> ControllerDecision(typed AgentAction + optional terminal outcome)
registry.run(action, budget)
-> V2ToolExecution
observe(state, execution)
-> new ControllerState + rebuilt EvidenceLedger
```

主要 trajectory 已自动测试：

```text
unsafe       -> refuse (zero tools)
fact         -> search(answer) -> ledger -> answer
comparison   -> search(A) -> search(B) -> ledger -> answer/partial
completeness -> search -> open(visible document ID) -> answer
no match     -> not_found
denied only  -> permission
partial + max steps -> partial
deadline before first call -> budget
tool system error -> system
```

没有递归。missing aspect 的顺序来自 `QueryAnalysis.required_aspects`，对应 query 来自同序的 bounded `search_queries`。controller 不能发明 tenant/group filter，open target 只能来自先前 visible hit 的 doc ID。

#### Runner：编排与 trace

`V2AgentRunner` 只执行 controller decision 和 registry result。C08 暂时提供 `ExtractiveResponseBuilder`：逐 supported aspect 选择一个 visible hit，原样形成 claim，立即调用 C07 verifier；它不调用 LLM，也不复用 legacy `answer_from_retrieved/hybrid_search`。C09 将通过同一个 `ResponseBuilder` protocol 接入结构化生成。

trace 每步只记录：sequence、tool、status、latency、visible count、context chars added、error code 和聚合 budget。它不记录 query、action args、chunk/doc ID、title、path、文本、ACL 或 denied count；最后再经过 `redact_trace_payload()` 防御性投影。

验证证据：

```text
registry focused                                  6 passed
controller trajectories                           9 passed
runner + trace security                           10 passed
all agent_v2 + security                           77 passed
legacy controller + adaptive runner + API         22 passed
E2/E3/selected legacy combined                   234 passed
```

当前不能宣称“LLM 自主规划”：C08 是 deterministic bounded orchestration，LLM 尚未参与 action selection。它的工程价值是工具执行和停止规则可复现、可测、不可由 prompt 绕过。

### E3-C09：structured generation and `/agent/v2/chat`

新增：

```text
app/agent/generation_v2.py
tests/agent_v2/test_generation_v2.py
tests/agent_v2/test_api_v2.py
tests/security/test_api_v2_zero_leak.py
```

修改：

```text
app/agent/runner_v2.py
app/schemas.py
app/main.py
```

#### 生成输入边界

`GenerationV2ResponseBuilder` 实现 C08 的 `ResponseBuilder` protocol。它只遍历 `ledger.supported_aspects`，再从对应 `state.evidence_by_aspect` 取 visible hits；state 中其他 key 即使存在也不序列化。prompt source 依 required aspect 和 hit 顺序稳定编号为 `S1..S8`。

每 source 最多使用 1200 字符 hit/parent context；同一可见 doc 的 authorized open content 最多 2000 字符；总 evidence context 最多 8000 且不超过 request budget。prompt 包含 original question 和 analysis intent，不包含 filesystem path、ACL、denied count 或未选 evidence。

模型只能返回 strict JSON：

```text
answer
claims[]:
  claim_id
  text
  critical
  cited_source_ids: [S1, ...]
```

JSON/字段/claim ID/source ID 任一非法即 source-free `system`，不回退 extractive 或 legacy retrieval。合法 source ID 映射回 visible chunk ID，随后运行 C07 verifier；critical claim 不通过时 answer mode 降为 `partial`。这仍不是语义事实核验，lexical verifier 的限制保持不变。

#### API 与 lazy construction

新增 `AgentV2ChatRequest(question, user_context, top_k)`；`UserContext` 必填，groups 非空，top_k 为 1..20，extra fields 禁止。新 endpoint 是 `/agent/v2/chat`，response model 直接使用 `AnswerResponse`。旧 `ChatRequest`、`/chat`、`/agent/chat` 未改字段和实现。

`run_agent_v2_chat` 先调用 deterministic analyzer：

```text
unsafe -> generic unsafe response, zero tool/index/model construction
safe   -> cached _get_default_v2_runner()
       -> active v2 snapshot + dense embed adapter + navigator + registry
       -> GenerationV2ResponseBuilder
factory/run exception -> generic source-free system response
```

factory cache 表示 active snapshot 在进程生命周期内固定；E2 activate/rollback 后需要重启服务才能拾取，这一 operational lifecycle 将在 E5 明确，不在 C09 假装 hot reload。

验证证据：

```text
generation focused                                 9 passed
API + API security                                 5 passed
C09 + legacy API/RAG compatibility                19 passed
agent_v2 + security + selected legacy            115 passed
E2/E3/selected legacy combined                   250 passed
compileall app/tests/scripts                       ok
git diff --check                                   exit 0 (CRLF notices only)
```

C09 结束时 API 已有真实 v2 入口，但尚未建立 E3 dev behavior run artifact。随后 C10 量化 outcome、coverage、unsafe zero-tool、permission zero-source、budget 和 trace completeness，并运行全仓库门禁。

### E3-C10：dev behavior audit, failure-driven gate and E3 verification

新增：

```text
scripts/eval_agent_v2_dev.py
tests/agent_v2/test_eval_agent_v2_dev.py
app/agent/evidence_relevance.py
tests/agent_v2/test_evidence_relevance.py
docs/roadmap/e3_beginner_learning_and_interview.md
```

计划里的 `demo_dev.jsonl` 和 `metadata.json` 不是实际 E1 artifact。实现读取 `data/generated/demo/eval/dev.json` JSON array，并用 `EvalCase` 验证；`test.json` 只在阶段末重新计算 hash，不解析内容。

#### Evaluator contract

默认 `--mode deterministic`：在系统临时目录对 E1 demo corpus 构建 fixed chunks + 128D stable hash embedding 的 v2 index，运行 C08 extractive runner，不调用 Ollama。`--mode live` 必须显式选择，才使用 active v2 index 和配置模型。

指标都保存 `passed/total/rate`：

- outcome accuracy；
- comparison full gold-document coverage；
- permission zero-source；
- 1 个固定 unsafe zero-tool probe；
- budget compliance；
- trace completeness；
- claim citation presence；
- citation visible-reference correctness；
- forbidden-source zero rate。

details 不保存 question、chunk text、preview、ACL 或 forbidden ID list，只保存 case ID、task、expected/actual mode、visible source doc IDs、计数、布尔结果和 failure reasons。默认只 stdout JSON；显式 output 才以 staging 发布 `summary/details/run_manifest`，目标存在即拒绝覆盖。

#### 第一次真实 dev run

Artifact：`data/eval_outputs/agent_v2_dev_e3_deterministic/`。

```text
outcome accuracy                 20/24 = 0.8333
comparison full coverage          4/4 = 1.0
permission zero-source            2/2 = 1.0
unsafe zero-tool                  1/1 = 1.0
budget compliance               25/25 = 1.0
trace completeness              25/25 = 1.0
citation presence               26/26 = 1.0
citation visible correctness    26/26 = 1.0
forbidden-source zero           24/24 = 1.0
```

四个失败全是 `no_answer -> answered`。检索返回的是正确政策文档，但问题中的命题“2027 年所有额度自动翻倍”不存在；旧 ledger 仅凭同一 policy hit 就标记 `answer` supported。这证明“source/citation 合法”不等于“问题命题被证据支持”。

#### Query-anchor gate

新增 `has_query_anchor_support(query, hit)`：去掉 quoted entity 和通用问法词后，至少一个命题 anchor 必须与 evidence token 重合；显式四位年份必须出现在 evidence。controller 仍记录 retrieval visible count，但只有 gate 通过的 hit 才进入 aspect evidence 和 ledger。

这是 deterministic heuristic，不是 entailment。它可能对同义改写产生 false negative；显式年份规则也不理解“无到期 active policy 是否延续到未来”。因此只能作为保守 admission gate，E4 仍需人工抽检和更完整 answer eval。

第二个 artifact：`data/eval_outputs/agent_v2_dev_e3_anchor_gate/`。

```text
outcome accuracy                 24/24 = 1.0
comparison full coverage          4/4 = 1.0
permission zero-source            2/2 = 1.0
unsafe/budget/trace/forbidden       all 1.0
citation presence/visible        22/22 = 1.0
```

before/after diff 只有四个 no-answer case 从 answered 变为 not_found，其他 20 个 mode/failure 不变。citation 分母 26 -> 22 是因为四个 no-answer 不再生成 claims。由于修复由 dev failure 驱动，第二次 24/24 只能叫 dev regression result，不能叫 unseen/final accuracy；frozen test 完全未读。

#### Writer incident

第二次 run 首次发布时 staging rename 在 Windows 报 `WinError 5`。检查 target 不存在、项目 Python 进程 0、父目录 ACL 有 Modify 权限。根因只能标为最可信的 transient directory handle/Windows rename behavior，不能百分百断言。writer 改用 resolved absolute paths，并只对 PermissionError 最多重试五次；每次重试检查 target 是否被并发创建，其他异常立即失败并清 staging。模拟首个 rename 失败的测试先 RED 后 GREEN。

#### Final gate diagnostics incident

第一次并行跑最终门禁时出现三项表面异常。第一，`test_manifest.sha256` 使用标准 `<hash>  test.json` 格式，检查脚本却把整行与纯 hash 比较，形成假 mismatch；改为提取首个 token 后 expected/actual 相同。第二，进程检查和 full pytest 同时执行，因此把正在验证的 pytest 自己计为后台进程 1；测试退出后串行检查为 0。

第三，full pytest 新增 `PytestCacheWarning: WinError 5`。PowerShell 可读 `.pytest_cache/v/cache`，但虚拟环境 Python 的 `Path.stat()` 可稳定复现 PermissionError。ACL 显示项目根目录允许 Codex sandbox identities，而 2026-05 创建的旧 `.pytest_cache` 使用 protected DACL、关闭继承。只对该缓存目录执行 inheritance enable 后，Python `stat/mkdir` 成功，evaluator 6 tests 无 cache warning，full suite 再次为 380 passed/5 warnings。没有删除缓存，也没有修改业务代码。

#### E3 gate

```text
E3 focused domain/retrieval/security/agent_v2 155 passed, 5 warnings
legacy controller/runner/API/RAG               24 passed, 5 warnings
full repository                               380 passed, 5 warnings
pip check                                      clean
compileall app/scripts/tests                   ok
git diff --check                               exit 0, CRLF notices only
frozen test SHA256 expected == actual          556ffe...43338
project Python/pip processes                   0
git index lock                                 false
```

warnings 是 FAISS SWIG type deprecations 和 legacy FastAPI `on_event` deprecation。后者属于 E5 lifespan/runtime 阶段，本阶段不混入兼容性重构。

## 8. 当前明确不做

- 不实现 reranker、多 Agent、长期记忆、真实 IAM、Redis/队列。
- 不删除 legacy Agent 或改变其默认 endpoint。
- 不运行 E1 frozen test 做开发反馈。
- 未经本人确认不 commit 或 push。
