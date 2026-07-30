# FinQA Gate E2：Typed Contract Calibration 逐步讲解

## 1. 这一阶段到底解决什么问题

Gate E 已经证明，原来的 typed route 不能上线：

```text
B0 自由算式严格正确率       57%
B1 单 typed program         5%
B2 多 typed program         6%
```

这不是说 typed program 这个方向一定错误，而是说 v1 合约同时存在两个问题：

1. 合约过严，把“元数据不知道”当成“元数据已经确定冲突”；
2. 给 8B 模型的任务过重，要求它同时选择数字、选择操作、生成 DAG、维护 step
   编号和引用顺序。

Gate E2 的目标不是在 test 上继续刷分，而是在已经披露的 dev 上回答：

> 哪些失败来自错误的合约，哪些失败来自模型，哪些失败来自上游证据根本不够？

## 2. 为什么先切成 60/40

Gate E 的 100 条 dev 已经被看过，所以它们不再是独立 holdout。Gate E2 用固定算法
把它们切成：

```text
calibration          60
internal validation  40
```

分层字段是：

- Gate E diagnostic category；
- B1-v1 的最终 outcome/failure reason。

同一个 stratum 内用：

```text
SHA256(seed + "\0" + case_id)
```

排序，再用 largest-remainder 算法保证验证集恰好 40 条。公开文件只放 cohort
SHA-256，不放 ID。

这一步的重要性是：可以反复使用 60 条找问题，但不能一边看 40 条结果一边改规则。
本轮最终没有运行 40 条，说明采用门禁确实发挥了作用。

对应代码：

- `app/external_datasets/finqa_typed_calibration.py`
- `scripts/freeze_finqa_typed_calibration.py`
- `tests/external_datasets/test_finqa_typed_calibration.py`

## 3. v1 为什么会错误拒绝

### 3.1 unknown 和 conflict 混在一起

v1 中，如果问题要求 2020 年，而候选没有 period：

```python
if period is None:
    raise ambiguous_intent
```

但“候选没标 period”不等于“它一定不是 2020”。v2 改为：

```python
if period is not None and period not in allowed_periods:
    raise temporal_mismatch
```

也就是：

- unknown：允许继续，但不增加可信度；
- known conflict：继续 fail closed。

metric、entity 和 unit 使用了同一原则。

### 3.2 ADD 不一定要求同一个 metric

求总资产时，现金、应收账款和存货的 row metric 不同，但它们可以合法相加。
v1 的 `_same_metadata` 会把它们拒绝成 `metric_mismatch`。

v2 增加：

```python
allow_additive_metric_composition: bool
```

只有 intent 明确允许组合时，`ADD` 才能把多个已知 metric 合成输出；`SUB`、
`AVERAGE`、`PERCENT_CHANGE` 仍要求已知 metric 不冲突。

### 3.3 百分比变化不是只看最终操作名

下面两种程序语义等价：

```text
PERCENT_CHANGE(new, old)
(new - old) / old
```

v1 只要求最终 operation 等于 intent operation，因此第二种会被拒绝。v2 不只是
允许 `SUB -> DIV`，还检查：

1. DIV 的 numerator 必须引用 SUB；
2. DIV 的 denominator 必须与 SUB 的第二个 old operand 完全相同；
3. 如果两个年份都已知，new/old 顺序不能反。

所以 `(new-old)/unrelated` 不会因为形状相似而通过。

对应代码：

- `app/external_datasets/finqa_typed_contract_v2.py`
- `tests/external_datasets/test_finqa_typed_contract_v2.py`

## 4. 第一轮 v2 做了什么

第一轮 v2 保留完整 typed DAG，让模型返回 1–8 个步骤。

结果：

```text
coverage                   41.67%
strict accuracy            13.33%
grounded accuracy          13.33%
mean / p95 latency         15.57s / 26.50s
correct -> wrong vs B0     25
wrong -> correct vs B0      2
prevented operand failures  1
```

相对 v1，coverage 和正确率都提高了，证明 unknown/conflict 的拆分不是无效改动。
但逐题程序显示，错误答案经常包含 8 个重复或互不相关的步骤。模型不仅在回答财务
问题，还被迫处理编译器前端工作。

## 5. 第二轮 v2.1 为什么失败

v2.1 假设：

> 候选少一些、图结构严一些，模型会更容易选对。

实现：

- 问题条件 candidate ranking；
- 候选最多 24 个；
- 已知错误年份在 prompt 前移除；
- 最多 5 步；
- 每一步必须能从最终 output 反向到达；
- 同一步不能重复同一个 operand；
- 不能重复同一 operation + arguments。

离线候选审计：

```text
平均候选数 25.65 -> 14.85
shortlist p95 24
只有 2/60 条出现 coarse operand recall 损失
```

但真实结果变差：

```text
coverage                   28.33%
strict accuracy             6.67%
mean / p95 latency          9.99s / 13.92s
invalid_program_schema     26
wrong -> correct vs B0      0
```

原因不是这些结构约束本身错误，而是 qwen3:8b 仍然要输出完整 DAG。限制越多，它越
容易在 step order、dead step 或重复引用上失败。

这是一条有价值的负实验：

> 缩短 prompt 能降低延迟，但不会自动提高语义正确率；把编译器职责留给 LLM，
> 再多 schema 约束也可能只是改变失败类型。

## 6. 第三轮 v2.2 的架构变化

v2.2 不再让模型生成程序图。模型只输出：

```json
{
  "template": "PERCENT_CHANGE",
  "operand_candidate_ids": ["num-a", "num-b"]
}
```

模型负责：

- 根据问题判断模板；
- 从 allowlist 选择有序 operands。

主机负责：

- 生成唯一 `step-01`；
- 把模板编译成 typed DSL；
- 校验 candidate ID、provenance 和 evidence admission；
- 校验 period/metric/entity/unit/sign；
- 校验 arity 和 divide-by-zero；
- 用 Decimal 执行。

这叫职责分离，而不是“少写一点 prompt”。

对应代码：

- `TypedProgramSketch`
- `typed_program_sketch_response_format_v2`
- `parse_typed_program_sketch_v2`
- `compile_typed_program_sketch_v2`
- `LocalFinQATypedProgramPlannerV2.plan_and_execute`

## 7. v2.2 的真实结果

同一 60 条、同一 evidence、同一 qwen3:8b digest：

```text
coverage                    81.67%
strict accuracy             26.67%
grounded accuracy           25.00%
mean latency                 2.19s
p95 latency                  3.38s
protocol errors             11/60
correct -> wrong vs B0      20
wrong -> correct vs B0       5
prevented operand failures   3
```

与 v1 比：

```text
coverage        +71.67 percentage points
strict accuracy +21.67 percentage points
mean latency    12.91s -> 2.19s
```

说明 host-compiled sketch 是三轮中真正有效的架构改进。

但不能只与差的 v1 比。与 B0 比：

```text
B0 strict accuracy    51.67%
v2.2 strict accuracy  26.67%
delta                -25.00 pp
```

而门禁要求不能低于 B0 超过 5 pp，因此 v2.2 仍被拒绝。

## 8. 为什么 coverage 81.67% 仍不够

coverage 只表示系统返回了答案，不表示答案正确。

v2.2：

```text
answered 49
correct  16
wrong    33
```

如果只汇报 coverage，会把 33 个错误答案隐藏掉。工业系统更关心：

- correct-to-wrong；
- grounded accuracy；
- protocol error；
- 上游 operand 是否存在。

## 9. 候选可用性诊断

公开审计使用一个保守的 coarse heuristic：

- gold Decimal 与 candidate normalized value 完全相同，或
- candidate 等于 `gold / 100`，用于识别百分比归一化。

结果：

```text
full-pool operand recall mean        60.00%
shortlist operand recall mean        58.89%
full-pool complete coverage          26/60
shortlist complete coverage          25/60
v2.2 wrong + gold missing            24
v2.2 wrong + all gold available       9
v2.2 non-answer + gold missing        7
```

这不是精确语义 recall，因为：

- `const_100` 可能是官方计算常量，不是 evidence 中的事实；
- 表头 “in millions” 可能没有传播到 cell；
- 同一个 Decimal 可能来自错误 metric；
- 也可能存在与 gold 不同但等价的计算。

但它足以表明：大量题在进入 planner 前已经缺少可执行 operand，继续改 planner
prompt 不可能解决这些题。

## 10. 为什么没有运行 internal validation 和 B2-v2

冻结门禁要求 v2.2 在内部验证前至少表现出可采用的希望。校准 shadow gate 中：

```text
coverage                         PASS
wrong -> correct count           PASS
prevented operand failure        PASS
latency mean / p95               PASS
execution delta vs B0            FAIL
grounded delta vs B0             FAIL
correct -> wrong rate            FAIL
protocol error rate              FAIL
```

因此：

```text
internal validation  NOT_RUN
B2-v2                NOT_RUN
Gate F               BLOCKED
frozen test          untouched
```

这不是“项目没做完”，而是评测系统阻止了一个不合格方案继续消耗 holdout。

## 11. 文件在哪里

冻结与失败矩阵：

- `app/external_datasets/finqa_typed_calibration.py`
- `scripts/freeze_finqa_typed_calibration.py`
- `docs/external_datasets/evidence/finqa_typed_contract_calibration_protocol_v1.json`
- `docs/external_datasets/evidence/finqa_typed_contract_failure_matrix_v1.json`

v2/v2.1/v2.2：

- `app/external_datasets/finqa_typed_contract_v2.py`
- `app/external_datasets/finqa_typed_planner_v2.py`
- `tests/external_datasets/test_finqa_typed_contract_v2.py`

真实运行与 checkpoint：

- `app/external_datasets/finqa_typed_calibration_run.py`
- `scripts/eval_finqa_typed_calibration_v2.py`
- `.private/external_datasets/finqa/typed_contract_calibration_runs/`
- `.private/external_datasets/finqa/checkpoints/typed_contract_calibration/`

公开证据：

- `app/external_datasets/finqa_typed_calibration_public.py`
- `scripts/publish_finqa_typed_calibration.py`
- `scripts/verify_finqa_typed_calibration_public.py`
- `docs/external_datasets/evidence/finqa_typed_contract_calibration_public_v1.json`

## 12. 运行和验证命令

```powershell
# 只检查来源和 hash，不调用模型
.\.venv\Scripts\python.exe -m scripts.eval_finqa_typed_calibration_v2 `
  --run-id example-calibration --cohort calibration --dry-run

# 重建聚合公开证据
.\.venv\Scripts\python.exe -m scripts.publish_finqa_typed_calibration

# 私有逐题重算 + 历史 Git source hash + raw-field audit
.\.venv\Scripts\python.exe -m scripts.verify_finqa_typed_calibration_public
```

## 13. 面试时应该怎么讲

### 问：为什么不用 LLM judge 判断程序对不对？

答：这一步的目标是计算正确性和合约安全。FinQA 有可执行 gold answer，因此主指标
用 Decimal 结果精确比较；provenance、unit、period 和引用合法性用确定性 validator。
LLM judge 更适合开放式答案质量，不应该替代可执行真值。

### 问：为什么 v2.2 比 v2.1 好？

答：v2.1 仍要求 8B 模型生成 DAG，schema 只是在限制 DAG。v2.2 缩小了模型责任，
只让它做语义选择，宿主做图构造和执行，因此结构错误归零、延迟下降，覆盖和正确率
都提高。

### 问：既然 v2.2 比 v1 好，为什么不采用？

答：采用标准必须与当前可用 baseline 比，而不是只和失败版本比。v2.2 比 B0 低
25 pp，并有 33.33% correct-to-wrong，远超 5% 门槛，所以只能记录为 best
calibration iteration，不能上线。

### 问：下一步是什么？

答：先提高 planner 输入的可执行性：

1. 保留 table-level scale/unit context；
2. 修复跨表头和百分比归一化；
3. 区分 evidence operand 与 host-controlled constants；
4. 量化 candidate complete coverage；
5. 完成后仍在 60 条 calibration 上复测；
6. 只有 B1 通过，才运行 40 条 internal validation 和 B2。

### 问：这个负结果有什么项目价值？

答：它证明项目不是技术堆叠。系统能冻结协议、保存失败、拒绝不合格方案、避免污染
holdout，并把瓶颈从“模型可能不行”定位到“程序生成职责过重”和“operand availability
不足”。这比只展示一个无法复现的高分更接近工业评测与变更管理。
