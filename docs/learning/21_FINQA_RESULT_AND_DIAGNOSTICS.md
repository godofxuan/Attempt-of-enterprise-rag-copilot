# 第 21 章：FinQA Calculator Agent、结果解释与失败诊断

本章回答四个问题：

1. 这轮 FinQA 结果到底好不好；
2. Oracle、Hybrid、dev 和 test 为什么不能混在一起比较；
3. Calculator Agent 和失败诊断代码具体做了什么；
4. 下一阶段为什么是 plan-review 成对实验，而不是继续增加 Top-K。

## 21.1 先看结论，但不要误读

| 实验 | Strict | 宽容正确率 | Evidence recall | Grounded strict |
| --- | ---: | ---: | ---: | ---: |
| 旧 20 题 dev Oracle | 75% | 未作为最终结论 | 100% | 未作为最终结论 |
| 新 100 题 dev Oracle | 63% | 64% | 100% | 56% |
| 新 100 题 dev Hybrid K=10 | 59% | 61% | 91.98% | 52% |
| 冻结 100 题 test Oracle | 52% | 54% | 100% | 45% |
| 冻结 100 题 test Hybrid K=10 | 44% | 44% | 93.5% | 40% |

最容易犯的错误是说：

> “我们把 test Hybrid 从 44% 提升到了 dev Hybrid 的 59%，提升 15 个百分点。”

这是错误表述。两者来自不同 split、不同稳定样本，而且本轮 dev 诊断没有修改
模型 prompt。新 dev 分数只能说明这 100 道开发题上的表现，不能覆盖已经观察过的
test 结果。

正确结论是：

- 20 题 dev 的 75% 明显偏乐观；扩大到 100 题后 Oracle 下降到 63%；
- 同一 100 题上 Oracle 63%、Hybrid 59%，检索造成 4 个百分点净损失；
- Oracle 已经拿到完整 gold evidence，仍有 37 道严格错误，所以主要剩余瓶颈是
  选数、运算关系、参数顺序和尺度，而不只是检索；
- 冻结 test 的 52%/44% 仍是当前最可信的留出观察，不能继续用它调参。

## 21.2 每个指标到底测什么

### Strict execution accuracy

模型表达式经 Calculator 执行后，结果归一化并保留到 5 位，与 FinQA 官方
`exe_ans` 比较。它严格、稳定、可复算，但会受到数据集执行标签质量影响。

### Presentation tolerance accuracy

符号必须一致，同时允许绝对或相对误差不超过 0.5%。它用于区分合理四舍五入和
真正计算错误，不能替代 strict。

### Evidence recall

交给模型的检索结果覆盖了多少 `gold_inds`。它回答“检索有没有把需要的证据找全”，
不回答“模型有没有正确使用证据”。

### Citation precision 与 citation recall

- precision：模型引用的证据里有多少是 gold；
- recall：全部 gold 证据里有多少被模型引用。

### Grounded strict

只有 strict 正确并且 citation recall 为 100% 才算成功。数字算对但引用不完整，
不能称为可审计的 grounded answer。

## 21.3 为什么要把 LLM 和 Calculator 分开

早期 direct-answer 方案让模型同时负责理解、选数、运算和最终格式，20 题 dev
Oracle strict 为 0%。复杂 typed-step JSON 虽然看起来更 Agentic，但 Qwen3 8B
经常把 evidence ID 当成 operand，strict 只有 15%，协议错误达到 50%。

最终流程是：

```text
question
  -> Oracle 或 BM25Plus/BGE-M3 RRF
  -> Retrieved-content Guard
  -> Qwen3 选择数字并输出一个算术表达式
  -> AST 白名单和 Decimal Calculator
  -> strict / retrieval / citation / grounding 分层评分
  -> immutable manifest / details / summary
```

职责分离如下：

- LLM：理解自然语言、选择年份和类别、决定运算关系；
- Calculator：验证表达式语法、限制资源、精确执行；
- Evaluator：分别归因检索、答案、引用和协议；
- Manifest：绑定数据 hash、样本 hash、模型 digest、代码 SHA 和私有 artifact hash。

`app/agent/safe_calculator.py` 不调用 `eval`。它只接受数字、括号和
`+ - * /`，使用 Python AST 白名单和 `Decimal`，并限制字符数、AST 节点、深度、
数值范围和指数。变量、函数、属性、下标、幂、除零和非有限数都会被拒绝。

## 21.4 为什么不能只看总正确率

总分只能告诉我们“错了多少”，不能告诉我们“下一行代码改哪里”。因此新增
`app/external_datasets/finqa_diagnostics.py`：

1. 解析官方 gold program，例如：

   ```text
   subtract(120, 100), divide(#0, const_100)
   ```

2. 将 gold program 转成执行顺序：

   ```text
   [subtract, divide]
   ```

3. 将模型表达式 `(120 - 100) / 100` 解析为 AST，并按后序遍历得到同样的执行顺序；
4. 提取 gold 和预测表达式里的 Decimal operand multiset；
5. 检查预测数字是否出现在模型实际引用的证据中，标准换算常量单独白名单；
6. 按固定优先级分类，不调用另一个 LLM 当裁判。

解析器成功覆盖 pinned FinQA dev 的 `883/883` 条 gold program。它有长度、步骤数、
operation 名称、参数个数和数值格式限制，遇到未知语法会失败，而不是默默猜测。

## 21.5 错误分类是事实还是推测

优先级是：

```text
generation_protocol_error
  -> correct_grounded / correct_citation_incomplete
  -> retrieval_miss
  -> unsupported_gold_operation
  -> operand_selection_signal
  -> operation_plan_signal
  -> composition_or_scale_signal
```

各类型含义：

| 类型 | 判断依据 | 可信边界 |
| --- | --- | --- |
| `generation_protocol_error` | 输出在重试预算内仍无法解析或执行 | 直接事实 |
| `correct_grounded` | strict 正确且 gold citation recall=1 | 直接事实 |
| `correct_citation_incomplete` | strict 正确但引用不全 | 直接事实 |
| `retrieval_miss` | 错题且至少一个 gold unit 未进入上下文 | 直接观察，但不保证缺失证据一定是唯一根因 |
| `unsupported_gold_operation` | gold 使用比较、表格聚合等当前工具不支持的操作 | 直接事实 |
| `operand_selection_signal` | 预测表达式未覆盖全部 gold 数字 | 机械信号，等价改写可能误报 |
| `operation_plan_signal` | operand 覆盖，但运算顺序与 gold 不同 | 机械信号，等价代数可能误报 |
| `composition_or_scale_signal` | 前述检查通过但结果仍错误 | 可能是参数顺序、括号、正负号或百分比尺度 |

所以这里不用 LLM judge，不代表诊断就是绝对语义真相。retrieval 和 protocol
更接近事实；operand 和 operation 必须叫 signal，不能在简历或面试中说成
“准确识别了每道错题根因”。

## 21.6 新 100 题 dev 到底错在哪里

Oracle 100 题：

- 56 题 strict 正确且引用完整；
- 7 题答案正确但引用不完整；
- 20 题出现 operand-selection signal；
- 11 题出现 operation-plan signal；
- 5 题是 composition/scale signal；
- 1 题需要当前 Calculator 不支持的 operation；
- 0 个协议错误。

Hybrid 100 题：

- 52 题 strict 正确且引用完整；
- 7 题答案正确但引用不完整；
- 12 题 retrieval miss；
- 21 题 operand-selection signal；
- 1 题 operation-plan signal；
- 6 题 composition/scale signal；
- 1 题 unsupported operation；
- 0 个协议错误。

同题成对比较为：

- Oracle、Hybrid 都正确：53；
- 两者都错误：31；
- 只有 Oracle 正确：10；
- 只有 Hybrid 正确：6。

这说明检索不是单调开关。更多上下文有时会提供必要证据，有时也会引入干扰。
因此不能把 Oracle-Hybrid 差值机械解释成“所有检索错误数”。

## 21.7 FinQA 标签本身也要审计

FinQA 同时提供人类展示 `answer` 和程序执行结果 `exe_ans`。全 dev 中：

- `858/883` 个展示答案能按单值协议解析；
- 25 个是空值、长文本或其他不可解析内容；
- 可解析的 858 个里有 97 个与 `exe_ans` 超出 0.5% 宽容一致性；
- 本次 100 题中 94 个可解析，只有 3 个存在这种不一致。

项目的处理原则：

1. 主评分继续绑定官方 `exe_ans`，保持协议稳定；
2. `answer` 只作为数据质量信号；
3. 不允许在模型跑完后选择对模型更有利的标签；
4. 文档公开不一致数量，但不发布逐题内容。

这是工业评测的重要原则：数据标签也可能出错，但不能因为发现标签问题就随意
更换主指标。

## 21.8 不可变运行怎样保证结果可审计

`scripts/eval_finqa.py` 生成：

```text
manifest.json
details.jsonl
summary.json
```

manifest 记录：

- FinQA revision 和 split SHA-256；
- 稳定 seed 和 selected case IDs SHA-256；
- Qwen3/BGE-M3 模型 digest；
- retrieval mode、K、timeout、attempt budget；
- Git code revision；
- details 和 summary 的 artifact hash。

发布时先写同盘 staging，重新计算 summary 和 hash，通过 verifier 后原子移动到最终
目录。run ID 已存在时拒绝覆盖。

`scripts/diagnose_finqa_run.py` 会先验证 source run，再要求 `split=dev` 和
`answer_strategy=program`。test run 会被显式拒绝，避免在 test 揭示后继续调参。

## 21.9 GitHub 上有什么证据

- 实现提交：`87d2f0c`；
- 文档与公开证据提交：`cba451a`；
- 本地全量：`2578 passed / 30 skipped / 3 warnings`；
- public audit：`968 candidates / 0 findings`；
- GitHub Actions：Ubuntu、Windows、Linux container contract 全部成功；
- 公开聚合证据：
  `docs/external_datasets/evidence/finqa_dev_diagnostic_v1.json`。

公开仓库没有上传 raw dev/test、case ID、问题、答案、证据文本、逐题表达式或
私有运行目录。公开证据只有 aggregate、hash、代码版本和边界声明。

## 21.10 面试时怎样回答

### 问：为什么项目只有 44%，是不是模型很差？

答：44% 是固定 100 题 test 上包含检索的端到端 strict，不是单纯模型分。
同样本 Oracle 是 52%，说明检索造成 8 点损失，但 gold evidence 下仍有约一半
错误，主要瓶颈是小模型的 operand selection 和财务运算计划。项目没有用模糊
“模型不行”结束，而是建立 gold-program 诊断，把下一步拆成检索、选数、计划和
尺度实验。

### 问：为什么不用另一个 LLM 判断错因？

答：FinQA 已提供 gold evidence、gold program 和执行结果，可用确定性规则直接
比较。这样便宜、稳定、可复算。对于不能确定语义因果的 operand/operation 比较，
项目明确叫 signal，并保留人工审核作为更高层证据。

### 问：为什么 63% 不能写成比 52% 提升？

答：63% 来自新 dev 样本，52% 来自已经冻结并揭示的 test 样本，而且两次之间
没有模型改动。跨 split 差值混合了样本难度，不能归因于代码提升。

### 问：Calculator 为什么算 Agent 工具，而不只是普通函数？

答：关键不在函数名字，而在责任和权限边界。LLM 只能提交受限表达式；工具有
明确 schema、资源预算、错误类型、调用计数和停止条件；最终值由可信执行器产生，
并进入 trace 和 evaluator。这是有界工具使用，不是让模型执行任意代码。

## 21.11 下一阶段：有界 plan-review 实验

下一阶段先在同一 100 题 dev 上增加实验臂：

```text
planner
  -> Calculator
  -> reviewer 检查年份、类别、operand、operation、sign、scale
  -> revised expression 或保持原表达式
  -> Calculator
  -> reviewer 失败时回退到已验证 planner 结果
```

必须同时统计：

1. strict 和 grounded strict 的净变化；
2. 原来错误变正确的数量；
3. 原来正确被 review 改错的数量；
4. review 保持、修改和协议失败回退次数；
5. generation/calculator 调用数；
6. mean/p95 延迟。

只有净收益、退化、成本和延迟都可接受，review 才能进入默认路径。无论结果好坏，
都不能再次运行已经揭示的 test 来挑 prompt。

## 21.12 学完后你应该能回答

1. Oracle 和 Hybrid 分别隔离了什么变量？
2. 为什么 20 题 dev 75% 不能写进简历当泛化正确率？
3. `strict`、`presentation tolerance` 和 `grounded strict` 有什么区别？
4. AST Calculator 防住了哪些输入，又没有解决哪些推理错误？
5. 哪些错误类别是直接事实，哪些只是机械 signal？
6. 为什么标签质量审计不能变成事后挑选 gold label？
7. plan-review 为什么必须有 fallback、退化统计和调用预算？

## 21.13 这次 Plan Review 实际改了什么

原有链路是：

```text
evidence -> 8B planner -> expression -> Calculator -> score
```

实验链路先变成：

```text
baseline expression
  -> reviewer 读取原问题、证据、表达式和 Calculator 结果
  -> KEEP 或 REVISE
  -> revised expression 再过 evidence guard
  -> Calculator 重新执行
  -> 与同一 baseline 做逐题成对比较
```

核心代码在：

- `app/external_datasets/finqa_review.py`：review prompt、响应 schema、执行和评分；
- `scripts/eval_finqa_review.py`：命令行入口与 artifact 门禁；
- `tests/external_datasets/test_finqa_review.py`：协议和不可变性测试。

`FinQAReviewCaseEvaluation` 为每题保存 baseline/final correctness、review 状态、
调用数和耗时。状态不是一个含糊的 `failed`，而是：

- `kept`：reviewer 明确保留 baseline；
- `revised`：提出新表达式，且安全校验和 Calculator 都通过；
- `fallback_protocol_error`：结构输出、候选引用或 Calculator 协议不合法，保留
  已验证 baseline；
- `not_applicable_baseline_error`：baseline 本身没有可 review 的有效表达式。

这里最重要的异常边界是：只有可预期的模型协议错误可以 fallback。Ollama 进程
退出、HTTP 超时或数据 hash 不一致会继续抛错并终止 run。否则基础设施故障会被
统计成“模型选择 KEEP”，得到虚假的稳定性。

## 21.14 v1 为什么变差，v2 又为什么没有变好

v1 8B reviewer 在 Hybrid 上：

```text
strict:             59% -> 55%
wrong -> correct:   1
correct -> wrong:   5
mean latency:       2.08x
```

逐题检查后发现 planner prompt 明确规定：当问题询问 ratio/percentage 时，模型
可以输出 raw ratio，统一评分器会处理显示尺度；reviewer prompt 却没有继承这条
合同。它把一些原本正确的比例又乘以 100。问题不是“8B 智商突然下降”，而是同一
系统的两个组件使用了不同单位协议。

v2 做了两项修复：

1. 将 raw-ratio、percentage、sign 和 scale 合同完整写入 reviewer；
2. 要求只有能指出无歧义错误时才 REVISE，否则必须 KEEP。

结果 Hybrid `59% -> 59%`，0 修正/0 退化。它证明 contract 修复消除了系统性
伤害，但也说明同一个 8B 模型重新阅读相同信息，并不会自动获得新的纠错能力。
因此“多一轮反思”不能凭架构图被算作质量改进。

## 21.15 30B Proposal 和匿名 8B 仲裁是什么

30B reviewer 能看到更多错误，在 100 题 tuning 上把 strict 从 `59%` 提到
`61%`，但它修正 5 题的同时改错 3 题。项目没有直接接受所有 proposal，而是增加：

```text
8B baseline
  + 30B revised proposal
  -> 按 SHA256(prompt_version | case_id) 隐藏成 candidate A/B
  -> 8B adjudicator 只能选择 A 或 B
  -> 不能生成第三个表达式
  -> 选中的表达式再由 Calculator 执行
```

代码位于：

- `app/external_datasets/finqa_adjudication.py`；
- `scripts/eval_finqa_adjudication.py`；
- `tests/external_datasets/test_finqa_adjudication.py`。

匿名化解决固定位置偏差：不能让 baseline 永远是 A，也不能告诉 adjudicator
“B 来自更大的模型”。只允许二选一则限制了能力边界，避免仲裁阶段再引入一个
未经审查的新算式。只有 30B 真正修改的题才调用 adjudicator，未修改题不浪费
额外调用。

100 题 tuning 最终为：

```text
strict:             59% -> 63%
grounded strict:    52% -> 55%
wrong -> correct:   4
correct -> wrong:   0
McNemar p:          0.125
mean latency:       3.90x
```

结果有希望，但 `p=0.125` 没有达到常用 `0.05` 门槛，而且它仍是开发样本。

## 21.16 exact McNemar 在这里衡量什么

这是 paired experiment：baseline 和新策略回答完全相同的题。普通 accuracy
只看总分，McNemar 只看两种不一致：

- `b = wrong_to_correct`：旧方案错、新方案对；
- `c = correct_to_wrong`：旧方案对、新方案错。

零假设是改进和退化同样可能。两侧 exact McNemar 用二项分布计算在 `b+c` 个
变化题中，出现至少这么不平衡的结果有多罕见。tuning 的 `b=4,c=0` 看起来很好，
但只有 4 个变化样本，`p=0.125`，证据还不够强。

这不代表策略一定无效。它只表示：在当前样本量下，还不能以冻结的 5% 显著性门槛
排除偶然波动。工业决策还必须同时看退化、grounding、调用成本和延迟，不能只追求
一个 p 值。

## 21.17 零重叠验证怎样防止继续在 tuning 上讲故事

在任何 validation 模型调用前，项目冻结：

- 50 题 dev cohort；
- 稳定 seed；
- selected case IDs SHA-256；
- 与 tuning 100 题 overlap 为 0；
- planner/reviewer/adjudicator/BGE-M3 model digest；
- prompt version、K、attempt budget；
- 成功门槛。

选 seed 时只使用 case ID 检查重叠，没有读取答案或分数。冻结协议在
`docs/external_datasets/evidence/finqa_plan_review_validation_protocol_v1.json`。

结果是：

| Stage | Strict | Grounded strict | 修正 | 退化 |
| --- | ---: | ---: | ---: | ---: |
| Hybrid baseline | 44% | 32% | - | - |
| 30B proposal | 48% | 36% | 3 | 1 |
| 8B adjudicated | 50% | 38% | 3 | 0 |

最终质量方向从 tuning 复现：strict `+6` 点、grounded strict `+6` 点、没有
正确题退化。但 exact McNemar 是 `0.25`，未达到预冻结 `0.05`。因此公开状态是
`COMPLETE_NOT_ADOPTED`，默认开关保持关闭，冻结 test 也没有重跑。

注意：这是与 tuning 零重叠的同一 FinQA dev split，不是跨数据集、跨公司或生产
流量 holdout。它比重复使用 tuning 更可信，但不能被写成跨域泛化。

## 21.18 Ollama/CUDA 故障是怎样定位的

validation 中 Ollama 从 0.32.4 自动升级到 0.32.5 后，`qwen3-coder:30b`
在 CUDA v13 和 cuda_v12 runner 都于 Flash Attention warm-up 退出，错误包含
`CUDA shared object initialization failed`。

诊断顺序是：

1. 用最小 prompt 单独调用 30B，仍失败，排除 FinQA 长 prompt 和 JSON schema；
2. 日志显示模型 tensors 已加载，失败发生在 CUDA kernel warm-up，不像 blob
   下载损坏；
3. 分别强制 CUDA v13/v12 backend，错误一致；
4. 启动独立 Vulkan Ollama endpoint，最小调用成功；
5. 不改模型 digest、prompt 或质量门槛，用 Vulkan 完成 reviewer；
6. 在 manifest 新增 `runtime_backend`，明确跨 backend latency 不可比较。

Vulkan 使 validation 最终平均延迟达到 baseline 的 `7.84x`。这个数字能证明
当前成本不可接受，却不能代表 30B 在正常 CUDA 上也一定慢 7.84 倍。失败 run
没有发布 artifact；同时暴露出长评测没有 checkpoint/resume，中断后需要重跑已
完成调用。

## 21.19 为什么没有上线，以及下一阶段做什么

没有上线的原因有三个：

1. 冻结统计门槛失败：`p=0.25 > 0.05`；
2. 端到端成本过高：generation `2.3x`、Calculator `2.6x`、本次 latency
   `7.84x`；
3. 验证仍来自 FinQA dev，没有跨域证据。

下一阶段应先做两项工程工作：

- **runtime uncertainty trigger**：只使用线上可获得信号，例如证据覆盖、表达式
  operand 是否全部有出处、年份/类别/尺度歧义、planner 自洽结果；不能偷看 gold
  answer。只有高风险问题调用 30B proposal/adjudication。
- **resumable evaluation**：每题完成后写 append-only checkpoint，恢复时验证
  run contract 和逐题 hash，跳过已完成 case；最终 artifact 仍原子发布且不可
  覆盖。

新的 trigger 不能在当前 validation 上继续反复调。应冻结新 cohort，报告触发率、
节省的调用数、strict/grounded strict、修正/退化、p 值和正常 CUDA latency。

本阶段最终工程门禁是：

```text
FinQA focused        63 passed
full pytest          2592 passed / 30 skipped / 3 warnings
public audit         978 candidates / 0 findings
compileall           PASS
pip check            PASS
git diff --check     PASS
```

这些门禁只证明实现、回归和公开数据边界通过，不能把未通过的模型统计门槛改写成
通过。模型策略状态仍是 `COMPLETE_NOT_ADOPTED`。

## 21.20 这一阶段的面试题与参考答案

### 问：为什么 reviewer 协议错误可以回退，Ollama 失败却不能回退？

答：结构输出错误是已定义的模型能力边界，回退到已验证 baseline 是安全降级；
Ollama 退出是基础设施故障。如果也静默回退，监控会把“reviewer 根本没运行”统计
成“reviewer 决定保留”，污染质量和可用性指标。

### 问：匿名 A/B 仲裁怎样减少偏差？

答：baseline 和 proposal 的位置由版本化 hash 决定，adjudicator 看不到来源，
所以不能因为“A 通常是旧答案”或“30B 应该更好”做选择。它只能从两个已经通过
Calculator 协议的候选中选一个，不能扩大动作空间。

### 问：strict 提升 6 点，为什么还不采用？

答：50 题上只有 3 个 paired flip，exact McNemar `p=0.25`，没有通过预冻结
显著性门槛；本次 Vulkan 延迟又是 baseline 的 7.84 倍。工程上线看的是冻结证据、
退化、成本和故障边界的组合，不是只看百分点。

### 问：v1 regression 给项目带来了什么价值？

答：它定位了 planner/reviewer 数值尺度合同不一致。修复后 v2 消除了 5 个正确题
退化，并促使项目把 prompt contract、review 状态和 paired regression 变成显式
测试与指标。负实验改变了系统设计，不是无效工作。

### 问：下一步怎样降低成本又保持收益？

答：先构建不使用 gold label 的 uncertainty trigger，只对高风险题调用 30B；
同时加入 checkpoint/resume，避免长实验因基础设施故障全部重跑。随后在新冻结
cohort 上联合测调用率、质量、退化、显著性和正常 CUDA 延迟。

## 21.21 为什么长评测需要 checkpoint，而不只是重新运行

上一阶段 30B 在 Ollama/CUDA warm-up 中断。原脚本把所有结果放在内存列表，只有
100 题全部完成后才写 `details.jsonl`。如果第 80 题失败，前 79 题的模型费用和
时间都无法恢复。

`app/evaluation/resumable_checkpoint.py` 的 contract 包含：

```text
source manifest/details SHA-256
selected case IDs SHA-256 和数量
model name/digest
prompt/algorithm version
Git code revision
runtime backend
timeout/max attempts
```

同一个 run ID 恢复时，任一字段不同都会失败。例如把 30B 换成 8B、把 Vulkan
换成 CUDA、修改 prompt 或换 source run，都不能接着旧 checkpoint 写。

每个 case 的提交过程是：

```text
row Pydantic model
  -> canonical JSON
  -> row_sha256
  -> envelope(ordinal, case_id, previous_record_sha256, row_sha256, row)
  -> 同目录 pending 文件完整写入 + fsync
  -> 仅当 000123.json 不存在时原子提交
```

恢复时重新校验连续序号、预期 case 顺序、row hash 和 hash chain，再从
`completed_count` 后一题开始。最终 immutable run 发布后，`seal.json` 绑定 final
manifest/details hash。checkpoint 仍是 D 盘 `.private` 数据，不上传 GitHub。

## 21.22 Trigger 的 8 个信号怎样计算

`app/external_datasets/finqa_uncertainty.py` 不让 LLM 自报 confidence。v1 使用：

| Signal | 权重 | 运行时含义 |
| --- | ---: | --- |
| ungrounded_operand | 3 | 表达式数字不在引用证据或固定常量白名单 |
| planner_retry | 2 | baseline generation calls 至少 2 |
| quarantined_content | 3 | Guard 隔离过检索内容 |
| multi_operation | 1 | 表达式至少两个运算 |
| many_numbers | 1 | 引用证据至少 12 个不同数字 |
| multiple_citations | 1 | 至少引用两个 evidence units |
| multi_year | 1 | 引用证据至少三个不同年份 |
| ratio_division | 1 | ratio/percentage/change 类问题包含除法 |

总分 `>=2` 才触发。强信号可以单独触发，弱信号必须至少两个同时出现。这个规则
不是“判断答案对不对”，而是判断是否值得支付 30B review 成本。

### 怎样证明没有偷看 gold

测试对同一 runtime 输入修改：

- gold program 和 `exe_ans`；
- gold evidence IDs；
- strict/presentation correctness；
- evidence recall、citation precision/recall；
- grounded correctness。

两次 `FinQARuntimeUncertainty` 必须完全相等。离线 evaluator 当然会用 strict 判断
trigger 最后是否有效，但线上 `assess_finqa_runtime_uncertainty()` 不接收这些标签。

## 21.23 成本结果应该怎样读

100 题 tuning：

```text
triggered                         67/100
strict / grounded                63% / 55%（与 full strategy 相同）
wrong->correct / correct->wrong  4 / 0
generation calls                 84 vs full 124，减少 32.26%
Calculator calls                 减少 31.76%
```

冻结算法后，50 题零重叠 validation：

```text
triggered                         31/50
strict / grounded                50% / 38%（与 full strategy 相同）
wrong->correct / correct->wrong  3 / 0
generation calls                 42 vs full 65，减少 35.38%
Calculator calls                 53 vs full 80，减少 33.75%
historical incremental latency   减少 28.06%
```

调用减少是精确反事实：未触发 case 若不执行 review，就一定省掉 artifact 中记录的
那些调用。latency 则不是实际 selective wall-clock，只是把历史逐题增量相加；
而历史 30B 使用 Vulkan、baseline/adjudicator 使用 CUDA，因此不能写成线上 p95。

## 21.24 为什么成本 gate 通过仍然不上线

原因有四个：

1. underlying quality 的 McNemar 仍是 `p=0.25`，没有新修正样本；
2. trigger validation 复用了已经揭示的 50 题 cohort，不是新的独立 holdout；
3. 当前只做离线选择，没有真实执行 selective pipeline 的 wall-clock；
4. 30B 正常 CUDA runtime 尚未恢复验证。

正确表述是：“v1 trigger 在两个 cohort 上捕获全部已观察修正，并把额外调用减少
约三分之一，因此值得进入新 cohort 的真实选择性实验。”错误表述是：“线上成本
降低 35%，模型已上线。”

## 21.25 公开协议 hash 抄写错误怎样处理

审计发现早期
`finqa_plan_review_validation_protocol_v1.json` 的 `split_sha256` 手工抄错。
实际 `FINQA_DEV_SHA256` 和 baseline/review/adjudication 三个 manifest 始终使用
正确值，所以模型输入、样本和结果没有变化。

项目没有直接改掉旧冻结文件，因为那会让历史证据看起来从未出错。处理方式是：

1. 保留原 protocol 和它的 SHA-256；
2. 新增 `finqa_plan_review_validation_protocol_erratum_v1.json`；
3. 同时记录错误值、权威值、根因和影响矩阵；
4. 增加测试，让 erratum 的正确值等于代码常量，并验证新协议源码 hash。

面试时可以这样回答：不可变审计不是“永远不会写错”，而是错误发生后不能静默
覆盖；必须让原记录、纠错记录和实际运行证据形成可追踪链。

### 新增面试题：为什么不用模型 confidence 做 trigger？

模型自报 confidence 往往没有校准，而且同一个模型可能对错误计划非常自信。当前
规则使用可解释、可复算的结构信号，并在 paired artifact 上测 beneficial capture
和 regression。以后可以加入学习型 router，但也必须独立校准和冻结验证。

### 新增面试题：hash chain 能防止所有恶意篡改吗？

不能。未 seal 的本地攻击者若能重写全部记录和 contract，仍可能重算整条链。
hash chain 主要发现意外损坏、错序、缺失和局部改写；最终可信锚点是 immutable
run 的 artifact hash、Git-bound contract 和 seal。更强威胁模型需要外部签名或
WORM 存储，当前项目没有声称已经实现。

本阶段最终验证：

```text
FinQA + checkpoint focused    73 passed
full pytest                   2602 passed / 30 skipped / 3 warnings
public audit                  986 candidates / 0 findings
compileall / pip / diff       PASS / PASS / PASS
```

这些工程门禁不改变模型采用结论：成本过滤 gate 通过，默认生产路由仍关闭。

## 21.26 这次效果到底有没有提升

有“方向性提升”，但没有达到“可以默认启用”的证据等级。

新的 100 题与此前 100 题 tuning、50 题 validation 的 case ID 完全不重叠。结果：

```text
baseline strict              53%
selective strict             55%   (+2 percentage points)
baseline grounded strict     38%
selective grounded strict    40%   (+2 percentage points)
wrong -> correct             3
correct -> wrong             1
exact McNemar p              0.625
```

这里的 `+2 percentage points` 是“百分点”，不是相对提升 2%。100 题中多对 2 题，
相对 baseline strict 的提升约为 `2/53=3.77%`，但项目不使用这个更容易误导的写法。

为什么不能只看 `55 > 53`？因为同一批题上既有 3 个错误被修正，也有 1 个正确
答案被改错。配对 McNemar 检验关心的正是这两个不一致方向。`p=0.625` 表示目前
样本不足以支持“改进不是偶然波动”的强声明；它不表示系统有 62.5% 概率无效，
也不表示 baseline 有 62.5% 概率更好。

## 21.27 这次真正新增了哪条运行链路

历史 uncertainty 实验只是读取已有 full-review artifact，计算“如果当时跳过这些
题会省多少”。这次新增的 `eval_finqa_selective.py` 在模型调用发生之前决定路线：

```text
question
  -> hybrid retrieval
  -> 8B planner + Calculator
  -> runtime uncertainty
       -> low risk: baseline final
       -> high risk: 30B review
            -> KEEP: baseline final
            -> revised: anonymous 8B A/B adjudication
  -> production final frozen
  -> shadow full evaluation for untriggered cases
```

要特别理解三点：

1. trigger 不能读取 gold program、正确答案或本题 strict 分数，否则是标签泄漏；
2. shadow 只能在 production final 固定后运行，否则会污染线上策略；
3. reviewer 不是直接写最终数字，而是提交受限表达式，仍由 Calculator 执行并
   经过 evidence grounding。

### `FinQASelectiveCaseEvaluation` 为什么字段很多

逐题 schema 同时保存：

- baseline 的表达式、执行结果、正确性、调用数和延迟；
- uncertainty score、原因和触发决定；
- production review/adjudication 是否实际执行；
- production final route 和结果；
- shadow review/adjudication 是否执行及其反事实结果；
- 各阶段延迟分区和总延迟。

这些字段不是为了“技术堆叠”，而是为了让聚合指标能够从逐题事实重算。例如记录
若声称 `route=baseline`，却又声称 production adjudication 已执行，Pydantic
校验会直接拒绝；若各阶段毫秒数加起来不等于 total，也会拒绝。

### 为什么同时有 production arm 和 shadow arm

production arm 回答“这条选择性策略实际上会输出什么、付出多少调用”。shadow arm
回答“被 trigger 跳过的题如果仍做全量复核，会不会错过修正”。没有 shadow，
我们只能看到 selective 得分，无法计算 beneficial capture；让 shadow 影响 final，
又会把选择性策略伪装成全量策略。

## 21.28 100 题是怎样冻结的

`freeze_finqa_selective_protocol.py` 做以下顺序：

1. 校验 FinQA revision、dev 文件 SHA-256 和总题数 `883`；
2. 读取旧 tuning/validation 样本，只提取其 case ID；
3. 建立排除集合，共 `150` 个唯一 case；
4. 用固定 seed 在剩余题中确定性选 100 题；
5. 写入 selected case IDs 的集合 hash，而不公开 case ID；
6. 写入模型 digest、源码 hash、runtime 参数、成功门槛；
7. 在任何正式模型调用前提交协议。

选中集合 hash 为：

```text
cbb5c205609e618292f9e7465e2ea25803311f99af2a1f686f7674a0930987ae
```

这个 hash 不是用来从 hash 还原题目，而是以后核对“运行的是否仍是同一集合”。

## 21.29 30B CUDA 故障是怎样诊断和修复的

症状是 `qwen3-coder:30b` 在 Ollama `0.32.5` 上退出，底层出现
`CUDA error: shared object initialization failed`。诊断没有直接改业务代码，
而是按“最小复现 -> 单变量探针 -> 集成复验”推进：

1. 用最小 chat 请求仍失败，排除 FinQA prompt 和 JSON schema；
2. 关闭 Flash Attention 后仍失败，只是失败点从 attention 移到 `MUL_MAT`；
3. 改变 GPU offload layers：`num_gpu=10/7` 失败，`1/2/5` 成功；
4. 选择保守的 `num_gpu=5`，而不是继续逼近不稳定阈值；
5. 固定 `num_ctx=4096`、`num_batch=512`；
6. 在正式 11434 endpoint 用完整 application request 再验证。

运行时观测：

```text
qwen3:8b           100% GPU
bge-m3             100% GPU
qwen3-coder:30b     89% CPU / 11% GPU
```

所以“修复”的准确含义是：通过受控 partial offload 恢复稳定执行。它不是找到
Ollama/CUDA 底层 bug，也不是让 30B 变成 full-GPU。因为 8GB 显存无法容纳该模型
的完整运行工作集，绝大部分计算仍在 CPU，延迟不能外推到生产 GPU。

### 为什么没有把 options 直接加到共享 `ollama_chat.py`

第一次实现尝试修改共享 Ollama client，旧 frozen FinQA holdout 的源码 hash 测试
立即失败。这不是“测试太严格”，而是旧证据明确绑定了那个文件的字节。继续修改会
让历史运行无法再证明对应哪份源码。

最终做法是恢复共享文件原字节，只在新的 selective CLI 的 30B review 调用边界
传入 runtime options。这样：

- 旧 holdout 的 source binding 不变；
- 新协议能精确记录新参数；
- 影响范围只限这次实验；
- 将来通用化必须另起版本化 client contract，不能悄悄改变历史语义。

## 21.30 为什么保留 v1 incident，而不是改掉 v1

最初 v1 协议在发现 CUDA 问题前已冻结。好消息是它还没有执行任何 selected case：

```text
selected cases executed       0
checkpoint rows               0
model outputs observed        0
```

因此可以在不看结果的前提下保留同一批 100 题，新增 runtime options 后冻结 v2。
项目发布 append-only incident，记录 v1 hash、失败探针和 superseded 原因；v2 再
绑定 incident hash。这样审计者可以看见“先出过问题，后来怎样修”，而不是看到
一份看似从未出错的完美历史。

## 21.31 成本和延迟怎样理解

真实 selective 运行：

```text
eligible / triggered                96 / 63
route baseline/reviewed/adjudicated 37 / 41 / 22
incremental generation calls        85 vs full 125  (-32.00%)
incremental Calculator calls        107 vs full 154 (-30.52%)
selective mean / p95                9.02s / 15.24s
selective total                     902.33s
shadow-full experiment total        1184.61s
selective reduction                 23.83%
```

`eligible=96` 是因为 4 题 baseline 输出无法按协议解析，不能进入正常数值 review
流程。`triggered=63` 按完整 100 题是 63%，按 eligible 题则是 65.63%；冻结协议
选择报告前者，避免事后改变分母。

generation 和 Calculator 的“增量”只统计 baseline 之后 review/adjudication
新增的调用；baseline 本来就必须执行，不能把它算成 router 节省。

`23.83%` 是同一运行、同一机器、同一 cohort 内 selective 与隔离 shadow-full
对照的总时间差。它不是并发服务 p95，不包含生产队列、网络、冷启动或多用户负载。

## 21.32 为什么质量、成本部分提升仍不采用

预冻结门槛包括：

```text
strict 不低于 baseline                  PASS
grounded strict 不低于 baseline         PASS
correct -> wrong 必须为 0               FAIL (1)
trigger rate <= 75%                     PASS
generation reduction >= 20%             PASS
Calculator reduction >= 20%             PASS
exact McNemar p <= 0.05                 FAIL (0.625)
真实 selective latency 存在             PASS
full-GPU latency evidence 存在           FAIL
```

`overall_adoption_gate_passed=false` 是这些条件的合取结果。工程上最重要的不是想办法
解释掉失败项，而是保持默认开关关闭，并把失败转成下一轮可检验假设。

## 21.33 断点恢复这次不是模拟测试

正式运行第一次在 26 题完成后退出，exit code 为 `0x40010004`，没有 Python
traceback。没有证据能确定是谁终止，所以文档只写 external interruption。

第二次执行完全相同命令时：

1. 读取 checkpoint contract；
2. 核对 protocol、data、sample、model、runtime 和 code revision；
3. 按顺序重算 26 个 row hash 与 chain link；
4. 输出 `resuming after 26/100 completed cases`；
5. 从第 27 题继续；
6. 完成 100 题后发布并 seal。

这能写进简历，因为它是一次真实故障恢复证据。但准确范围是“单机逐题评测可恢复”，
不是“分布式 exactly-once”或“生产容灾”。

## 21.34 下一版从哪里改，但不能在哪里验证

聚合错误分析得到三个研发方向：

1. literal-only、zero-operation baseline 也可能漏掉必要加法，考虑加入低成本
   arithmetic-plan risk signal；
2. 百分比变化先检查时间方向与 operand alignment，再允许 revised proposal；
3. 4 个 baseline protocol error 说明 planner JSON/表达式可靠性仍需提高。

但这 100 题已经被查看。正确做法是在旧的已揭示 tuning/validation cohort 上开发，
然后换另一批未见 FinQA dev 或不同公开金融 QA 数据集确认。错误做法是在本次 100
题上加规则，跑到 56% 后把 56% 写成独立验证。

## 21.35 简历够不够，以及怎样写

对 AI Agent 开发岗实习，项目已经有可展示价值，主要价值不应只写“准确率 55%”，
而应写出你解决了 Agent 系统中的可测量决策、成本和可靠性问题。

推荐表述：

> 为金融数值 RAG 构建 runtime-only 风险路由、30B 有界复核与匿名 8B 候选仲裁；
> 在新零重叠 100 题 FinQA cohort 上将 strict/grounded strict 从 53%/38%
> 提升到 55%/40%，同时减少 32.0%/30.5% 的增量生成/计算器调用；因 1 个退化和
> McNemar p=0.625 未通过预注册门槛，保持默认关闭。

第二条可以写工程可靠性：

> 实现绑定数据、样本、模型 digest、代码 SHA 与 runtime 的 hash-chained 逐题
> checkpoint；一次正式运行中断后恢复已完成 26/100 题并完成不可变发布与 seal，
> 避免重复模型调用。

这两条比“实现 Agentic RAG，准确率提升”更可信，因为数字、边界和不采用结论都能
在公开 protocol/results 与测试中核验。

### 面试题：为什么有 shadow full arm？

答：router 跳过低风险题后，线上只能看到 selective 结果，不知道跳过的题是否本可
被 30B 修正。shadow 在 production final 固定后补跑 full strategy，用来计算
beneficial capture 和真实成本差；它不能影响 production output，避免评测泄漏。

### 面试题：为什么 `p=0.625` 还值得保留这项工作？

答：它否定的是“已证明稳定质量提升”，不是工程本身。实验仍证明了端到端路由、
约三成调用节省、23.83% 同运行时间差和真实断点恢复；同时暴露了 1 个退化与漏捕获
模式，为下一轮设计提供受约束假设。可信项目需要能发布负结论。

### 面试题：为什么 30B 不直接全量复核？

答：全量复核在新 cohort 只比 selective 多对 1 题，却需要更多增量调用和时间。
但 selective 又漏掉了这个修正，所以当前正确决策是继续研究 router，而不是仅凭
成本或质量一方开启默认路径。

### 面试题：模型更大为什么仍会改错？

答：更大模型增加了候选多样性，不保证数值方向、单位和时间语义总正确。项目让
30B 只提 proposal，再由匿名 8B 二选一，并保留 Calculator/evidence guard；本次
仍出现 temporal direction 退化，说明仲裁也需要独立校准，不能把模型规模当保证。

## 21.36 Gate A/B：为什么先把财务数字变成有身份的候选

### 旧方法哪里不够

旧 planner 看到一段证据后，直接输出：

```json
{
  "expression": "(120 - 100) / 100",
  "cited_candidate_ids": ["evidence-01"]
}
```

`evidence-01` 可能同时包含多个年份、多个指标和多个数字。宿主程序能检查表达式
是否可计算，却不能回答：

- `120` 到底来自 2020 还是 2019；
- 它是 revenue 还是 headcount；
- 单位是美元、百万美元还是百分比；
- 它是否真的出现在已准入证据中；
- 括号是运算分组还是财报里的负数表示。

这也是为什么 Oracle evidence 仍会有大量错误：证据已经给对了，模型仍可能从正确
证据中复制错误的 operand。

### Gate A 做了什么

Gate A 没有立刻写实现，而是先在
`docs/external_datasets/finqa_typed_program_protocol.md` 冻结合同，并在
`tests/external_datasets/red/test_finqa_typed_program.py` 写 12 个失败测试。

这些测试先规定未来系统必须拒绝错误年份、错误 metric、方向颠倒、未准入来源和
模型凭空生成的 literal，也必须正确处理 thousand/million、百分比、括号负数、
多步引用和等价程序。这样后续实现不能为了让某个已知样本通过而偷偷改变问题定义。

### Gate B 的新数据流

核心实现位于：

```text
app/external_datasets/finqa_typed_program.py
```

数据流是：

```text
FinQA 原始二维表
  -> 只读取 admitted evidence row
  -> 每个 data cell 独立处理
  -> 继承明确的 row header / column header
  -> Decimal 标准化
  -> 精确字符跨度与原文 hash
  -> 稳定 candidate_id
  -> NumericCandidate
```

例如：

```text
header = ["", "2020", "2019"]
row    = ["Revenue", "$120 million", "$100 million"]
```

不会再只依赖模型阅读一整句，而会形成两个不同候选：

```text
candidate A: Revenue / 2020 / USD / million / 120000000
candidate B: Revenue / 2019 / USD / million / 100000000
```

候选 ID 绑定来源文档、evidence、表格坐标、字符位置、原文 hash、标准化值、单位、
scale、sign 和 role。它不使用列表序号，所以相同输入重复执行会得到相同 ID；相同
数值来自不同文档或不同单元格时不会被错误合并。

### 为什么用 Decimal

二进制浮点不能精确表示很多十进制小数。财务程序如果用 `float`，可能产生
`0.1 + 0.2 != 0.3` 一类误差。Gate B 使用 `Decimal`，并规定：

```text
$2.5 million -> 2500000
12%          -> 0.12
35 bps       -> 0.0035
(120)        -> -120
```

标准化值用于计算，但候选仍保留原始 scale、unit 和 provenance，不能只剩一个脱离
来源的数字。

### 哪些字段宁可不知道也不能猜

表格候选只从明确的行列标题继承 metric 和 period。普通文本只有在同一受限句段内
出现唯一年份时才绑定年份；如果一句话同时出现 2019 和 2020，候选 period 保持
`None`。entity、unit 等无法从显式结构确定时同样保持 `None/unknown`。

`2020` 被标成 `period_label`，`Page 12` 被标成 `page_number`，`3rd` 被标成
`ordinal`。它们可以保留用于审计，但不能默认进入未来的计算程序。

### 实现时发现了什么错误

第一次格式测试是 `14 passed / 2 failed`：

1. 正则为了防止错误小数，把句末 `42.` 也当成非法数字；
2. `FY2020` 的年份紧邻字母，普通数字边界没有匹配。

修复没有把规则整体放宽。代码只在句点或逗号后面仍是数字时阻止匹配，并为显式年份
增加独立的 period-label 扫描。最终 Gate B focused tests 为 `20 passed`。

### 表格和跨页问题解决到什么程度

FinQA 使用已经结构化的 JSON 表格，所以 Gate B 能可靠取得 row/column header。
企业接入层对 DOCX、HTML、CSV、JSONL 也保存结构化表格，chunk 时会重复表头。

但原始 PDF 目前只是逐页抽取文本并保留 page locator。项目尚未实现 OCR、PDF
表格检测、合并单元格恢复、双栏阅读顺序、重复页眉清理和跨页表格拼接。因此不能在
面试中说“已经解决跨页 PDF 表格”；准确说法是“已解决结构化表格进入财务候选层后
的单元格语义对齐，原始 PDF layout recovery 是明确 backlog”。

### 这个阶段能不能说准确率提升

不能。Gate B 没有运行 LLM，也没有重跑 disclosed dev 或 frozen test。它证明的是：

- 候选抽取是确定性的；
- 财务格式标准化符合合同；
- 来源和表格坐标不会丢；
- 噪声数字不会默认成为 operand；
- 公开 manifest 可以复算且不泄露评测内容；
- 全仓 `2632 passed / 29 skipped / 10 xfailed`。

Gate B 收口时的 10 个 `xfailed` 是当时尚未实现的 Gate C
typed planner/compiler 合同。它们先使用 `strict xfail` 防止未来实现被悄悄忽略；
Gate C 完成后已移除标记并全部转为普通 pass。

## 21.37 Gate C：模型为什么只能选 ID，宿主怎样证明程序可执行

### 从“表达式字符串”变成“受限 AST”

Gate B 让每个财务数字有了 candidate ID，Gate C 继续禁止模型把数字复制回自由
表达式。模型现在只能输出：

```json
{
  "dsl_version": "finqa_typed_financial_dsl_v1",
  "steps": [
    {
      "step_id": "step-01",
      "operation": "SUB",
      "arguments": [
        {"candidate_id": "num-...new"},
        {"candidate_id": "num-...old"}
      ]
    }
  ],
  "output_step_id": "step-01"
}
```

每个 argument 只能是：

```text
CandidateRef(candidate_id)
StepRef(previous_step_id)
```

不存在 `literal`、`expression` 或 Python 代码字段。因此模型负责“选哪个数、做什么
操作”，宿主负责“这些数是否允许被选、这个操作是否合法、最后怎样计算”。

### JSON Schema 为什么不是安全边界

Ollama 的 structured output 能提高格式成功率，但模型、服务版本或 fake client
仍可能返回不符合 schema 的 JSON。项目不会因为给了 response schema 就直接相信
结果，而会再次执行：

```text
raw response
  -> duplicate-key-safe JSON parser
  -> Pydantic extra=forbid
  -> literal/operation/size checks
  -> candidate lookup
  -> admitted evidence check
  -> financial compatibility check
  -> Decimal compiler
```

所以 structured output 是可靠性工具，宿主 validator 才是 correctness 和安全边界。

### Validator 具体检查什么

固定顺序包括：

1. payload、step 和 argument 是否超预算；
2. operation 是否在七个允许项中；
3. 是否出现 literal、裸数字、expression 或额外字段；
4. candidate 是否存在且 ID 唯一；
5. step ID 是否从 `step-01` 连续编号；
6. StepRef 是否只引用已经完成的前序步骤；
7. raw text、字符跨度和 hash 是否一致；
8. normalized value、unit、scale 和 sign 能否从 raw text 重新抽取出来；
9. evidence 是否属于 admitted set；
10. candidate role 是否为 operand；
11. 年份、metric、entity、unit、scale、方向是否兼容；
12. arity、零除、Decimal 精度、结果大小和输出单位是否正确。

这里第 8 项是实现审查时补出的重要约束。只检查 `"120"` 的 hash 还不够，因为有人
可能保留原文和 hash，却把 `normalized_value` 改成 `121`。现在 validator 会对精确
原文重新运行 Gate B extractor，再比较结构化值。

### 七个 operation 怎样计算

```text
ADD(a,b)                 a + b
SUB(a,b)                 a - b
MUL(a,b)                 a * b，至少一个参数必须是 ratio
DIV(a,b)                 a / b，b 不能为 0
PERCENT_CHANGE(new,old)  (new - old) / old
RATIO(part,total)        part / total
AVERAGE(a,b,...)         sum / 参数个数
```

ADD、SUB、AVERAGE 和 PERCENT_CHANGE 会检查 metric/entity 与单位兼容。DIV/RATIO
检查单位能否形成允许的比值。V1 不实现通用量纲代数，所以 `USD/share` 等复合单位
仍是明确限制。

### 多步程序怎样工作

例如先算差值，再除以旧值：

```text
step-01 = SUB(new_candidate, old_candidate)
step-02 = DIV(step-01, old_candidate)
output  = step-02
```

StepRef 只能向后引用已完成步骤。`step-02` 引用 `step-03` 会在执行前报
`forward_step_reference`。每一步的 Decimal 值都会进入不可变 `step_values`，
最终结果还保留全部 candidate/evidence 来源闭包。

中间结果还必须保留“它代表什么”。例如：

```text
step-01 = MUL(100 USD revenue, 0.5 ratio)  -> 50 USD revenue
step-02 = ADD(step-01, 25 USD revenue)     -> 75 USD revenue
```

最初实现只保留了 step-01 的数值和单位，丢掉 `revenue/company` 元数据，导致
step-02 被当成“已知 revenue + 未知 metric”而保守拒绝。现在 MUL/DIV 会从承担
实际量纲的 operand 传播 metric/entity，并由两步回归测试证明结果和来源闭包正确。

### 为什么不用 float、eval 或 exec

compiler 通过 operation 分支直接调用 `Decimal` 运算，没有把字符串交给 Python。
测试会解析源码 AST，确认没有直接调用 `eval` 或 `exec`。Decimal context 精度固定
为 50，绝对值上限为 `1e30`，避免模型构造超大计算消耗资源。

### Typed Planner 做了什么

新类位于：

```text
app/external_datasets/finqa_typed_planner.py
```

它和旧 `LocalFinQAProgramAnswerer` 并存，不会修改旧实验含义。输入包括问题、admitted
候选、可选的 admitted evidence context 和 `FinancialQuestionIntent`。输出 schema
只列出允许 candidate ID 和 StepRef。

第一次输出若被宿主拒绝，默认最多修复一次。repair prompt 只告诉模型稳定 failure
reason 和 candidate allowlist，不提供 gold program 或正确答案。连续失败后抛出
`TypedPlannerProtocolError`，记录 attempts、latency 和最后原因。

### Intent 为什么仍是有限能力

当前 deterministic intent extractor 只识别明确词语：

```text
percentage change / growth rate -> PERCENT_CHANGE
average / mean                  -> AVERAGE
ratio / what percent            -> RATIO
difference / absolute change    -> SUB
total / sum / combined          -> ADD
product / multiply              -> MUL
divide / quotient / per         -> DIV
```

它不会凭空猜 metric 和 entity。百分比变化必须出现两个明确年份，否则
`ambiguous_intent`。这保证可复现和保守，但不能宣称已经理解所有自然语言财务问题。

### 实现与验收过程中发现的六个工程问题

1. provenance hash 不能证明 normalized value 正确，因此加入确定性重建检查；
2. `frozen=True` 不会递归冻结普通 dict，因此 `step_values` 改成运行时只读 mapping，
   序列化时仍输出 JSON object；
3. Gate C 修改了与 extractor 同文件的源码 hash，不能覆盖 Gate B manifest v1。
   项目保留 v1 原字节并新增 v2，测试要求两版 candidate set、配置和 fixture hash
   完全一致。
4. 只检查 candidate ID 格式还不够，攻击者或错误代码可以换一个合法形状的 ID。
   Validator 现在会从 source/evidence、表格坐标、原文 span、值、单位、scale 和
   role 重新计算 candidate ID；单候选 ID 替换会在执行前失败。
5. 金额与 ratio 计算后的中间状态曾丢失 metric/entity，合法多步程序被误拒；
   现在从有量纲 operand 传播元数据，并新增真实两步执行回归。
6. 为避免写 C 盘，把 pytest `--basetemp` 放到 `.tmp` 后，四个 JWT/JWKS 测试按
   安全策略拒绝了私钥路径。正确修复不是放宽“私有身份文件必须位于 `.private`”
   的规则，而是把 D 盘测试临时根放到项目 `.private` 下。受影响的 18 个测试随后
   全部通过。

### 本阶段能说什么、不能说什么

可以说：

> 实现 reference-only typed financial DSL、candidate/admission/provenance 与
> temporal/unit compatibility validator，以及无 eval/exec 的 Decimal compiler；
> 用 fake model 和结构化 FinQA 表格验证 bounded repair 与端到端执行。

不能说：

> FinQA 准确率已经提高。

Gate C 没有运行真实模型、disclosed dev 或 frozen test。它证明机制满足合同，不证明
模型在新样本上会更常选对程序。效果判断必须等 Gate E retrospective 和 Gate F
confirmatory protocol。

最终门禁为：

```text
Gate C focused     43 passed
external datasets  162 passed
full repository    2674 passed / 30 skipped / 0 xfailed
public audit       1006 candidates / 0 findings
```
