# FinQA Gate E5：为什么“多步规划 + 语义角色 + 动态示例”仍然只有 21.67%

## 1. 先说结论：有一点提升，但远远不够

这轮实验完整跑完了，不是程序崩溃，也不是 Ollama 卡住。最终决策是：

`CALIBRATION_REJECTED`

最好的方案是 `B4_ROLE_DYNAMIC_DEMOS`：

```text
问题和证据
  -> 从 train 检索 3 个“只有结构、没有答案”的示例
  -> LLM 先生成 operation skeleton 和 semantic roles
  -> LLM 再把 role 绑定到候选数字
  -> 主机 validator 检查
  -> Decimal 执行
```

它把严格正确率从 v2.3 的 `20.00%` 提到 `21.67%`，grounded 正确率从
`18.33%` 提到 `20.00%`。60 题里只多对了 1 题，所以不能在简历上写成
“显著提升”。

正确说法是：

> 动态结构示例明显改善了小模型生成合法程序的能力，但没有实质解决
> operation 和 operand 的语义选择问题；预注册门禁自动拒绝了该版本。

## 2. 四个实验臂分别是什么

| 实验臂 | 模型做什么 | 严格正确率 | 覆盖率 | 协议错误 |
| --- | --- | ---: | ---: | ---: |
| B1 v2.3 stored | 单步模板 + 候选 ID，复用 E4 | 20.00% | 73.33% | 16 |
| B2 direct | 一次生成最多 3 步完整程序 | 1.67% | 8.33% | 55 |
| B3 roles | 先生成角色骨架，再绑定候选 | 0.00% | 3.33% | 58 |
| B4 demos | B3 + 3 个 train-only 结构示例 | 21.67% | 73.33% | 16 |

这里的“覆盖率”不是 retrieval recall，而是：

```text
回答成功的题数 / 60
44 / 60 = 73.33%
```

严格正确率是最终 `Decimal` 结果严格正确的题数：

```text
13 / 60 = 21.67%
```

grounded 正确率还要求引用证据满足 grounding：

```text
12 / 60 = 20.00%
```

## 3. 为什么 B2 和 B3 反而更差

### 3.1 B2 把太多自由度一次性交给 8B 模型

B2 要模型一次返回：

```json
{
  "steps": [
    {
      "step_id": "step-01",
      "operation": "SUB",
      "arguments": [
        {"candidate_id": "num-..."},
        {"candidate_id": "num-..."}
      ]
    },
    {
      "step_id": "step-02",
      "operation": "DIV",
      "arguments": [
        {"step_id": "step-01"},
        {"candidate_id": "num-..."}
      ]
    }
  ],
  "output_step_id": "step-02"
}
```

模型要同时处理 JSON、步骤图、操作符、参数顺序、候选 ID、单位、指标和期间。
最终 60 题里有：

- 42 个 `invalid_program_schema`；
- 11 个 `unit_mismatch`；
- 2 个 `metric_mismatch`；
- 只有 5 题生成了可执行回答。

这说明“支持多步”只扩大了表达能力，却同时扩大了搜索空间和出错空间。

### 3.2 B3 的分解方向合理，但没有结构示例时模型不会稳定遵守协议

B3 把任务拆成两次生成：

```text
问题 -> value-free skeleton
skeleton + candidates -> role bindings
```

理论上比 B2 更清楚，但 qwen3:8b 在没有示例时仍然发生：

- 28 个 skeleton schema 错误；
- 29 个 binding schema 错误；
- 1 个 unit mismatch；
- 58/60 协议错误；
- 平均延迟 17.58 秒，p95 29.58 秒。

分解不是免费的。两阶段各允许最多两次尝试，最差情况下会产生更多模型调用。
B3 一共用了 240 次 generation call，v2.3 只有 80 次。

## 4. B4 为什么能把协议错误从 58 降到 16

`app/external_datasets/finqa_semantic_demos.py` 从官方 FinQA train 中构造
value-free 示例。

原始 train program 可能是：

```text
subtract(120, 100), divide(#0, 100)
```

进入 prompt 的不是这些数字，而是类似：

```json
{
  "question_template": "What was the percentage change from <NUM> to <NUM>?",
  "skeleton": {
    "roles": [
      {"role_id": "role-01", "semantic_role": "new_value", "period_role": "end"},
      {"role_id": "role-02", "semantic_role": "old_value", "period_role": "start"}
    ],
    "steps": [
      {
        "step_id": "step-01",
        "operation": "SUB",
        "arguments": [{"role_id": "role-01"}, {"role_id": "role-02"}]
      },
      {
        "step_id": "step-02",
        "operation": "DIV",
        "arguments": [{"step_id": "step-01"}, {"role_id": "role-02"}]
      }
    ],
    "output_step_id": "step-02"
  }
}
```

模型从示例中学“输出形状”，不能复制训练题答案，因为 payload 不包含：

- 数值 operand；
- answer；
- evidence text；
- candidate ID；
- document ID；
- 当前 calibration 的任何内容。

冻结 train 文件共有 6,251 条源记录，其中 5,704 条能转换为当前最多 3 步、
最多 6 个 role 的结构示例。检索算法是确定性的 IDF token overlap，相同问题和
相同索引一定得到相同 3 个示例。

## 5. 为什么 B4 合法率提高，正确率却几乎不变

B4 回答了 44 题，但只答对 13 题：

```text
44 - 13 = 31 个 answered-but-wrong
```

它的“回答后条件正确率”是：

```text
13 / 44 = 29.55%
```

v2.3 是：

```text
12 / 44 = 27.27%
```

结构示例告诉模型 JSON、role、step 和多步引用应该长什么样，但没有充分告诉模型：

- 哪一个 revenue 是问题要求的 revenue；
- 哪个年份是 start，哪个年份是 end；
- numerator 和 denominator 谁在前；
- 同一个数字出现在多个表格位置时应该选哪个；
- ratio、percent change、difference 的业务含义有什么区别。

所以本轮把瓶颈进一步缩小为：

`ROLE_TO_CANDIDATE_BINDING_AND_PROGRAM_SEMANTICS`

## 6. 代码具体改在哪里

### 6.1 `finqa_semantic_program.py`

职责：定义模型允许表达的程序语言。

它检查：

1. role 必须从 `role-01` 连续编号；
2. step 必须从 `step-01` 连续编号；
3. 最后一步必须是 output；
4. step 只能引用前面的 step，不能向未来引用；
5. 每个声明的 role 必须真正进入程序；
6. `SUB/DIV/RATIO/PERCENT_CHANGE` 等必须正好两个参数；
7. `ADD/AVERAGE` 允许 2 到 6 个参数；
8. role binding 必须完整覆盖且 candidate 在 allowlist 中。

这相当于一个很小的金融计算 DSL 类型系统。

### 6.2 `finqa_semantic_demos.py`

职责：安全加载 train，并生成不泄漏答案的结构示例。

关键点：

- train 文件必须匹配固定 SHA-256；
- 最大读取 128 MiB；
- JSON 拒绝 duplicate key；
- demo index 拒绝和整个 dev split 的 case ID 重叠；
- question 中的数字替换为 `<NUM>`；
- program 的 operand 只变成 semantic role；
- 每个 demo payload 和整个索引都有 SHA-256。

### 6.3 `finqa_semantic_planner.py`

职责：构造 prompt、JSON Schema、解析响应、有限重试和调用 v2.3 compiler。

`plan_direct()`：

```text
question + candidates + evidence
  -> 一次生成完整 1-3 步程序
  -> host parse
  -> v2.3 compile/execute
```

`plan_decomposed()`：

```text
question + optional demos
  -> skeleton
  -> question + skeleton + candidates
  -> bindings
  -> compile
  -> Decimal execute
```

模型没有执行代码的权限，也不能把任意数字送进 Calculator。

### 6.4 `finqa_semantic_runtime.py`

职责：每题只做一次公共输入处理，然后执行三臂。

```text
E4 selected evidence
  -> evidence closure
  -> RetrievedContentGuard
  -> numeric candidate extraction
  -> <=24 shortlist
  -> B2 / B3 / B4 按冻结顺序执行
  -> strict + grounded evaluation
```

它记录 shortlist、Guard、arm order、demo hash、调用数、延迟、失败阶段和程序 hash。

### 6.5 `finqa_semantic_calibration_run.py`

职责：汇总和执行门禁。

每个候选臂同时与两个基线比较：

```text
progress baseline = v2.3
shadow baseline   = B0
```

先要求相对 v2.3 有足够进步，再要求不能远差于 B0。全部通过的臂才进入选择；
没有合格臂时 `selected_arm = null`。verifier 会从 60 条 details 重新计算，
不相信 manifest 里手写的百分比。

### 6.6 `eval_finqa_semantic_planning.py`

职责：正式实验入口。

模型调用前先核对 protocol、E4、dev/train、case-ID、模型、demo index 和实现文件
哈希。每做完一题写一个 append-only hash-chained checkpoint。最终三件套先写
staging，验证通过后原子激活，再 seal checkpoint。

## 7. 中间遇到的两个真实工程问题

### 7.1 官方 train 不能直接复用严格的完整 FinQA loader

官方 train 中有一条 `gold_inds` 使用 `text_-1`。项目主 `FinQACase` 契约只允许
`text_N/table_N`，放宽它会污染所有历史数据边界。

解决方法是保持主 loader 不变，为 train demo 建立只解析
`id/question/program` 的最小 loader，同时保留完整文件 hash、strict JSON、
duplicate-key 和 ID 唯一性检查。

### 7.2 修改旧共享文件导致 3 个 frozen-source 测试失败

最初为了支持 train，我改了 `finqa.py` 和 `prepare_finqa.py`。完整
external-dataset 测试出现 3 个失败，因为历史协议记录了它们的精确 SHA-256。

错误做法是更新历史 hash。实际修复是恢复两个历史文件的原始字节，把 train
功能全部移进新模块。最终 external suite `260 passed`，正式运行前全仓
`2773 passed / 29 skipped`，历史证据没有被重写。

## 8. 13 项门禁为什么拒绝 B4

B4 通过了 correct-to-wrong、平均延迟倍率、p95 延迟、demo isolation 和
fail-closed suite。

B4 没通过：

- coverage：`73.33% < 75%`；
- strict delta vs v2.3：`+1.67pp < +10pp`；
- grounded delta vs v2.3：`+1.67pp < +8pp`；
- wrong-to-correct：`3 < 6`；
- protocol error rate：`26.67% > 15%`；
- strict delta vs B0：`-30pp < -5pp`；
- grounded delta vs B0：`-23.33pp < -5pp`；
- correct-to-wrong vs B0：`36.67% > 10%`。

所以不能因为“有一点提升”就进入 internal validation。

## 9. 下一轮 E6 应该改什么

下一轮不应该继续加更多示例，也不应该放松 validator。应该在 role 和 candidate
之间增加宿主可见的 compatibility layer：

```text
semantic role
  + required metric/entity/period/unit/scale/sign/table coordinates
  -> deterministic compatibility matrix
  -> 每个 role 只暴露兼容候选
  -> LLM binding
  -> host ambiguity check/ranking
  -> typed compiler
```

建议消融：

```text
B4 stored dynamic demos
B5 demos + compatibility filter
B6 demos + compatibility filter + deterministic ranking
```

研究依据包括 [FinQA](https://aclanthology.org/2021.emnlp-main.300/) 的受限
program vocabulary、[TAT-QA](https://aclanthology.org/2021.acl-long.254/)
的 evidence tagging + symbolic aggregation、Candidate Expressions Semantic
Parsing 的类型/候选约束，以及
[APOLLO](https://aclanthology.org/2024.lrec-main.122/) 的 number-aware
negative sampling。它们提供设计方向，不是可直接横比的分数。

## 10. 面试官可能怎么问

### 问：为什么用了多步规划，准确率反而下降？

答：

> 表达能力和可学习性不是一回事。直接多步臂同时要求 8B 模型满足 JSON、图结构、
> 运算符、参数方向和候选绑定，55/60 变成协议错误。动态结构示例可以恢复合法率，
> 但 correctness 仍受语义绑定限制。

### 问：动态 few-shot 有效果吗？

答：

> 对结构有效，对端到端正确率效果很小。相对无示例 role arm，coverage 从 3.33%
> 到 73.33%，协议错误从 58 降到 16；但相对 v2.3，strict 只提升 1.67pp。
> 所以结论只能是改善 contract adherence。

### 问：怎么防止 few-shot 泄漏答案？

答：

> demo 只来自固定 hash 的 train；整个 dev case-ID 集被禁止进入索引；问题数字替换
> 为 `<NUM>`；gold operand 变成 role；payload 不含 answer、数值、证据、
> candidate/document ID；每个 payload 和索引都记录 hash。

### 问：为什么不直接让 LLM 自己算？

答：

> LLM 只负责有限语义决策。候选必须来自 Guard 放行证据，数值由 provenance span
> 重建，程序由 host validator 编译，最后由 Decimal 执行。这样可以审计并拒绝
> 越权数值，但必须同时衡量 coverage 和 regression。

### 问：负结果放简历有价值吗？

答：

> 不能把 21.67% 写成好效果，但可以写预注册协议、三臂消融、train/dev 隔离、
> Latin-square 顺序、hash-chained checkpoint、原子发布、public/private 双验证和
> 自动拒绝退化方案。质量数字应使用项目已冻结的 FinQA test baseline
> `44% strict / 40% grounded`，并明确它属于另一条 expression-planning 路线。

## 11. 证据在哪里

- 冻结协议：
  `docs/external_datasets/evidence/finqa_semantic_planning_calibration_protocol_v1.json`
- 公开结果：
  `docs/external_datasets/evidence/finqa_semantic_planning_calibration_public_v1.json`
- 工程记录：
  `docs/external_datasets/finqa_semantic_planning_gate_e5.md`
- 私有逐题结果：
  `.private/external_datasets/finqa/semantic_planning_calibration_runs/finqa-semantic-planning-calibration-v1`

```powershell
.\.venv\Scripts\python.exe `
  -m scripts.verify_finqa_semantic_planning_public --public-only

.\.venv\Scripts\python.exe `
  -m scripts.verify_finqa_semantic_planning_public
```

