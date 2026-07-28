# FinQA 独立数值推理轨道

## 1. 为什么增加 FinQA

FinanceBench 当前主要回答“系统能否从完整财报集合中找到正确文档和正确 PDF
页”。它不能单独回答：

1. 正确证据已经给出时，本地模型能否完成多步财务计算；
2. 表格行和正文句子混合时，检索能否召回全部运算输入；
3. 最终数字正确时，模型引用的证据是否也是正确的；
4. `$1,200`、`1200`、`12%` 和 `0.12` 应该怎样可复现地评分。

FinQA 在真实财报的表格和文本上提供问题、支持事实、推理程序和执行结果。因此
本轨道补充 FinanceBench 的数值推理与证据引用评测，但不把 FinQA 的 evidence
unit recall 冒充 FinanceBench 的 PDF Page Recall。

## 2. 上游与许可边界

- 官方仓库：`https://github.com/czyssrs/FinQA`
- 固定 revision：`0f16e2867befa6840783e58be38c9efb9229d742`
- dev SHA-256：`a847fb7e...4deee51`
- test SHA-256：`831dbfb2...8a30dc`
- 官方项目网站声明数据集为 CC BY 4.0；仓库中的代码 LICENSE 为 MIT。

原始 JSON 只下载到 `.private/external_datasets/finqa`，不提交到 Git。公开仓库
只发布来源、revision、字节 hash、聚合指标、代码版本和私有 artifact hash。

## 3. 数据处理

`app/external_datasets/finqa.py` 完成：

1. 64 MiB 文件预算、UTF-8、重复 JSON key 和 Pydantic schema 校验；
2. 固定 revision 与 split SHA-256 校验；
3. 把 `pre_text + post_text` 按上游定义映射为 `text_0..n`；
4. 用上游修正后的 `table_row_to_text` 模板生成 `table_0..n`；
5. 验证每个 `gold_inds` ID 都存在，且文本只允许空白/标点空格差异；
6. 用 `SHA256(seed + case_id)` 做顺序无关的稳定抽样。

下载命令：

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.prepare_finqa --split dev
```

test 下载必须显式增加 `--execute-frozen-test-download`，并且只能在 test 协议
冻结后执行。

## 4. 评测分层

### Oracle evidence

只把 `gold_inds` 指向的证据交给模型。若这里答案错误，说明主要问题是数值推理、
输出协议或模型能力，不应归因于检索。

### Retrieved evidence

在每个样本的所有文本句和表格行中检索 Top-K：

- `bm25`：对英文 token 做 casefold，并使用适合小候选集的 BM25Plus；
- `dense`：本地 BGE-M3 batch embedding 与 cosine ranking；
- `hybrid`：BM25Plus 与 BGE-M3 的 RRF 融合。

若 oracle 正确而 hybrid 错误，继续分解为 evidence miss、排序不足或引用遗漏。

## 5. Agent 与 Calculator 边界

最终采用 `LocalFinQAProgramAnswerer`，而不是让模型直接写最终数字：

1. retrieved-content Guard 先扫描证据；
2. 真实 unit ID 映射成临时 `evidence-01..n`；
3. 模型只输出算术表达式和白名单引用，不输出可信最终答案；
4. 表达式只允许数字、括号和 `+ - * /`；
5. `app/agent/safe_calculator.py` 用 AST 白名单和 `Decimal` 执行，不使用
   `eval`；
6. Calculator 限制字符数、AST 节点、深度、数值范围和指数，并拒绝变量、
   函数、幂运算、下标、除零和非有限数；
7. 最多纠错一次，generation calls 和 calculator calls 分开计数；
8. 单题协议失败记 0 分并保留错误类型；网络、模型服务和数据损坏仍使整批失败。

dev 消融说明为什么使用简单表达式，而不是“为了 Agentic 而堆复杂 JSON”：

- direct answer：oracle strict `0%`，presentation tolerance `35%`；
- typed-step program：strict `15%`，但协议错误 `50%`；
- safe expression + Calculator：oracle strict `75%`，协议错误 `0%`。

这组数字只来自固定 20 题 dev pilot，用于选择协议，不是泛化结论。

## 6. 指标含义

| 指标 | 含义 |
| --- | --- |
| `answer_parse_rate` | 最终答案是否满足单值协议 |
| `execution_accuracy` | 归一化并四舍五入到 5 位后是否匹配官方 `exe_ans` |
| `presentation_tolerance_accuracy` | 保持符号一致，且绝对或相对误差不超过 0.5% |
| `evidence_recall` | 提供给模型的证据覆盖多少 gold units |
| `citation_precision` | 模型引用中有多少是 gold units |
| `citation_recall` | gold units 中有多少被模型引用 |
| `grounded_execution_accuracy` | 答案正确且 gold citation recall 为 100% |
| `generation_protocol_error_rate` | 两次输出仍无法解析或安全执行的题目比例 |
| `generation_calls` / `calculator_calls` | 模型与确定性工具的真实调用次数 |

数值评分把逗号、美元符号、会计负数括号和百分号规范化，并在 5 位小数上比较。
严格指标与展示容差指标同时保留，不能用容差覆盖严格失败。评分不使用 LLM
judge，也不从长文本中猜测“最像最终答案”的数字。

## 7. 不可变运行

每个私有 run 包含：

- `manifest.json`：Git SHA、dataset SHA、selected case IDs SHA、模型 digest、
  检索模式、Top-K、超时和重试；
- `details.jsonl`：逐题答案、证据、引用、延迟和分层指标；
- `summary.json`：聚合指标。

发布过程先写同盘 staging、复验后原子移动。run ID 不可覆盖；summary 必须能从
details 重新计算；任何文件被修改后 verifier 都会拒绝。

## 8. 冻结、incident 与 test 结果

冻结协议绑定 10 个关键源码 hash、Qwen3/BGE-M3 digest、temperature 0、
100 题稳定样本、oracle/hybrid 两臂、K=10 和评分规则。第一次 oracle 尝试在
抽样和模型调用前因单行表 schema 失败，没有生成 run artifact。该事件没有隐藏：

- [v1 superseded 协议](evidence/finqa_holdout_protocol_v1.json)
- [schema incident](evidence/finqa_holdout_schema_incident_v1.json)
- [v2 frozen 协议](evidence/finqa_holdout_protocol_v2.json)

修复只把 `table/table_ori` 从至少两行放宽到至少一行，保留矩形、宽度、
gold ID/text、字节 hash 和重复 key 校验。结构预检通过后重新冻结，参数、模型、
策略和评分未变化。

固定 100 题 test 样本结果：

| Arm | Strict execution | Presentation tolerance | Evidence recall | Grounded strict | Protocol error | Mean / p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Oracle gold evidence | 52% | 54% | 100% | 45% | 0% | 0.796s / 0.931s |
| Hybrid RRF, K=10 | 44% | 44% | 93.5% | 40% | 1% | 1.054s / 1.570s |

可审计的内容无关聚合证据见
[finqa_test_holdout_v1.json](evidence/finqa_test_holdout_v1.json)。原始 test、
逐题 details、问题、答案和证据文本仍只在 `.private`。

收口门禁：FinQA/Calculator focused `90 passed`；仓库全量
`2563 passed / 30 skipped / 3 warnings`；public audit
`964 candidates / 0 findings`。`0 findings` 只表示当前静态规则未命中。

## 9. 结果怎么解释

1. oracle strict `52%` 是给出 gold evidence 后的本地数值计划上限，不是检索分；
2. hybrid strict `44%` 是固定 K=10 的端到端观察值；
3. 两者相差 8 个百分点，而 hybrid evidence recall 为 `93.5%`，说明检索仍有
   损失，但更大的剩余瓶颈是选择正确数字和财务运算计划；
4. grounded strict 比 strict 更低，因为数字正确还不够，引用必须覆盖全部 gold；
5. dev oracle `75%` 到 test oracle `52%` 的 23 点下降说明 20 题 dev pilot
   明显乐观，不能用 dev 分数写成泛化能力。

可以声称的是“固定 100 题 FinQA test 样本上的本地观察结果”。不能声称完整
FinQA test accuracy、SOTA、跨模型泛化、生产财务可靠性或人工语义审核结论。

## 10. test 之后的 dev 错误诊断

test 结果揭示后不再用该 100 题调参。项目改用新的稳定 seed
`finqa-v2-diagnostic-dev-v1`，从 883 题 dev 中选 100 题做诊断。两臂使用同一
Qwen3/BGE-M3 digest、Calculator 协议和 K=10：

| Arm | Strict | Presentation | Evidence recall | Citation recall | Grounded strict | Mean / p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Oracle | 63% | 64% | 100% | 92.42% | 56% | 0.870s / 1.179s |
| Hybrid RRF | 59% | 61% | 91.98% | 82.07% | 52% | 1.036s / 1.328s |

这不是第二个 holdout，也不能用 63%/59% 覆盖上面的 test 52%/44%。它的用途是
定位下一步：

1. `app/external_datasets/finqa_diagnostics.py` 严格解析全部 `883/883` 条 dev
   gold program，并把模型表达式转成后序运算序列和 Decimal operand multiset；
2. `scripts/diagnose_finqa_run.py` 先校验 source run 的 manifest/artifact hash，
   只接受 `split=dev` 和 Calculator program 策略，显式拒绝 test；
3. 分类优先级为协议错误、正确且 grounded/引用不全、检索漏证据、不支持的
   gold operation、operand signal、operation-plan signal、composition/scale；
4. retrieval/protocol 是直接观察；operand/operation 是与 gold program 的机械
   比较信号，可能受等价代数改写影响，不能冒充确定的语义根因；
5. Oracle 的 37 个错误中有 20 个 operand signal、11 个 operation-plan signal、
   5 个 composition/scale signal 和 1 个当前 Calculator 不支持的 operation；
6. Hybrid 的 41 个错误中有 12 个 retrieval miss、21 个 operand signal，
   说明检索有损失，但完整证据下的选数仍是更大的工程目标。

标签质量审计也没有隐藏：全 dev 的人类展示 `answer` 有 `858/883` 可按单值协议
解析，其中 `97/858` 与官方 `exe_ans` 超出 0.5% 宽容一致性；本次 100 题为
`94` 个可解析、`3` 个不一致。主分仍严格绑定官方 `exe_ans`，展示 answer 只作为
数据质量信号，不能选择对模型更有利的标签。

可审计聚合证据见
[finqa_dev_diagnostic_v1.json](evidence/finqa_dev_diagnostic_v1.json)；
逐题问题、表达式、case ID 和诊断详情只在 `.private`。下一假设是对 dev 评估
有界 plan-review，但必须同时报告提升、正确题退化、额外模型调用和延迟，不能
默认“再调一次 LLM”一定更好。

本阶段收口：相关公开/诊断测试 `107 passed`，全仓库
`2578 passed / 30 skipped / 3 warnings`，public audit
`968 candidates / 0 findings`。

## 11. 有界 Plan Review 成对实验

下一阶段不重新生成 baseline，也不修改检索结果，而是对同一批 100 题 dev 的
不可变 planner 输出增加一次受限审查。运行前冻结的输入、回退语义、成对统计和
采用门槛见
[FinQA 有界 Plan Review 成对实验协议](finqa_plan_review_protocol.md)。

该实验明确拒绝 test source run。只有 `wrong_to_correct` 多于
`correct_to_wrong`、grounded strict 不退化、协议回退受控且 exact McNemar
达到预设证据门槛时，reviewer 才能成为候选默认策略；否则保留负结果，但不接入
默认链路。
