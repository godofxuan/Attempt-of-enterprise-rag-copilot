# FinQA Gate E：真实模型评测与失败复盘

这一步最重要的结论不是“类型化程序做完了”，而是：

> Gate C/D 的代码机制虽然通过了合成测试，但第一次真实模型开发集评测证明，
> 当前版本不具备可用性，不能接入默认回答路径。

这是一次有价值的失败。它把“代码能运行”“安全规则严格”“真实任务效果好”这
三件经常被混在一起的事情分开了。

## 1. 为什么要做 Gate E

Gate C 实现了单个 typed program，Gate D 实现了多个 typed program 和确定性
选择器。此前的测试只能证明：

- 模型不能直接塞入数字 literal；
- operand 必须引用宿主机给出的 candidate ID；
- candidate 必须来自 Guard 放行的证据；
- provenance、单位、年份、方向和 Decimal 计算受到宿主机检查；
- 多候选不能靠重复程序、交换参数或 `+0` 填充来刷票。

这些是“机制正确性”，不是“回答正确率”。真实模型可能根本生成不出通过规则的
程序，规则也可能错误拒绝本来合法的财务计算。因此 Gate E 要回答：

1. 类型化程序是否真的修复历史 operand selection 错误？
2. 它新增了多少拒答和回归？
3. 多候选是否比单候选更有效？
4. 多出来的模型调用和延迟是否值得？

## 2. 为何只能叫回顾性开发评测

使用的是以前已经分析过的 100 道 FinQA dev 题，所以结果统一标记为：

```text
RETROSPECTIVE_DEVELOPMENT_ONLY
```

它不能叫新 holdout，也不能写成“FinQA 测试集准确率”。为了不再次污染冻结的
test，Gate E 直接复用了历史保存的每题 Top-10 evidence ID，没有重新调整检索器，
也完全没有读取 test。

协议在模型调用前固定于：

```text
docs/external_datasets/evidence/finqa_typed_retrospective_protocol_v1.json
```

真实执行代码提交是：

```text
9180b7ecd61bbabc1f00edc2929877c471fa769b
```

## 3. 三个比较臂到底有什么区别

### B0：旧的自由表达式程序

```text
问题 + Top-10 证据
  -> Qwen 输出 "(120 - 100) / 100" 这样的字符串
  -> 宿主机 AST 白名单解析
  -> Decimal Calculator
  -> 数值答案和 citation
```

优点是覆盖率高、输出简单。缺点是模型自己重新抄写数字，可能选错相邻年份或相似
表格行。

### B1：单个类型化程序

```text
证据
  -> deterministic numeric candidate extraction
  -> candidate_id + value + period + metric + unit + scale + provenance
问题
  -> deterministic FinancialQuestionIntent
LLM
  -> 只输出 operation 和 candidate_id/step_id 引用
宿主机
  -> compatibility validator
  -> Decimal compiler
```

模型不能输出 `120`，只能输出类似：

```json
{
  "steps": [{
    "step_id": "step-01",
    "operation": "ADD",
    "arguments": [
      {"candidate_id": "num-..."},
      {"candidate_id": "num-..."}
    ]
  }],
  "output_step_id": "step-01"
}
```

### B2：三个类型化程序再选择

B2 一次要求模型产生三个 typed programs。三个程序分别通过 B1 的 validator 和
compiler，然后按以下顺序选择：

```text
独立最小 provenance 支持更多
-> step 更少
-> candidate 更少
-> evidence 更少
-> 若不同答案仍同 rank，则拒答 AMBIGUOUS
```

B2 不是三个 Agent，也不是让另一个 LLM 评分。最终选择完全由宿主机的确定性规则
完成。

## 4. 运行器为什么比较工程化

主要代码是：

```text
app/external_datasets/finqa_typed_retrospective.py
scripts/eval_finqa_typed_retrospective.py
scripts/publish_finqa_typed_retrospective.py
scripts/verify_finqa_typed_retrospective_public.py
```

运行前检查：

- dev 文件 SHA-256；
- 100 个 case ID 的顺序哈希；
- 历史 manifest/details 哈希；
- `qwen3:8b` 的 Ollama 模型 digest；
- 11 个执行源码文件的 SHA-256；
- Gate B/C/D 的版本号；
- 超时、尝试次数、程序数量和比较臂。

每完成一题才追加一个 hash-chained checkpoint record。若 Ollama 或终端中断，
下次从已完成题目继续。HTTP 故障不会被伪装成“答错”：

```text
transport/runtime failure -> 整个运行中止，等待 resume
bounded model output fail -> PROTOCOL_ERROR
intent/compatibility/selection fail closed -> REFUSED
valid numeric output -> ANSWERED
```

每题使用循环顺序：

```text
B0 -> B1 -> B2
B1 -> B2 -> B0
B2 -> B0 -> B1
```

这样降低固定把某个臂放在模型冷启动位置造成的延迟偏差。

## 5. 最终数字怎么读

| 指标 | B0 | B1 | B2 |
| --- | ---: | ---: | ---: |
| coverage | 99% | 9% | 11% |
| strict accuracy | 57% | 5% | 6% |
| answered 后的准确率 | 57.58% | 55.56% | 54.55% |
| grounded strict | 50% | 5% | 6% |
| refusal | 0 | 36 | 89 |
| protocol error | 1 | 55 | 0 |
| generation calls | 101 | 122 | 118 |
| mean latency | 1.09s | 13.28s | 15.90s |
| p95 latency | 1.39s | 32.02s | 33.34s |

### coverage 是什么

```text
coverage = ANSWERED 数量 / 全部题目数量
```

B1 的 coverage 只有 9%，表示 100 道题只有 9 道给出答案。即使它在 9 道题中全对，
也不能说系统很好，因为用户 91% 的问题都得不到回答。

### accuracy on answered 为什么还要单独看

它回答“系统愿意回答时有多准”。B1 是 5/9，B2 是 6/11，都只有约 55%，和 B0
总体 57% 没有本质优势。因此问题不只是 validator 太严格。若直接放宽规则，新增的
答案也没有证据会更正确。

### grounded strict 是什么

它要求：

```text
数值严格正确 AND gold evidence citation recall = 100%
```

B1/B2 的 grounded strict 只有 5%/6%，说明低覆盖率没有换来更可靠的完整证据链。

### correct-to-wrong 与 wrong-to-correct

B1 相对 B0：

```text
wrong -> correct  2
correct -> wrong 54
```

B2 相对 B0：

```text
wrong -> correct  1
correct -> wrong 52
```

这不是轻微波动，而是大规模有害回归。McNemar 的极小 p-value 表示在这 100 道
已披露 dev 题上，成对差异非常不对称；但方向是变差，而且这不是独立 holdout，
所以不能把 p-value 包装成泛化结论。

## 6. 最关键的假设为何被否定

历史诊断中有 21 道 `operand_selection_signal`。Gate C/D 最初就是希望通过
candidate ID 和 metadata 避免模型抄错数字。

最终：

```text
B1 修复 operand-selection failure：0 / 21
B2 修复 operand-selection failure：0 / 21
```

B1 的两道新修复分别来自：

- 1 道 composition/scale；
- 1 道 operation plan。

B2 只有 1 道 composition/scale 修复。

因此不能在简历写“typed planner 修复了 FinQA operand 错误”。正确说法是：

> 构建了 reference-only typed financial DSL，并通过真实开发集回顾实验发现
> contract mismatch 导致 coverage collapse；拒绝上线该版本，并建立了可复现
> 的失败基线和后续校准计划。

## 7. 问题主要出在哪一层

100 道题中，36 道在 deterministic intent 阶段就被拒绝，根本没有调用 B1/B2
模型。其余 64 道才进入模型。

### 问题一：intent 词法覆盖太窄

`extract_financial_question_intent` 只识别有限关键词，例如：

```text
total/sum/combined -> ADD
difference/how much more -> SUB
average -> AVERAGE
ratio/what percent -> RATIO
percent change/growth rate -> PERCENT_CHANGE
```

真实 FinQA 问法远比这个丰富，所以 36% 的题在模型前就被拒绝。

### 问题二：一个 operation_intent 无法表达真实程序

Validator 要求最后一步 operation 与 intent 完全相同：

```python
if output_step.operation != intent.operation_intent:
    raise unsupported_operation
```

但自然语言中的“百分比”“变化量”“占比”可能对应多步程序。一个粗粒度标签无法
稳定描述 operation sequence，造成 17 个 B1 `unsupported_operation`。

### 问题三：metric 兼容规则把合法组合也拒绝

ADD/SUB/AVERAGE/PERCENT_CHANGE 会要求 operand 的 metric/entity 相容。但一些题
本来就要相加不同表格行，文本候选的 metric 又经常为空。因此出现：

```text
metric_mismatch 7
additional ambiguous_intent 13
```

### 问题四：单位类型系统不够完整

当前类型只有有限 currency/ratio/count/shares 和 scale。真实财务表格还存在：

- 单位写在跨列/跨页 header；
- cell 中只有数字；
- count 与 currency 的隐含组合；
- ratio、percent、basis point 的转换；
- 不同 metric 的乘除组合。

过严会 `unit_mismatch`，过松又可能让错误计算通过。因此不能简单删除单位检查。

### 问题五：多候选无法修复共同的错误契约

B2 的 64 道模型调用题中：

```text
SELECTED         11
NO_VALID_PROGRAM 52
AMBIGUOUS         1
```

如果三个程序都面对同一个错误 intent 和同一套不兼容 validator，增加候选数量只会
产生三个一起失败的变体，还带来 14.58 倍平均延迟。

## 8. 评测代码自身发现了什么 bug

### bug 1：new_refusal_count 命名错误

private v1 把 `REFUSED + PROTOCOL_ERROR` 都算进 `new_refusal_count`。这会让读者误以为
都是安全拒答。

修复后 public v2 分为：

```text
new_non_answer_count
new_refusal_count
new_protocol_error_count
```

B1 分别是 90、36、54；B2 分别是 88、88、0。

### bug 2：B1 失败路径少记 compiler calls

原 `TypedPlannerProtocolError` 只带 attempt count 和 last reason，没有带已经发生的
compiler calls。sealed v1 无法准确恢复这个数字，所以 public v2 直接省略 compiler
和 generated-program 总数，并写明 measurement limitation。

未来代码已经让异常保存 `compiler_calls`。这里没有估算或伪造历史数字。

## 9. 如何验证 GitHub 上的公开证据

运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_finqa_typed_retrospective_public `
  --evidence docs\external_datasets\evidence\finqa_typed_retrospective_dev_v1_public_v2.json `
  --protocol docs\external_datasets\evidence\finqa_typed_retrospective_protocol_v1.json
```

Verifier 会：

1. 严格解析 public schema；
2. 重算 protocol SHA-256；
3. 检查 coverage、状态计数、transition 和 delta 算术；
4. 从 Git 历史提交 `9180b7e...` 读取 11 个源码 blob；
5. 对照冻结协议逐个重算源码 SHA-256；
6. 输出 private manifest/details digest，但不需要公开私有逐题数据。

## 10. 下一步不能直接进 Gate F

Gate F 应该使用新的独立样本。当前版本明显有害，直接消耗新 holdout 没有价值。
下一步应是 `Gate E2: Typed Contract Calibration`，仍只使用已披露 dev：

1. 建立不含题目正文的 failure matrix；
2. 扩展 intent schema，使其能表达多步 composition，而不是只有一个 operation；
3. 改进 table header、row metric、entity、unit 和 scale 的 provenance；
4. 区分“metadata 未知”和“已证明不兼容”；
5. 保留 literal、admission、provenance、sign、divide-by-zero 安全规则；
6. 先只校准 B1，coverage 和正确率达标后才重新考虑 B2；
7. 必须出现 operand failure 的正向修复，同时把 correct-to-wrong 控制在门槛内；
8. 通过后才能冻结 Gate F 的新独立确认协议。

## 11. 面试可能追问

### 问：结果这么差，这一步是不是失败了？

答：算法版本失败了，但工程阶段成功完成了。实验在结果出现前冻结了样本、模型、
源码、比较臂和指标；运行可恢复、结果不可变、公开投影不泄漏，并且发现方案有害后
明确拒绝采用。比只展示成功样例更能说明我具备评测驱动和上线门禁意识。

### 问：为什么不直接放宽 validator？

答：因为已作答子集也只有约 55% 准确。放宽规则可能提升 coverage，但没有证据会
提升正确率，还会削弱 provenance/unit 安全边界。应逐类修复数据契约并做回归，而
不是删除所有检查。

### 问：这是模型不行还是规则不行？

答：现有证据首先指向系统规则和表示。36 题在模型调用前就被 intent 拒绝；其余失败
大量来自 host validator。模型也有责任，因为通过 validator 的 9/11 道答案仍只有
5/6 道正确。结论是两者都有问题，但不能把 5%-6% 总准确率简单归因于模型参数量。

### 问：为何保留这段负面结果？

答：它防止团队把“单元测试全绿”误当成“真实效果提升”，也为下一轮校准提供固定红色
基线。公开结果明确 `COMPLETE_REJECTED`，不会进入简历的效果提升数字，但可以作为
评测体系、失败归因和发布决策的工程案例。
