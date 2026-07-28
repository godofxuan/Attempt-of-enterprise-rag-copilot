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

