# FinQA 有界 Plan Review 成对实验协议

## 1. 实验问题

FinQA dev 失败诊断显示，当前主要问题不是 Calculator 算错，而是 planner
选择了错误的年份、类别、基准值、运算顺序或尺度。本实验只回答一个问题：

> 在不改变问题、证据、检索结果和 Calculator 的前提下，再进行一次受限的
> 算式审查，能否带来可归因且值得额外成本的净收益？

这不是 LLM judge。reviewer 不判断自然语言答案“看起来好不好”，而是重新提交
一个受限算式和引用，最终正确性仍由确定性 FinQA scorer 判定。

## 2. 冻结输入与隔离变量

实验读取以下两个已经发布且可验证的不可变 source run：

- `finqa-v2-diagnostic-dev-v1-oracle`
- `finqa-v2-diagnostic-dev-v1-hybrid`

两臂必须使用相同的固定 100 题 dev 样本。脚本会验证：

1. source manifest、details 和 summary 的 SHA-256；
2. FinQA revision、dev split SHA-256 和 selected case IDs SHA-256；
3. source run 必须是 `split=dev` 和 `answer_strategy=program`；
4. 每题的 evidence ID 和顺序必须与 baseline 完全一致；
5. 工作树必须干净，并记录 reviewer 代码 Git SHA 和模型 digest。

脚本显式拒绝 test source run。已揭示的固定 test 不得用于 reviewer prompt
选择、阈值调整或重复试验。

## 3. Reviewer 能做什么

reviewer 接收：

- 原问题；
- 与 baseline 相同且通过 retrieved-content Guard 的证据；
- baseline 算式、Calculator 结果和引用。

它检查 requested quantity、年份、期间、类别、old/base、operand label、
argument order、符号和尺度。输出只能包含：

```json
{
  "expression": "(numeric arithmetic using + - * /)",
  "cited_candidate_ids": ["evidence-01"]
}
```

真实 evidence ID 会先映射为临时 ID。表达式由 AST/Decimal Calculator 执行；
reviewer 不能输出可执行代码、变量、函数、证据 ID 或自然语言最终答案。

## 4. 失败和回退语义

状态只有四种：

| 状态 | 含义 |
| --- | --- |
| `kept` | reviewer 原样保留 baseline 算式和引用 |
| `revised` | reviewer 修改算式或引用，且新表达式通过 Calculator |
| `fallback_protocol_error` | 两次 JSON/Calculator 协议尝试均失败，原样回退到已验证 baseline |
| `not_applicable_baseline_error` | baseline 本身没有合法算式；不调用 reviewer，并原样保留该题 |

只有结构化输出或 Calculator 合同错误允许回退。Ollama 不可用、网络错误、
source artifact 损坏、证据顺序漂移和模型身份不明确都会让整批失败，不能被记成
“回退成功”。

## 5. 成对指标

除原有 strict、presentation tolerance、citation 和 grounded 指标外，必须报告：

- `wrong_to_correct`：review 真正修正的题数；
- `correct_to_wrong`：review 造成的退化题数；
- `correct_to_correct` / `wrong_to_wrong`；
- discordant case 数和 two-sided exact McNemar p-value；
- kept、revised、fallback、not-applicable 数量；
- 新增 generation/calculator 调用；
- review mean/p95 延迟和端到端调用/延迟倍数。

只看 reviewed accuracy 会隐藏退化和成本，因此不能作为采用依据。

## 6. 预先冻结的采用门槛

本轮 dev 结果只有同时满足以下条件，才能成为“候选默认策略”：

1. `wrong_to_correct > correct_to_wrong` 且 strict delta 为正；
2. grounded strict 不退化；
3. `fallback_protocol_error / eligible <= 5%`；
4. exact McNemar `p <= 0.05`；
5. 调用数和延迟完整披露，并由业务延迟预算另行接受。

不满足任一条件时，不把 reviewer 接入默认生产路径。负结果仍保留为有效工程
证据，用于说明为什么“再调用一次 LLM”不自动等于 Agent 能力提升。

## 7. v1 结果和 v2 修复假设

v1 同模型全题 review 未达到采用门槛：

| Arm | Baseline strict | Reviewed strict | wrong→correct | correct→wrong | Mean latency multiplier |
| --- | ---: | ---: | ---: | ---: | ---: |
| Oracle | 63% | 62% | 0 | 1 | 2.08x |
| Hybrid | 59% | 55% | 1 | 5 | 2.08x |

Oracle exact McNemar p-value 为 `1.0`，Hybrid 为 `0.21875`。两臂协议回退均为
0，但“协议稳定”不等于“质量有效”。v1 结论是 `REJECT`，不得接入默认链路。

逐题私有诊断发现，Oracle 唯一退化题和 Hybrid 的两道退化题被 reviewer
错误地把原始比例乘以 100。原因是 planner prompt 已明确规定 FinQA scorer
接收 raw ratio，而 v1 review prompt 只笼统要求检查 scale，没有复述这一合同。

v2 只做两个预注册修复：

1. 明确百分比答案必须产生 raw ratio，禁止为了显示百分数乘以 100；
2. baseline 已通过 planner/Calculator 合同，无法指出无歧义错误时必须 KEEP。

v2 使用同一 100 题只能判断已知开发失败是否被修复，属于 tuning observation，
不能作为独立泛化证据。即使 v2 在该集合上通过数值门槛，仍需新的未用于提示词
修改的 dev validation cohort 才能考虑采用。

## 8. 实现位置

- 核心 reviewer、成对 schema、统计和不可变 artifact：
  `app/external_datasets/finqa_review.py`
- 真实运行入口：`scripts/eval_finqa_review.py`
- 回退、传输失败、状态转移和篡改检测测试：
  `tests/external_datasets/test_finqa_review.py`

运行产物只写入 `.private/external_datasets/finqa/review_runs`。公开仓库后续仅发布
聚合指标、hash、代码版本和边界声明，不发布问题、答案、证据、case ID 或逐题算式。
