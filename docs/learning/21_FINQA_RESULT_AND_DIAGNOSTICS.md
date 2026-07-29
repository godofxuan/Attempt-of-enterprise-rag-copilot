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
