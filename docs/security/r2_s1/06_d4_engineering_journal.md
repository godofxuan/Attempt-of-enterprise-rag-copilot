# R2-S1 D4 数据流接入与能力约束工程日志

更新时间：2026-07-17

状态：D4 `IMPLEMENTED AND DETERMINISTICALLY TESTED`。D5 此后已完成，见 [D5 Engineering Journal](07_d5_engineering_journal.md)；D6 72-case OFF/ON evaluation 仍为 `NOT RUN`。

## 1. D4 到底解决什么问题

D3 已经能对一段字符串返回 `ADMIT` 或 `QUARANTINE`，但 D3 没有改变运行时路径。D4 开始前，真实路径仍然是：

```text
retrieval
-> raw SearchResult / FindResult / OpenResult
-> Controller.observe
-> EvidenceLedger
-> generation / citation / response
```

这意味着“有一个 Guard 类”不等于“系统受 Guard 保护”。调用者可以忘记调用 Guard，或者在 Guard 前已经把 `top_k` 之外的候选丢掉。D4 把路径改成：

```text
ACL + metadata filter
-> ranked candidate pool (<= candidate_k, one ranking run)
-> RetrievedContentAdmission
   -> body / parent / metadata / find preview / open content
   -> bounded adjacent split checks
   -> quarantine + one bounded top-up
-> GuardedV2ToolExecution
-> Controller.observe runtime type check
-> admitted-only ControllerState / EvidenceLedger
-> generation / citation / response
```

核心安全属性不是“正则更多”，而是 raw 内容不能再合法进入 Controller。

## 2. 代码修改总览

| 文件 | D4 修改 | 为什么需要 |
|---|---|---|
| `app/domain/retrieved_security.py` | 新增 admitted/quarantine/guarded payload、深度不可变内容快照和安全计数器；版本升到 `rcg-v1.1.0` | 用类型表达信任状态，拒绝非法组合和判定后的原地篡改 |
| `app/retrieval/pipeline.py` | 新增 `RankedSearchPool` 和 `ranked_candidates_for_guard()` | Guard 前保留 `candidate_k`，避免毒 top-1 删除后无候选可补 |
| `app/retrieval/navigation.py` | 新增 `search_ranked()` | 给安全工具路径一个受 ACL、timeout 约束的候选池入口 |
| `app/security/retrieved_admission.py` | 新增字段扫描、parent fallback、split、diversity、top-up 编排 | D3 只判单字符串，D4 负责对象级数据流决策 |
| `app/agent/tools_v2.py` | `run()` 只返回 `GuardedV2ToolExecution` | Guard 成为 mandatory enforcement point |
| `app/agent/controller_v2.py` | 状态只存 admitted 类型；运行时拒绝 raw execution | 类型注解之外再建立真实运行时边界 |
| `app/agent/evidence_ledger.py` | 只接受 `AdmittedEvidenceChunk` | 隔离内容不能建立支持、冲突或 coverage |
| `app/agent/evidence_relevance.py` | 只对 admitted chunk 做 query-anchor 检查 | raw hit 不能通过辅助函数旁路进入状态 |
| `app/agent/citation_verifier.py` | visible evidence 改为 admitted chunk | citation 只证明 admitted evidence 的支持关系 |
| `app/agent/generation_v2.py` | prompt source 从 admitted wrapper 投影 | 生成器不再接受 raw state |
| `app/agent/runner_v2.py` | guarded trace adapter、source-free security outcome、raw bypass fail closed | 自定义/错误 registry 不能静默回退到旧路径 |
| `app/domain/agent.py` | 新增 `security_filtered/evidence_filtered` | 区分“没找到”和“找到了但安全策略扣留” |
| `app/domain/evidence.py` | `security_filtered` 强制零 sources | 隔离终态不能带来源或正文 |

## 3. Domain Contract 详解

### 3.1 `AdmittedEvidenceChunk`

该类型接收一个 raw `SearchHit`，构造时立即复制为 `AdmittedSearchHitSnapshot`。字符串列表变成 tuple，locator 也变成 frozen snapshot，之后再修改原始 hit 或执行 `admitted.hit.matched_text = ...` 都不能改变已准入证据。它同时要求：

```text
matched_decision.disposition == ADMIT
metadata_decision.disposition == ADMIT
if context_from_parent:
    context_decision exists and is ADMIT
else:
    context_decision is None
    context_text == matched_text
```

因此以下状态无法构造：正文被判为 `QUARANTINE`，对象却声称是 admitted；或者 parent context 没有独立判定就进入下游。

### 3.2 `QuarantineSummary`

隔离摘要只有：

```text
internal_item_key   internal only, excluded from serialization
field_kind          matched/parent/find_preview/open/metadata/aggregate
decision            content-free QUARANTINE decision
```

它没有 `content`、`normalized_content` 或 decoded payload 字段。Pydantic 使用 `extra="forbid"`，所以调用者不能偷偷增加正文。

### 3.3 `SecurityCounters`

模型验证以下关系：

```text
scanned_count == admitted_count + quarantined_count
post_guard_evidence_count <= admitted_count
guard_error_count <= quarantined_count
top_up_attempts in {0, 1}
risk_categories exactly match allowlisted rule_ids
detector_version == rcg-v1.1.0
```

`candidate_count` 是排名池对象数；`scanned_count` 是实际扫描的字段/aggregate 数，所以后者可以更大。`post_guard_evidence_count` 是最终交给 Controller 的安全对象数。

### 3.4 为什么版本从 v1.0.0 升到 v1.1.0

D4 加入 `RCG-SPLIT-ADJACENT-001` 和固定的跨分片组合规则。即使 D3 的单字符串正则没有改变，完整 detector policy 已改变，因此 detector version 和 rule hash 必须改变：

```text
detector_version  rcg-v1.1.0
rule_set_sha256   dcafd504a01dcc757910751503eaaf1387903827e5e0f4932fbdd7937b68da01
```

## 4. Ranked Pool 和 Top-Up 详解

旧 `HybridRetrievalPipeline.search()` 的顺序是：

```text
rank candidate_k
-> diversity select top_k
-> create SearchResult
```

若 rank 1 是毒文档而 `top_k=1`，Guard 即使删除它，也看不到 rank 2。D4 抽出：

```python
pool = pipeline.ranked_candidates_for_guard(request)
```

`pool.candidates` 保留最多 `candidate_k` 个 ACL-visible、metadata-filtered、稳定排序的候选。hybrid 的 BM25/dense union 在 fusion 后再硬截断；Admission 还会对 custom Navigator 的 oversized pool 再截断一次。公开 `search()` 仍从同一 pool 做原来的 diversity/top-k，因此 R1 行为不变。

安全路径只遍历现有 pool：

```text
rank 1 quarantined -> no top-k/diversity slot consumed
rank 2 clean       -> admitted and selected
rank > top_k scanned -> top_up_attempts = 1
```

它不会重新 embedding、重新 BM25、扩大 ACL、增加 `candidate_k` 或循环直到成功。

## 5. 字段级 Admission 详解

### 5.1 Search

每个候选的可解释文本面分别处理：

```text
matched_text
document title + source_path + section_path + locator label
distinct parent context, if expanded
```

正文或 metadata 隔离会删除整个候选。parent 隔离不同：若 child 正文和 metadata 干净，系统将 `context_text` 回退为 `matched_text`，把 `context_from_parent` 改为 `False`，并保留 child。

这避免了两个错误极端：

1. 只扫 child，漏掉恶意 parent；
2. parent 有风险就把独立干净 child 一起删除，降低可用性。

### 5.2 Find 和 Open

- `find` 对每条 preview 和 section metadata 分别扫描，风险 match 不进入 Controller。
- `open` 对完整 content 与 source/section metadata 分别扫描；任一风险都返回 content-free `GuardedOpenQuarantinedResult`。

三个工具复用同一 admission policy，不存在“search 安全但 open 绕过”的第二条原始内容路径。

### 5.3 Guard exception

D3 自身已捕获内部异常。D4 仍对 injected/custom Guard 做第二层保护：若 `scan()` 抛异常或返回非 `GuardDecision`，该字段变成 `RCG-GUARD-ERROR` quarantine；异常文本、路径、canary 和 traceback 不进入结果。

若 Guard/admission 整体不可初始化或运行时不可用，工具返回 source-free `system` error，不回退 raw 内容。

## 6. Split Payload 详解

D4 只组合：

```text
same authorized document
same locator kind
adjacent locator range
2 or 3 fragments
NFKC/casefold normalized joined length <= 12,000 characters
raw joined length <= the Guard's 20,000-character scan bound
```

跨文档、非相邻、原文超过 Guard 扫描上限或 NFKC/casefold 后超过 12,000 字符的组合不会扫描为 split。先检查原文上限是为了限制归一化的资源消耗；再检查归一化长度是为了防止多个 Hangul Jamo 等字符在 NFKC 后收缩而绕过 split。true split 必须满足：各 fragment 单独是 `ADMIT`，组合后是 `QUARANTINE`；随后增加 `RCG-SPLIT-ADJACENT-001`，并在本次 execution 中删除全部贡献 fragment。即使其中一个 fragment 单独已经被隔离，风险 aggregate 的其他贡献 fragment 也不会单独进入本次回答。

这个限制很重要。无限组合所有历史 chunk 会产生组合爆炸、跨租户风险和大量误报。当前 claim 必须写成“覆盖有界、同文档、相邻 2-3 分片”，不能写成“防住所有分片攻击”。

## 7. Tool 和 Controller 硬边界

`V2ToolRegistry.run()` 的公开返回类型现在只有：

```text
GuardedV2ToolExecution
```

旧 `V2ToolExecution` 被保留为 raw negative-test 类型。Controller 的第一行安全检查是实际运行时检查：

```python
if not isinstance(execution, GuardedV2ToolExecution):
    raise TypeError("Controller.observe requires a guarded tool execution")
```

不能只依赖 Python type hint，因为运行时不会自动执行 type hint。Runner 捕获该 boundary error 后返回 `system/system_error`、零 sources，不调用 legacy fallback。

`ControllerState` 的字段也改成：

```text
evidence_by_aspect: dict[str, list[AdmittedEvidenceChunk]]
open_results: list[AdmittedOpenResult]
find_results: list[AdmittedFindMatch]
```

生产状态更新不再使用不重新验证的 `model_copy(update=...)`，而是重新构造 `ControllerState`。因此 raw `SearchHit` 即使由内部代码注入，也会触发 Pydantic validation error。

## 8. Outcome 语义

```text
no candidates                         -> not_found / not_found
denied-only candidates                -> permission / permission
candidates exist, all usable filtered -> security_filtered / evidence_filtered
some admitted                         -> existing answer/partial/budget logic
Guard/admission unavailable           -> system / system_error
```

`security_filtered` 不宣称系统确定发现了攻击。它只表示“候选存在，但配置的安全策略没有允许它们进入回答”。这比错误返回 `not_found` 更可解释，也不会泄露哪篇文档触发了规则。

## 9. Context Budget 和能力约束

旧工具在 Guard 前计算 raw chars。D4 改为 admission 完成后才计算：

```text
BudgetState.context_chars += admitted prompt-reachable chars only
SecurityCounters.scanned_chars += bounded detector scan chars
quarantined chars do not consume model context budget
```

Search 的预算同时计算 generation 实际会发出的 `matched_text`、`context_text`、`version` 和 source/section metadata。旧实现只算 parent context，distinct parent 场景会漏掉同时写入 prompt 的 child matched text；D4 审查后已用精确回归锁定这两个字段都计数。

工具 allowlist 仍是 `search/find/open`。`AgentAction` schema 拒绝 shell/HTTP/email 等名字；`open` 只把 `target_id` 交给当前 index 的字典解析。真实 `DocumentNavigator` 测试把 `requests` 和 socket transport 全部替换成失败函数，再传入 `https://attack.invalid/collect` 作为 target ID，结果为 `not_found` 且网络尝试列表为空。

## 10. TDD 过程和实际困难

### 10.1 RED/GREEN 切片

| 切片 | RED 证据 | GREEN 证据 |
|---|---|---|
| guarded domain | import `AdmittedEvidenceChunk` failed | contract + D3 Guard `74 passed` |
| ranked pool | 2 missing-method failures | retrieval regression `24 passed` |
| admission | module import failed | admission focused `10 passed` |
| tool boundary | 5 expected failures | tool focused `12 passed` at that checkpoint |
| Controller/Runner/D2 | 15 integration failures | target group `29 passed` |
| downstream unit migration | 31 raw-hit failures | affected group `35 passed`; Agent V2 `97 passed` |
| independent security review | `8 failed / 28 passed`，复现 2 Critical + 6 Important | corrected focused batch `38 passed` |
| full repository | not inferred from focused tests | `687 passed`, 3 known warnings |

### 10.2 遇到的具体问题

**问题 1：包级循环导入。**

第一次把 `RetrievedContentAdmission` 从 `app.security.__init__` 重导出后，形成：

```text
pipeline -> app.security.access -> app.security.__init__
         -> retrieved_admission -> pipeline (partially initialized)
```

解决：Guard core 保留稳定 package export；admission 使用具体模块导入，不在安全包顶层做 convenience re-export。依赖方向恢复单向。

**问题 2：测试伪造了先天非法 action。**

工具/结果 mismatch 测试最初用 `model_copy` 把 search action 改成 find，却没有 `find_request`。Pydantic 在 action 层先失败，测试没有到达目标 invariant。解决：构造合法 `FindRequest`，再给它错误的 guarded search payload。

**问题 3：严格边界使 31 个旧单元测试失败。**

这不是放宽生产函数的理由。新增测试专用 `admit_search_hit()`，先运行真实 Guard 再构造 admitted wrapper；ledger/citation/generation 测试因此遵守新合同。

**问题 4：历史 D2 测试自己绕过新入口。**

旧测试直接把 poisoned hit 塞入 `ControllerState`。D4 后这不再是合法运行路径。解决：propagation 测试改走 Registry -> Admission -> Controller；raw-boundary 测试则显式手工构造旧 `V2ToolExecution`，专门验证拒绝。

### 10.3 独立安全审查发现与修复

第一次 full suite 的 `677 passed` 不能单独证明边界正确。只读审查者从“哪些字符串最终进入 generation”“哪些上限在谁手里执行”“对象在验证后还能否变化”三个方向手工构造反例，得到 2 个 Critical 和 6 个 Important。每项先加入失败测试，初次批次为 `8 failed / 28 passed`，修复后的扩展批次为 `38 passed`。

| 审查发现 | 根因 | 修复位置和验证 |
|---|---|---|
| `version` 可携带指令进入 prompt | metadata scanner 没扫描 generation 会插值的 `hit.version` | `_search_metadata()` 加入 version；poisoned-version 用例必须得到 `security_filtered` |
| split 在 NFKC 前判断 12,000 | 原始字符数可能大于 12,000，但归一化后收缩到界内 | `normalized_content_length()` 与 raw 20,000 上限；Hangul Jamo 回归证明 aggregate 被隔离 |
| hybrid pool 最多可达 `2 * candidate_k` | BM25 和 dense 各取 N，fusion union 后未截断 | pipeline fusion 后 slice，Admission 对 custom pool 再 slice；两个独立测试锁定上限 |
| Guard 时间不在 deadline 内 | Registry 只在 retrieval 前看一次时钟 | 计算 request/global effective deadline，在 Navigator 后和 Admission 后复查；超时只返回 source-free timeout |
| frozen wrapper 内含 mutable `SearchHit` | Pydantic `frozen=True` 只冻结外层字段赋值 | 新增 Search/Find/Open/Locator frozen snapshots，列表转 tuple；正文和 section 原地修改都失败 |
| parent 与 child 文本相同会 system error | `context_from_parent=True`，但代码因文本相同没有建立 context decision | 相同文本标准化为 child-only；保留 provenance ID，不重复扫描相同正文 |
| 风险 aggregate 的 clean contributor 仍可进入 | mixed individual decisions 分支只 block 单独风险 fragment | 任一已判风险的 aggregate 都 block 本窗口全部贡献者 |
| parent expansion 少算 child prompt chars | generation 同时发 matched/context，预算只算 context | `_search_context_chars()` 同时计算 matched、context、version 和显示 metadata |

这次审查还带来一个工程结论：测试数量只能说明已编码的假设都通过，不能说明假设完整。安全 review 的任务是寻找“测试没问的问题”，再把反例固化成回归。

## 11. 验证证据

```text
detector_version                         rcg-v1.1.0
rule_set_sha256                          dcafd504a01dcc757910751503eaaf1387903827e5e0f4932fbdd7937b68da01
guarded tool/no-egress focused             6 passed
Agent V2                                  98 passed
D2/D4 propagation and top-up               8 passed
independent-review focused                 38 passed
R1 V2 API                                  12 passed
full offline repository suite             687 passed
warnings                                    3 FAISS SWIG deprecation warnings
compileall                                  exit 0
pip check                                   no broken requirements
public repository audit                    359 candidates / 0 findings
```

R1 frozen data remained byte-identical:

```text
dev.json                  92b4753df4e69bb570e9ea202420b46124207f15a07cdbb421fb00e6990082bd
test.json                 556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
test_manifest.sha256      fc9151daee0d6a0ac1ecfd1b6a3e361bc985d3f8512a8bc76927528ecd32f253
```

D4 没有运行 Ollama、embedding 模型、真实外网请求或 live security trial。

## 12. D4 能证明和不能证明什么

可以证明：

- 默认 V2 工具路径在 Controller 前执行确定性 Guard；
- raw execution 在 Controller 运行时被拒绝；
- body/parent/metadata/find/open 均有测试覆盖；
- top-ranked poison 可从同一 `candidate_k` pool 有界补回 clean candidate；
- 隔离内容不进入 generation context、response source 或 model context budget；
- read-only tool schema 不会把攻击 URL 解释为网络能力。

不能证明：

- 对未知或所有 indirect injection 免疫；
- D3 heuristic detector 没有 false positive/false negative；
- D5 nonce prompt boundary 和 public security counters 已完成；
- 72-case dev/test OFF/ON 指标已计算；
- Qwen 在真实 paired trial 中的攻击成功率；
- legacy endpoint、生产 IAM、外部 connectors 或任意未来新工具自动受保护。

## 13. 面试常见问题与回答

### Q1：为什么不是在 prompt 中写“忽略文档指令”就够了？

因为 raw 文本在生成前已经进入 Controller、EvidenceLedger、citation verifier 和 extractive response。prompt 指令只保护一个 sink，无法恢复被 top-k 丢掉的 clean candidate，也不能防止非 LLM 组件消费恶意文本。D4 在工具结果进入状态前建立类型边界，prompt boundary 是 D5 的第二层防御。

### Q2：为什么不用另一个 LLM 判断是否是注入？

这是 pre-model security gate，需要确定、低延迟、可复现和 fail-closed。再调用 LLM 会把不可信文本发送给另一个模型，引入网络/模型故障与非确定性。当前 Guard 是 heuristic，不宣称完美；D6 会用固定攻击/benign 集量化误报漏报，live model 只作独立证据。

### Q3：type hint 为什么不算安全边界？

Python 默认不在运行时执行 type hint。任意对象仍能传给函数。因此 `Controller.observe()` 先做 `isinstance(GuardedV2ToolExecution)`，Pydantic state 再验证 admitted 子类型，Runner 最后把边界异常变成 source-free system response。

### Q4：top-up 会不会无限检索？

不会。ranking 只运行一次，pool 最大是请求 schema 已限制的 `candidate_k <= 200`。top-up 只是继续遍历这个现有 pool，最多记录一次 `top_up_attempts=1`，不会重新 embedding、扩大 ACL 或递归搜索。

### Q5：为什么 parent 风险时还保留 child？

child 和 parent 是独立内容单元。若 child、metadata 均 ADMIT，只有扩展 parent 被隔离，系统可回退 child-only，从而减少不必要拒答。若 child 或 metadata 风险，则删除整个候选。

### Q6：`security_filtered` 和 `not_found` 有什么区别？

`not_found` 表示可见检索没有匹配候选；`security_filtered` 表示候选存在，但安全策略没有允许可用内容进入回答。两者都 source-free，但运维含义不同，且后者不暴露具体资源。

### Q7：citation verifier 能不能防注入？

不能。若恶意 canary 本身就在检索证据里，模型复制它并引用该 chunk，词法 citation 反而会认为有支持。citation 解决“回答是否被 admitted evidence 支持”，Guard 解决“哪些 evidence 有资格进入下游”。

### Q8：如何证明 URL 没被执行？

除了结构上没有 HTTP tool，测试还 monkeypatch `requests.Session.request`、`socket.connect` 和 `socket.create_connection` 为立即失败，向真实 `DocumentNavigator.open()` 传 URL 字符串。它只作为 index ID 查字典，返回 `not_found`，transport attempt 为 0。

## 14. 下一审批门

```text
批准D4，执行D5提示边界与安全可观测性
```
