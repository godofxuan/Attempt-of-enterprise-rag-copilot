# R2-S1 V2 Guard 实际扫描来源工程日志

日期：2026-07-19

状态：`V2 IMPLEMENTED AND LOCALLY VERIFIED`；V3-V5 未开始；未 commit、未 push、未 merge、未创建 tag。

## 1. 这一阶段到底解决了什么

V2 修复的不是 Guard 检测规则，而是**评测器如何判断某个攻击单元是否真的到达过 Guard**。

修改前，`_reached_attack_unit_ids()` 没有实际扫描事件，只能从三类结果反推：

1. `quarantine_summaries`：只能看到被隔离的字段；
2. admitted search/open result：只能看到最终返回给 Agent 的内容；
3. `case.category == "split_payload"`：直接假设 split case 的攻击片段都被扫描。

第三条是标签泄漏。`category` 是评测集的答案标签，不是运行时事实。即使片段因为跨文档、非相邻、超长或没有进入工具路径而从未被扫描，标签也可能把它算成 reached。反过来，一个普通类别的相邻窗口如果被 Guard 聚合扫描并放行，又没有 quarantine summary，旧逻辑会漏记。

V2 改成：

```text
真实 Guard.scan(content) 调用
  -> 立即生成 content-free ScannedContentUnit
  -> GuardedAdmissionOutcome.scan_provenance
  -> evaluator recording admission
  -> 按 operation + surface + exact member IDs 映射 fixture unit
  -> reached / unreached 指标
```

因此现在的定义是：**只有 provenance 证明发生过 Guard 调用的字段，才算 reached。**

### 1.1 思路从哪里来

本阶段的直接任务来源是外部审核方案中的 V2 条目：它点名了 `_reached_attack_unit_ids()` 依赖 `split_payload` category 推断的问题，并要求 content-free scan provenance。实现细节不是照搬某个 Agent 框架，而是沿本项目自己的 `GuardDecision -> GuardedAdmissionOutcome -> evaluator` 数据流推导出来。

使用“在事实发生处记录不可变事件、由下游指标消费事件”的原因也很朴素：运行时的 Guard 调用才是一手证据，case label、最终输出和 quarantine summary 都只是不同阶段的派生结果。本阶段没有为了包装方案而声称引用某个网上项目；可验证依据是本地 RED 测试和逐 case 对比。

## 2. 冻结边界

V2 入口 HEAD 仍为：

```text
1bf9b95917d7ae813ca6214c7ab83492b4c47aa3
```

本阶段没有修改：

- `RetrievedContentGuard` 的规则、关键词、阈值、字符预算和 detector version；
- `MAX_SPLIT_FRAGMENTS=3`、`MAX_SPLIT_CHARS=12_000`、`MAX_SCAN_CHARS=20_000`；
- candidate ordering、top-k、top-up 和 Agent budget；
- frozen dataset、fixture manifest、freeze manifest；
- 正式 D7 run 或 V1 八文件公共证据包。

V2 前后的冻结 SHA-256 应保持：

```text
dataset          062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c
fixture          eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d
freeze manifest  5c9ba8aaa8cc1a0f8f02ddf011900ed4be022ece95b343902d1ad2469838fdd4
formal manifest  5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e
```

## 3. 代码修改详解

### 3.1 `app/domain/retrieved_security.py`

新增 `GuardOperation`：

```python
GuardOperation = Literal["search", "find", "open"]
```

新增严格冻结模型 `ScannedContentUnit`：

| 字段 | 含义 | 为什么需要 |
|---|---|---|
| `operation` | search/find/open | 区分同一个 surface 属于哪个工具 |
| `surface` | matched/parent/find_preview/open/metadata/aggregate | 精确说明被扫描的是哪个字段 |
| `internal_item_key` | 单项 ID 或聚合 key | evaluator 内部定位；序列化时排除 |
| `member_internal_ids` | 本次扫描实际包含的成员 ID | 聚合窗口不能再靠冒号字符串或类别猜成员 |
| `aggregate` | 是否为聚合窗口 | 与 `surface == aggregate` 强一致 |
| `disposition` | ADMIT/QUARANTINE | 记录该次 Guard 决策 |
| `rule_ids` | 实际 Guard rule IDs | 记录触发原因，不保存原文 |

这个模型使用项目已有的 `_GuardedModel`，所以默认具备：

- `extra="forbid"`：不能偷偷加入 `content`、`path`、`prompt` 等字段；
- `frozen=True`：构造后不能修改；
- `strict=True`：不做模糊类型转换；
- `internal_item_key` 和 `member_internal_ids` 使用 `exclude=True, repr=False`，不会进入 JSON 或普通 repr。

模型 validator 还强制：

- search/find/open 只能使用各自允许的 surface；
- `aggregate` 必须与 aggregate surface 完全一致；
- 聚合事件至少两个唯一成员；
- 聚合 key 必须等于成员 ID 的确定性拼接；
- 非聚合事件只能有一个成员，且必须等于 item key；
- rule IDs 必须来自 Guard allowlist、去重且排序；
- disposition 必须与 rule severity 一致。

注意：没有给 ID 新增任意长度上限。早期自审时曾加入 500 字符限制，但原 `SearchHit`/`OpenResult` 合同没有该限制；保留它会让“增加观测”意外变成“改变可接受输入”，所以在最终实现中删除。

### 3.2 `app/security/retrieved_admission.py`

`GuardedAdmissionOutcome` 新增：

```python
scan_provenance: tuple[ScannedContentUnit, ...]
```

并增加三个强不变量：

1. provenance 条数必须等于 `security_counters.scanned_count`；
2. ADMIT/QUARANTINE 事件数必须分别等于 counters；
3. 每条事件的 operation 必须与 outcome 的 search/find/open 类型一致。

新增 `_scan_recorded()`，它是唯一的记录入口：

```python
decision = self._scan(content)
provenance.append(
    ScannedContentUnit(
        operation=operation,
        surface=surface,
        internal_item_key=internal_item_key,
        member_internal_ids=member_internal_ids,
        aggregate=aggregate,
        disposition=decision.disposition,
        rule_ids=decision.rule_ids,
    )
)
return decision
```

重要点是：`content` 只传给 Guard，不传给 provenance model。事件里没有一个字段可以存原文。

所有实际扫描点都改为走这个包装器：

- search matched text -> `surface="matched"`；
- distinct parent context -> `surface="parent"`；
- search title/path/section/version 拼接 -> `surface="metadata"`；
- find preview -> `surface="find_preview"`；
- find section path -> `surface="metadata"`；
- open content -> `surface="open"`；
- open path/section -> `surface="metadata"`；
- eligible adjacent split window -> `surface="aggregate"`，成员为窗口的 exact chunk IDs。

聚合 eligibility 没有变化，仍先按 document 分组，再依次检查：

```text
same document
  -> locator adjacent and same kind
  -> raw aggregate <= MAX_SCAN_CHARS
  -> NFKC normalized aggregate <= MAX_SPLIT_CHARS
  -> actual Guard scan and provenance event
```

所以非相邻、跨文档或超长窗口不会产生 aggregate event。不是 evaluator 事后排除，而是 admission 从未调用 Guard，因而自然没有事件。

### 3.3 `app/evaluation/indirect_injection_runner.py`

`_RecordingAdmission` 原来只 override `admit_search()` 和 `admit_open()`。V2 审查发现 find outcome 虽然已有 provenance，却不会进入 `outcomes`，因此新增 `admit_find()` recording。

同时修复一个相关的既有 find 映射问题：

- `find_preview` quarantine 现在映射到 `matched_unit_id`；
- find metadata 只扫描 section path，所以只映射 `section_unit_id`；
- 不再把 find metadata 误映射到 search 才会扫描的 title/path/version。

### 3.4 `app/evaluation/indirect_injection_live_runner.py`

旧 `_reached_attack_unit_ids()` 中以下逻辑全部删除：

- 从 `quarantine_summaries` 猜 reached；
- 从 admitted result 猜 reached；
- `case.category == "split_payload"` 特判。

新逻辑只遍历：

```python
for recorded_operation, outcome in outcomes:
    for event in outcome.scan_provenance:
        ...
```

surface 到 fixture unit 的映射是：

| operation/surface | 被算作 reached 的 unit |
|---|---|
| search matched | `matched_unit_id` |
| search aggregate | 每个 member chunk 的 `matched_unit_id` |
| search parent | `context_unit_id` |
| search metadata | title/source_path/section/version unit IDs |
| find preview | `matched_unit_id` |
| find metadata | `section_unit_id` |
| open content | `content_unit_id` |
| open metadata | 当前 fixture 没有 metadata unit label，因此不伪造 reached |

最后仍与 `case.attack_unit_ids` 取交集，避免 benign unit 进入 attack reach 分子。

## 4. TDD：四轮 RED 到 GREEN

### 4.1 进入基线

修改前先运行 admission + live runner：

```text
26 passed, 3 known SWIG warnings
```

V1 standalone verifier 同时为 `VERIFIED`。

### 4.2 RED 1：领域模型不存在

先写 `ScannedContentUnit` 的严格性、不可变性、序列化和错误组合测试。第一次运行：

```text
ImportError: cannot import name 'ScannedContentUnit'
```

这是预期 RED，证明旧代码没有扫描来源合同。加入最小 domain model 后：

```text
19 passed
```

### 4.3 RED 2：admission 无事件，evaluator 仍用类别猜测

接着先写相邻/超长/非相邻/跨文档、parent/metadata/find/open、计数一致性和 evaluator mapping 测试。第一次结果：

```text
10 failed, 21 passed
```

主要失败分为三类：

- `GuardedAdmissionOutcome has no attribute scan_provenance`；
- 空 outcomes 的 split case 仍被 category 直接算成 reached；
- 提供 provenance 后 evaluator 完全不读取，结果仍为空。

接入 domain/admission/evaluator 后，核心聚焦集变为：

```text
51 passed
```

### 4.4 RED 3：find provenance 在 recording 层丢失

新增 find recording 测试后：

```text
assert [] == [("find", outcome)]
```

原因是 `_RecordingAdmission` 没有 override `admit_find()`。补上后转绿。

### 4.5 RED 4：find quarantine unit 映射错误

新增 preview + section 精确映射测试后，旧代码表现为：

```text
preview-unit 仍是 admitted
title/path/version 被错误标为 quarantined
```

原因是 `_unit_outcomes()` 不认识 `find_preview`，并把所有 metadata 都当成 search metadata。按 operation 分支修复后，聚焦结果：

```text
54 passed
```

## 5. 为什么正式 D7 是 15/28，而当前 mock run 是 17/28

这是本阶段最重要的诊断，不应把两个数字强行混成一个。

正式 D7 使用真实 BGE-M3 排序和 Qwen2.5:3b，历史公共包固定：

```text
reached 15/28
unreached 13/28
conditional quarantine 15/15
```

V2 的单元测试使用确定性 SHA-256 假 embedding 和结构化 fake chat。它不是正式 BGE 排序的复制品。新增 exact provenance 后，该 mock workload 的事实基线是：

```text
reached 17/28
unreached 11/28
OFF/ON per-case reach counts identical
```

逐例对比定位到两个差异 case：

```text
r2s1-test-secret-extraction-2
r2s1-test-markup-wrapped-2
```

正式 D7 中这两题的 clean candidate 在前、attack candidate 在后，`top_k=1` 已由 clean 满足，所以 attack 没有到达 Guard。mock embedding 的候选顺序不同，attack 实际进入了扫描，因此 provenance 正确地多计两条。

结论：

- V1 公共包继续不可变地复现历史正式 run 的 15/28；
- V2 不回写、不重解释旧 artifact；
- 当前 mock run 锁定自己的真实 17/28，不冒充 BGE-M3 正式结果；
- 将来若要发布 V2 新正式指标，必须新建 run ID，而不能覆盖 D7。

这不是测试妥协，而是避免把不同 retrieval ordering 的两个 workload 当成同一次实验。

## 6. 安全与隐私设计

provenance deliberately 不保存：

- retrieved text、question、prompt 或 model output；
- document/system/trace canary；
- source path 或本机绝对路径；
- nonce、credential、endpoint 或环境变量。

内部 item/member IDs 只供同一进程中的 evaluator 精确映射，并从 Pydantic dump/JSON/repr 排除。公开可序列化部分只有 operation、surface、aggregate、disposition 和 allowlisted rule IDs。

测试还明确尝试给 model 注入 `content=...`，严格 schema 会拒绝；find/open 的 provenance JSON 也检查不含 canary 和 source path。

## 7. 验证结果

实现后验证：

```text
focused domain/admission/live/find tests       54 passed
expanded domain/security/agent/evaluator      317 passed
full repository suite                         848 passed
warnings                                        3 known SWIG warnings
```

最终第一次重跑全仓时出现：

```text
1 failed, 847 passed
test_root_status_is_the_only_current_status_entrypoint
```

原因是 `PROJECT_STATUS.md` 已从 2026-07-18 更新到 2026-07-19，但“根状态文件是唯一当前入口”的仓库合同仍硬编码旧日期。同步测试日期后重新执行目标测试和全仓测试。该失败属于文档合同漂移，不是 Guard/provenance 行为失败，但仍在最终完成前修复。

其余最终门禁结果：

```text
V1 standalone verifier                      VERIFIED
public repository audit          409 candidates / 0 findings
compileall                                      exit 0
pip check                       no broken requirements
git diff --check                               exit 0
dataset / fixture / freeze / formal hashes      exact
```

## 8. 面试常见问题与答案

### Q1：scan provenance 是什么？

它是 Guard 每次真实扫描的 content-free 审计事件。它回答“哪个工具的哪个字段、哪些内部成员、是否聚合、得到什么安全决策”，但不保存被扫描原文。它与业务 trace 类似，但面向安全测量，并通过严格 schema 限制内容。

### Q2：为什么不能用 quarantine summary 判断 reached？

summary 只在 QUARANTINE 时产生。一个内容可能确实被扫描但被 ADMIT，尤其是 benign aggregate；如果只看 summary，会把这类真实扫描当成 unreached，分母错误，条件召回率也会失真。

### Q3：为什么不能看最终 admitted result？

final result 是经过 top-k、top-up、parent downgrade 和 quarantine 后的输出，不等于扫描轨迹。split aggregate 会在 top-k 前扫描多个候选，但不会作为独立 result 返回；反过来，一个 result 也可能由多个字段扫描共同决定。

### Q4：为什么 `case.category` 特判是严重问题？

category 是评测标签，相当于答案。用它推断运行时行为会产生 label leakage：指标看起来提高，但不是系统实际观测。真实系统处理线上文档时也没有 `split_payload` 真值标签，因此该逻辑不可部署、不可泛化。

### Q5：为什么 aggregate 要保存 exact member IDs？

一个 aggregate event 对应 2-3 个相邻片段。只保存 `a:b` 字符串再 split 容易出现 substring、分隔符和顺序歧义；exact tuple 能直接证明成员关系，并支持 admitted aggregate，不依赖 quarantine summary。

### Q6：内部 ID 为什么不公开？

内部 ID 可能泄漏文档结构或租户命名。evaluator 需要它们在内存里映射 fixture unit，但 public trace 不需要，所以使用 `exclude=True, repr=False`。公开部分仍能审计操作数量、surface、决策和规则分布。

### Q7：这次是否提高了 Guard 拦截能力？

没有。规则、阈值和预算完全不变。V2 提高的是**测量可信度与可审计性**。如果 reached 分母以前错了，即使 Guard 本身没变，指标也可能变化；这属于修正测量，不应宣传为检测率提升。

### Q8：如何证明 OFF 和 ON 可比？

相同 case 的 candidate set、query embedding、预算和参数保持一致，只替换 Guard delegate。V2 测试进一步比较每题 `attack_unit_reached_guard_count`，当前 deterministic workload 的 OFF/ON 字典完全相等；如果未来不相等，就必须解释 Guard 导致的控制流差异，而不能只比较总数。

### Q9：为什么 15/28 和 17/28 都保留？

它们属于不同 workload：15/28 是冻结真实 BGE-M3 D7 run，17/28 是哈希假 embedding 的测试运行。工程上应绑定 run ID、模型 identity、candidate ordering 和 input fingerprint，不能把不同实验的分子分母互换。

### Q10：这个方案还有什么限制？

它是应用进程内的 provenance，不是操作系统审计日志；内部 ID 依赖 admission 正确传入；旧 D7 artifact 没有 member-level events，不能事后补造；当前评测仍是可见 synthetic set。V3 才处理 LocalOllama socket origin 的实现收紧，V4 才处理指标命名语义。

## 9. 下一阶段

按批准计划，V2 完成后应停下等待 V3 授权。V3 是 `LocalOllamaOnlyBoundary` 的精确 origin/socket policy，不属于本阶段，也不能因为 V2 测试通过就宣称已经完成。
