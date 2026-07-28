# Citation Fail-Closed Fix Engineering Journal

最后更新：2026-07-28

## 1. 问题背景

Generation V2 已具备 ACL、Retrieved-content Guard、Evidence Ledger、
结构化 claim 和 citation verifier，但“验证失败”和“用户不可见”之间缺少
强制数据流约束。模型输出同时包含自然语言 `answer` 和候选 `claims`。旧实现
虽然能把不支持的关键 claim 标记为 partial，却仍把模型原文放入响应。

本次目标不是增加模型能力，而是收紧信任边界：

```text
LLM candidate claims
-> deterministic citation verification
-> host-side supported-claim selection
-> host-side answer/citation/source reconstruction
```

## 2. 原代码实际行为

`GenerationV2ResponseBuilder.build()` 的旧执行顺序是：

1. 从 Evidence Ledger 选择 Guard 已准入的可见证据；
2. 映射为 `S1...Sn` 并调用模型；
3. 把模型 claim 映射为内部 `Claim`；
4. 调用 `verify_claims()`；
5. 如果 critical claim 不支持，只把 mode 改为 `partial` 并加 warning；
6. 仍返回 `generated.answer`、全部 claims、全部 citations 和模型引用过的
   全部 sources。

旧 verifier 的 supported 条件只有：citation 存在、所有 chunk ID 可见、
claim 与证据至少共享一个 content token。`lexical_support > 0` 即通过。

## 3. 风险

该行为是 fail-open。典型风险包括：

- “5 天”与证据“3 天”共享大部分词，会被判 supported；
- “8000 元”与证据“5000 元”会被表面词重合掩盖；
- “允许”与“禁止”可能同时拥有足够词汇重合；
- verifier 已判 unsupported 的模型文本仍出现在 `answer`；
- non-critical 标记可能让错误内容只触发 warning；
- `sources` 反映模型尝试引用的来源，而不是最终安全内容使用的来源。

这不是 ACL 绕过，但会破坏回答层的证据一致性，并使 UI 的 partial/warning
与实际可见内容互相矛盾。

## 4. 最小复现

最小复现使用一个可见 chunk：

```text
Evidence: Employees may work remotely 3 days per month.
Claim:    Employees may work remotely 5 days per month.
```

旧 verifier 的词汇覆盖为高值，只有数字不同，因此仍返回
`supported=True`。Generation builder 随后直接返回包含 `5 days` 的模型
`answer`。

同类复现还包括：

```text
8000 yuan vs 5000 yuan
12% vs 10%
may use suppliers vs may not use suppliers
effective on 2026-01-01 vs repealed on 2026-01-01
```

## 5. RED Test

起始目标基线：

```text
34 passed, 3 warnings
```

新增测试后、修改生产代码前：

```text
12 failed, 18 passed, 3 warnings
```

12 个失败覆盖：

- 旧 reason message 不是稳定 reason code；
- 一个共享词仍被接受；
- 天数、金额、日期/状态、否定冲突仍被接受；
- partial 响应仍保留 unsupported claim；
- all-unsupported 仍返回模型原文；
- raw model answer 中没有对应 claim 的额外句子仍被显示。

随后补充百分比 `12% vs 10%` 回归。不可见或越权 chunk 使用同一个
`invisible_citation` 外部结果，避免泄露某个 chunk 是不存在还是无权访问。

## 6. 根因

根因分为两层：

1. `citation_verifier.py` 只有“任意词重合”规则，没有合理最低覆盖，也没有
   数字、日期状态和否定方向的一致性检查。
2. `generation_v2.py` 把 verifier 当成状态提示器，而不是输出准入门。
   `generated.answer` 和完整 candidate 列表绕过了 verifier 的结论。

模型输出 schema 本身不是可信边界。Pydantic 只能证明 JSON 形状合法，
不能证明内容有证据。

## 7. 修改方案

Verifier 按固定优先级返回：

```text
missing citation
-> invisible citation
-> no lexical support
-> insufficient lexical support
-> date/status mismatch
-> other Arabic numeric mismatch
-> common negation mismatch
-> supported
```

词汇门要求至少两个共享 content tokens 且 claim token coverage 不低于
`0.4`。claim 中的阿拉伯数字必须出现在被引证据组合中。完整日期和年份必须
一致；同一日期/年份上的 active/effective 与 repealed/expired 明显冲突返回
`date_mismatch`。常见中英文肯定/否定方向冲突返回
`negation_mismatch`。

Generation builder 先建立 `citation_by_claim`，再筛选 supported claims。
最终 answer 由 supported claim text 按原顺序连接；citations 只保留对应
supported entries；sources 只保留这些 claim 实际引用的可见 chunks。
`critical` 不参与是否展示的决定。

如果 supported claims 为空，复用 `ExtractiveResponseBuilder`，强制
`partial / partial_evidence`，并加入“模型 claims 缺少足够可见证据，已返回
抽取式 partial”的 warning。该 fallback 只读取 Controller state 中已经通过
ACL 和 Guard 的证据。

## 8. 为什么不用 NLI 大模型

本次是面试前最小可信收尾，不引入 NLI 服务或第二次 LLM judge，原因是：

- 新模型调用会增加延迟、失败模式和运行依赖；
- judge 自身也可能误判，不能自动成为安全 authority；
- 需要新的模型版本、prompt、阈值、校准集和人工对照证据；
- 当前最严重缺陷是数据流 fail-open，先用宿主程序强制过滤即可修复；
- 数字、日期、否定和可见引用适合做低成本、可复现的确定性第一道门。

代价是它会误拒绝部分正确同义改写。因此本实现只称 deterministic grounding
gate，不称 semantic entailment verifier。

## 9. 修改文件和函数

生产代码：

- `app/agent/citation_verifier.py`
  - `verify_claims()`：加入稳定 reason code 和固定检查顺序；
  - `_shared_content_token_count()`：阻止一个共享词直接通过；
  - `_date_mismatch()`：检查日期、年份和生命周期状态；
  - `_numeric_mismatch()`：检查 claim 中全部阿拉伯数字；
  - `_negation_mismatch()`：检查常见中英文肯定/否定方向。
- `app/agent/generation_v2.py`
  - `GenerationV2ResponseBuilder.build()`：过滤 candidate claims，重建四个
    用户字段，并实现 all-unsupported extractive fallback。

测试：

- `tests/agent_v2/test_citation_verifier.py`
- `tests/agent_v2/test_generation_v2.py`
- `tests/evaluation/test_indirect_injection_runner.py`

未修改：

- Controller、runner、领域 schema、身份、ACL、Guard、检索、索引和部署。

## 10. 测试结果

已完成的聚焦结果：

```text
tests/agent_v2/test_citation_verifier.py  13 passed
tests/agent_v2/test_generation_v2.py      18 passed
tests/agent_v2                            109 passed
```

第一次运行 `tests/agent_v2 tests/evaluation` 得到：

```text
1 failed, 1112 passed, 16 skipped, 3 warnings
```

唯一失败是历史 indirect-injection fake-generator 测试仍要求“攻击文本到达
模型后，document canary 必须出现在回答”。诊断发现 4 个 case 的 fake claim
固定引用 `S1`，但 `S1` 不支持 canary；新 verifier 正确把它们过滤为 partial。
临时只放宽 verifier 后，旧断言恢复，确认这是本次修改导致的预期合同变化，
不是随机、环境或 Controller 故障。相关测试现改为同时保留 Guard-OFF 的历史
泄漏信号，并验证不支持的 fake attack claim 会被 citation gate 过滤。单测
修复后为 `1 passed`。

最终验证：

```text
target citation + generation       31 passed, 3 warnings
agent_v2 + evaluation              1113 passed, 16 skipped, 3 warnings
frozen deterministic test suite    28/28, 4/4 security probes
pip check                          no broken requirements
compileall                         passed
public repository audit            918 candidates / 0 findings
full pytest first run              1 failed, 2427 passed, 30 skipped
status contract focused rerun      1 passed
full pytest final rerun             2428 passed, 30 skipped, 3 warnings
```

第一次全量的唯一失败是
`test_root_status_is_the_only_current_status_entrypoint` 仍把当前状态日期固定为
`2026-07-27`。本次把唯一 current status 更新到 `2026-07-28` 后，该合同按
设计报警。同步日期断言后，聚焦单测和第二次全量均通过。该失败分类为“本次
文档修改导致的测试合同同步”，不是生产逻辑、环境依赖或不可复现问题。

3 条 warning 均来自 FAISS SWIG 类型缺少 `__module__` 的已知
`DeprecationWarning`。没有为本次任务配置独立 formatter、linter 或 type
checker；仓库 CI 的实际本地对应检查是 `compileall`、`pip check`、pytest
和 public repository audit，均已执行。

deterministic run ID：

```text
citation-fail-closed-20260728-test
```

其 artifact 位于 ignored 的 `.private/eval_runs/`，没有加入 Git。运行时
temp 和 pytest basetemp 也显式放在项目 `.private/` 下，避免继续占用系统盘。

## 11. 未解决边界

- 词汇阈值会拒绝部分正确同义表达；
- 规则不理解复杂条件、例外、跨句指代和多跳推理；
- 否定模式只覆盖常见显式表达；
- 数字出现一致不代表单位、主体和业务语义一定一致；
- 多来源拼接可能让分别出现的 token/数字满足集合检查；
- 没有经过真人双评校准误拒绝率和漏检率；
- 没有新增 live-model 或独立 holdout 质量结论；
- 没有证明 staging、production 或任意 hallucination 都被阻止。

R2-S8 真人双评仍为 `NOT RUN`。R2-S9 只完成单主机 Linux deployment
contract，真实 staging 和 production 仍为 `NOT RUN`。

## 12. 面试时如何准确描述

推荐表述：

> 我发现原生成链虽然能标记 unsupported citation，却仍直接返回模型原始
> answer，属于 fail-open。我先用数字、金额、百分比、否定、日期状态、部分
> 支持和全部不支持案例写 RED tests，再把 LLM 降为 candidate-claim producer。
> 宿主程序用可见引用、最低词汇覆盖和确定性一致性规则筛选 claim，只从通过
> 的 claim 重建 answer、citations 和 sources；全部失败时从 Guard 已准入证据
> 返回 extractive partial。这个方案可复现、无额外模型延迟，但只是
> deterministic grounding gate，不是语义蕴含证明。

Controller 的准确表述是：默认策略按 required aspect 执行 `search`，
completeness 可以 `open`；`find` 有实现和安全边界但默认不主动选择；没有
自动 query rewrite/retry。

## 13. 不能使用的夸大表述

不得声称：

- “实现了完整 semantic verification / semantic entailment”；
- “彻底消除了 hallucination”；
- “所有回答都 fully grounded”；
- “三个工具都由 Agent 自主规划”；
- “Agent 会自动改写查询并重试”；
- “2419 个测试证明没有安全漏洞”；
- “合成评测代表生产准确率”；
- “R2-S8 已有人类质量认证”；
- “项目已经 production-ready”；
- “单主机 deployment contract 等于真实 staging/production 验收”。
