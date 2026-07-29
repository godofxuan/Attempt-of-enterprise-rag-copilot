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

## 12. Plan Review、候选仲裁与零重叠验证结果

第一版让同一个 Qwen3 8B 全题自审，Hybrid strict 从 `59%` 降到 `55%`：
只修正 1 题，却改错 5 题。逐题诊断发现 reviewer 漏掉 planner 已有的 raw-ratio
合同，甚至把正确比例乘以 100。v2 补齐比例合同，并规定“无法指出无歧义错误就
KEEP”，Hybrid 回到 `59%`，但没有新增正确题，说明同模型反思缺少新增信息。

异构 Qwen3-Coder 30B proposal 在 100 题 tuning 上达到 `61%`，但仍有 5 修正 /
3 退化。随后加入匿名 A/B 仲裁：

1. 30B 只能提出 proposal；
2. 只有 proposal 改变的题才调用 8B adjudicator；
3. baseline/proposal 来源隐藏，A/B 位置由 case ID hash 确定；
4. adjudicator 只能二选一，不能生成第三个算式；
5. 协议失败回退 baseline，传输失败仍中断整批。

该策略在 tuning 上达到 strict `59% -> 63%`、4 修正 / 0 退化，但 exact McNemar
为 `0.125`。随后在任何模型调用前冻结一批与 tuning 零重叠的 50 题 dev：

| Stage | Strict | Grounded strict | wrong→correct | correct→wrong |
| --- | ---: | ---: | ---: | ---: |
| Hybrid baseline | 44% | 32% | - | - |
| 30B proposal | 48% | 36% | 3 | 1 |
| 8B adjudicated | 50% | 38% | 3 | 0 |

质量方向得到复现，但 final exact McNemar 为 `0.25`，未达到预冻结 `0.05`。
同时 Ollama 从 0.32.4 自动升级到 0.32.5 后，30B 在 CUDA v12/v13 Flash
Attention warm-up 均退出；Vulkan workaround 可运行，但使本次端到端平均延迟
达到 baseline 的 `7.84x`。因此 plan review/adjudication 仍不进入默认链路。

机器可读协议和内容无关证据：

- [validation protocol](evidence/finqa_plan_review_validation_protocol_v1.json)
- [review/adjudication results](evidence/finqa_plan_review_results_v1.json)

收口验证为 FinQA focused `63 passed`、全仓
`2592 passed / 30 skipped / 3 warnings`、public audit
`978 candidates / 0 findings`；`compileall`、`pip check` 和
`git diff --check` 通过。以上回归门禁证明代码和公开边界未被本阶段改坏，不替代
模型质量门槛。

## 13. Resumable Eval 与 Runtime-only Uncertainty Trigger

### 13.1 为什么先修可恢复性

30B validation 因 Ollama/CUDA 故障中断时，原脚本只在整批结束后发布
`details.jsonl`，已经完成的模型调用无法恢复。`e59d9e4` 新增
`app/evaluation/resumable_checkpoint.py` 并接入 review/adjudication：

1. checkpoint contract 绑定 source manifest/details、样本 hash、模型 digest、
   prompt、代码 SHA、runtime backend、timeout 和 attempt budget；
2. 每完成一题就在私有 D 盘目录提交一个原子记录；
3. 记录按 ordinal/case ID 排序，并保存 row hash 和前序文件 hash；
4. 恢复时 contract 漂移、缺号、额外记录或篡改全部 fail closed；
5. 最终不可变 run 发布后，checkpoint seal 绑定 final manifest/details hash；
6. 发布后、seal 前崩溃时，脚本验证已存在 final run 后补 seal，不重复调用模型。

checkpoint 不进入 Git，最终公开证据仍来自原有 immutable publisher。它改变的是
故障恢复语义，不改变历史模型分数。

### 13.2 Trigger 只能读取什么

`08a3f62` 新增 `app/external_datasets/finqa_uncertainty.py`。v1 score 只使用请求
当时已有信号：

- 表达式 operand 是否出现在引用证据或固定常量白名单；
- planner 是否重试、Guard 是否隔离内容；
- 是否多步运算、引用多段证据；
- 引用证据中的数值和年份候选是否多；
- ratio/percentage/change 类问题是否包含除法。

权重为 ungrounded `3`、retry `2`、quarantine `3`，其余弱信号各 `1`，总分
`>=2` 才触发。回归测试会修改 gold program、`exe_ans`、gold unit、strict、
evidence recall 和 citation recall，并要求 signal 完全不变。

### 13.3 Tuning 与 validation

在 100 题 tuning 上，trigger 只选 `67%`，保持 full strategy strict/grounded
`63%/55%` 和 `4/0` 修正/退化；generation 增量从 `124` 降至 `84`
（`32.26%`），Calculator 增量减少 `31.76%`。

随后在读取逐题 validation signal 前冻结算法、源码 hash、源 artifact 和门槛。
50 题零重叠 cohort 的结果：

| 指标 | Full strategy | Trigger gated |
| --- | ---: | ---: |
| Triggered | 50 | 31 |
| Strict | 50% | 50% |
| Grounded strict | 38% | 38% |
| wrong→correct / correct→wrong | 3 / 0 | 3 / 0 |
| Incremental generation calls | 65 | 42 |
| Incremental Calculator calls | 80 | 53 |

generation/Calculator 精确反事实减少 `35.38%/33.75%`。历史逐题增量耗时求和减少
`28.06%`，但它不是实际 selective wall-clock，而且源 run 混合 CUDA/Vulkan，
所以不能发布生产延迟声明。underlying paired McNemar 仍为 `p=0.25`，默认路径
继续关闭。

公开证据：

- [uncertainty freeze](evidence/finqa_uncertainty_validation_protocol_v1.json)
- [uncertainty results](evidence/finqa_uncertainty_results_v1.json)
- [validation protocol erratum](evidence/finqa_plan_review_validation_protocol_erratum_v1.json)

最后一份 erratum 记录早期公开 freeze 中 `split_sha256` 的手工抄写错误。实际
代码常量和三个 runtime manifest 始终绑定正确 hash；原冻结文件没有被静默改写，
质量结果不受影响。

本阶段收口为 FinQA/checkpoint focused `73 passed`、全仓
`2602 passed / 30 skipped / 3 warnings`、public audit
`986 candidates / 0 findings`；compile、依赖和 diff 检查通过。

## 14. 新 cohort 上的真实 Selective Execution

### 14.1 这一步补了什么证据缺口

第 13 节只能回答“如果按 trigger 跳过历史调用，理论上能省多少”，不能回答：

1. trigger 是否真的在模型调用前执行；
2. 未触发题是否真的没有进入 30B production review；
3. selective 路径的真实 wall-clock 是多少；
4. 新样本上是否仍能改善质量；
5. 长运行中断后是否真的能恢复，而不只是单元测试声称可以。

因此新增独立入口 `scripts/eval_finqa_selective.py`，而不是改写历史 evaluator。
每题的数据流是：

```text
Hybrid retrieval + 8B planner baseline
              |
              v
runtime-only uncertainty trigger
       |                    |
       | no                 | yes
       v                    v
production baseline    30B bounded review
                            |
                      changed proposal?
                       |           |
                       | no        | yes
                       v           v
                  reviewed_kept  anonymous 8B adjudication
                                      |
                                      v
                              production final answer

production final 固定以后，未触发题才允许进入 shadow full arm。
shadow 只测“如果全量 review 会怎样”，不能改写 production final。
```

这种顺序非常重要。如果先跑 full arm，再根据结果决定是否触发，router 就可能
偷看 30B 输出；如果 shadow 可以改写 final，它就不再是成本对照。

### 14.2 代码落点和不变量

- `app/external_datasets/finqa_selective.py`
  定义逐题结果、聚合指标、路由状态、不可变发布和验证。Pydantic 校验器会重新
  计算 trigger、policy、route 和 latency partition；序列化字段不能自称合法。
- `scripts/eval_finqa_selective.py`
  编排 retrieval、baseline、trigger、review、adjudication、shadow 和 checkpoint。
  它只接受 frozen protocol 指定的数据、模型 digest、源码 hash 和 runtime options。
- `scripts/freeze_finqa_selective_protocol.py`
  在模型调用前排除旧 tuning/validation case，确定性选取新 100 题，并冻结门槛。
- `tests/external_datasets/test_finqa_selective.py`
  覆盖 trigger 前置、shadow 隔离、route 约束、样本排除、断点恢复、发布与篡改拒绝。
- `tests/external_datasets/test_finqa_public_evidence.py`
  重新计算公开指标、核对 protocol/incident hash，并递归拒绝 case ID、问题、答案、
  表达式或逐题 evidence 泄漏。

逐题 checkpoint contract 绑定 protocol SHA、源数据 hash、样本 hash、三个模型
digest、runtime backend、30B options 和代码 revision。任一项改变都不能续跑旧
checkpoint。

### 14.3 为什么 v1 protocol 被 supersede

v1 在任何 selected case 执行前冻结，但默认 30B CUDA 请求在 Ollama `0.32.5`
上退出。最小请求也能复现，因此先排除了 FinQA prompt、JSON schema 和长上下文。
受控探针得到：

| 配置 | 结果 |
| --- | --- |
| Flash Attention auto，默认 GPU layers | CUDA shared-object initialization 失败 |
| Flash Attention off，默认 GPU layers | 失败移动到 `MUL_MAT` warm-up |
| `num_gpu=10` | 失败 |
| `num_gpu=1/2/5` | 成功 |
| `num_gpu=7` | 失败 |

这说明关闭 Flash Attention 只能改变失败点，不是根因修复。项目选保守的
`num_gpu=5`，并固定 `num_ctx=4096`、`num_batch=512`。正式运行时 `ollama ps`
观测 30B 为 `89% CPU / 11% GPU`，所以这是 CUDA partial offload，不是 full GPU。

项目没有修改 v1 后假装它从未出错，而是：

1. 保留 v1 原文件和 hash；
2. 发布 `finqa_selective_execution_protocol_v1_incident.json`，证明已执行题数、
   checkpoint 行数和已观察模型输出均为 0；
3. v2 保留完全相同的 100 题样本，只增加稳定 runtime options 和 incident 绑定；
4. 运行前提交 v2，使源码、样本和运行参数都先于模型结果固定。

### 14.4 正式结果

数据为 FinQA dev 新 100 题；已排除之前 100 题 tuning 和 50 题 validation，
重叠数为 0。该 cohort 现在已经揭示，后续不能继续在它上面调 trigger 后声称独立
验证。

| 指标 | Baseline | Selective | Shadow full |
| --- | ---: | ---: | ---: |
| Strict | 53% | 55% | 56% |
| Grounded strict | 38% | 40% | 40% |
| wrong→correct | - | 3 | 4 |
| correct→wrong | - | 1 | 1 |
| Mean latency | 2.36s | 9.02s | 11.85s |
| p95 latency | 3.84s | 15.24s | - |

selective 触发 `63/100`；96 题 baseline 可解析，因此 eligible trigger rate 仍按
协议报告为 `63%`。路由结果为 baseline `37`、reviewed-kept `41`、adjudicated
`22`。相对全量策略，增量 generation calls 从 `125` 降到 `85`，减少 `32.00%`；
增量 Calculator calls 从 `154` 降到 `107`，减少 `30.52%`。

同一次实验中，selective 总时间为 `902.33s`，隔离 shadow-full 对照为
`1184.61s`，前者低 `23.83%`。这是本机部分 CUDA offload 下的观测值，只能用于
该冻结运行的内部比较，不能称生产 SLO 或 full-GPU benchmark。

### 14.5 真实断点恢复证据

第一次正式进程在第 27 题前以 `0x40010004` 退出，没有 Python traceback。
原因未知，因此记录为 external interruption，不推断为模型、用户或系统错误。
退出前已经原子提交 `26` 条 checkpoint。相同命令重启后输出：

```text
resuming after 26/100 completed cases
```

runner 校验 contract 和 26 条 hash chain 后从第 27 题继续，最终得到 100 条记录，
发布 immutable manifest/details/summary 并写入 seal。这个证据支持“完成项不
重跑的故障恢复”声明，不支持跨机器容灾或分布式 exactly-once。

### 14.6 为什么仍然 NOT ADOPTED

方向上有提升：strict 和 grounded strict 都增加 2 个百分点，并降低约三成额外
工具调用。但预冻结 gate 是合取关系，不是“多数通过就上线”：

- `correct_to_wrong <= 0`：实际为 1，失败；
- beneficial capture：只捕获 full strategy 4 个修正中的 3 个；
- exact McNemar `p<=0.05`：实际 `p=0.625`，失败；
- full-GPU latency evidence：没有，失败。

聚合错误分析显示，漏掉的 beneficial case 是 literal-only、zero-operation
baseline 没有执行必要的加法调整；退化 case 是 reviewer 反转了时间方向的百分比
变化，adjudicator 又接受了它。它们是下一版设计候选，不是允许在本 cohort 上
事后改规则再报分的理由。

下一阶段只能在以前已经揭示的开发 cohort 上研发 literal-only risk signal、
temporal operand alignment 和 planner protocol reliability，然后冻结另一批未见
样本或另一公开金融 QA 数据集做确认。FinQA test 不得重跑调参。

公开证据：

- [selective v2 frozen protocol](evidence/finqa_selective_execution_protocol_v2.json)
- [selective aggregate results](evidence/finqa_selective_execution_results_v1.json)
- [superseded v1 incident](evidence/finqa_selective_execution_protocol_v1_incident.json)
