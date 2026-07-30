# FinQA Gate E4：为什么数字都找到了，答案反而只有 20%

## 1. 先把结果说清楚

这次不是代码异常，也不是 Ollama 卡住。60 道题全部执行并生成了封存结果，
但是冻结的质量门槛没有通过，所以系统主动给出：

`CALIBRATION_REJECTED`

三个实验臂使用同一批 60 道已公开为“开发校准”的题：

| 实验臂 | 它在做什么 | 严格正确率 | 有引用的严格正确率 | 覆盖率 |
| --- | --- | ---: | ---: | ---: |
| B0 | 模型自由生成表达式，主机执行 | 51.67% | 43.33% | 98.33% |
| v2.2 | 模型选单步模板和候选数字 | 26.67% | 25.00% | 81.67% |
| v2.3 | v2.2 + E3 新数字提取和证据闭包 | 20.00% | 18.33% | 73.33% |

所以不能说“v2.3 提升了正确率”。正确说法是：

> E3 修好了输入可用性，但 E4 证明输入改进没有自动转化为端到端正确率；
> 当前主要瓶颈已经从数字提取转移到语义规划。

## 2. 三种百分比不要混在一起

### 2.1 输入完整率 96.67%

`58/60` 的候选列表里，能机械匹配到 gold program 需要的所有数字。

它只回答：“正确数字有没有进入模型可选范围？”

它不回答：“模型知不知道应该选哪几个、先减还是先除？”

### 2.2 严格执行正确率 20.00%

`12/60` 的最终 Decimal 执行值与标准答案严格匹配。

这才是本次 typed v2.3 的核心答案质量。

### 2.3 Grounded execution 18.33%

`11/60` 不仅数值正确，而且引用证据满足项目的 grounded 条件。

它比严格正确率少一题，说明那一题虽然算对，但证据引用不完整或不满足
grounding 规则。

## 3. 为什么不能简单说“模型不行”

真实原因是模型、任务设计和契约边界共同造成的。

### 3.1 32 道题是“通过校验但语义选错”

v2.3 一共回答 44 题，其中只有 12 题正确：

`44 - 12 = 32`

主机验证器能证明：

- candidate ID 来自允许列表；
- 数字能从原文 span 重建；
- unit、period、sign 没有违反已知约束；
- 程序可以被 Decimal 安全执行。

但它无法仅靠确定性规则证明：

- “营业利润”是不是问题真正需要的分子；
- “2019”与“2018”谁应该在前；
- 问题是在问差值、比例还是变化率；
- 多个同值数字中哪一个具有正确业务语义。

这就是“结构合法”不等于“语义正确”。

### 3.2 16 道题被 fail-closed 拒绝

失败分布是：

| 原因 | 数量 | 含义 |
| --- | ---: | --- |
| metric_mismatch | 6 | 选中的数字属于冲突指标 |
| unsupported_operation | 4 | 所选运算不在该 intent 允许范围 |
| direction_mismatch | 2 | 新旧期间或分子分母方向冲突 |
| invalid_arity | 2 | 运算需要两个参数，但模型给错数量 |
| unit_mismatch | 2 | 金额、比例、数量等单位不兼容 |

这些拒绝降低了覆盖率，但这是安全属性，不应该为了让数字变好看而删除。
正确做法是改善规划器，让它更少产生违规计划。

### 3.3 当前 sketch 只能表达一个运算

60 题的 gold program 中：

- 单步 32 题；
- 多步 28 题。

v2.3 的 `compile_typed_program_sketch_v2()` 永远只生成一个 `step-01`。
它是 E2 为降低 JSON/schema 错误做的工程折中：模型只返回一个模板和若干
候选 ID，复杂 DSL 由主机编译。

优点是 v2.2 覆盖率从早期版本大幅提高；缺点是无法自然表达真正的多步程序。
`PERCENT_CHANGE` 可以把某些“先减后除”折叠成单个高级模板，但不能覆盖所有
多步组合。

### 3.4 正则 intent 过于粗糙

`extract_financial_question_intent_v2()` 主要用关键词正则判断
`ratio`、`percent_change`、`exact_add` 等 family。

本次按它分组：

- `percent_change`：15 题，4 题正确，11 题协议错误；
- `ratio`：20 题，7 题正确，13 题合法但错误；
- `exact_add`：4 题，0 题正确；
- `exact_subtract`：4 题，0 题正确；
- `exact_divide`：2 题，0 题正确；
- `unspecified`：12 题，1 题正确。

这说明正则既会限制错误运算，也会把模糊问题交给一个过宽的操作集合。
下一版需要显式的 operation skeleton 与 semantic role，而不是继续堆关键词。

## 4. 代码到底在哪里

### 4.1 运行入口

`scripts/eval_finqa_v23_calibration.py`

职责是加载冻结 protocol、核对 E2/E3 hash、确认模型 digest、恢复 checkpoint，
并按 60 个固定 case 执行。

### 4.2 每题数据流

`app/external_datasets/finqa_v23_runtime.py`

核心顺序：

```text
原始 FinQA case
  -> E3 bounded evidence closure
  -> RetrievedContentGuard
  -> v2 numeric candidates
  -> <=24 shortlist
  -> qwen3:8b planner
  -> host validator/compiler
  -> Decimal result
  -> strict/grounded evaluator
```

### 4.3 模型规划

`app/external_datasets/finqa_typed_planner_v23.py`

模型只返回：

```json
{
  "template": "PERCENT_CHANGE",
  "operand_candidate_ids": ["num-...", "num-..."]
}
```

模型不能直接写数字，防止它绕过证据；也不能直接执行代码。

### 4.4 主机验证和执行

`app/external_datasets/finqa_typed_contract_v23.py`

它重新从 `raw_text + provenance_span` 提取数字，核对 source-bound candidate ID，
检查证据是否已被 Guard 放行，再调用已有 v2.2 的单位、期间、方向和运算规则。

### 4.5 结果封存

`app/external_datasets/finqa_v23_calibration_run.py`

新增的 verifier 不再只核对文件 hash。它还会：

1. 从 60 行 details 重算三个 arm 的汇总；
2. 重算 v2.3-v2.2 和 v2.3-B0 的 paired transition；
3. 核对有序 case-ID hash；
4. 核对每个 gate 的 comparator；
5. 可选地用冻结 protocol 重算最终 decision。

这防止有人只改 `summary.json` 或 manifest 里的百分比。

### 4.6 公开证据

`app/external_datasets/finqa_v23_public.py`

`scripts/publish_finqa_v23_calibration.py`

`scripts/verify_finqa_v23_calibration_public.py`

公开 JSON 只保留聚合指标和 hash，不包含题目、答案、证据文本、case ID、候选
ID 或模型生成的程序。

## 5. 下一步怎么改

下一步不是直接换一个更大的模型重跑，也不是放松 validator。

Gate E5 应做三项可消融改进：

1. **多步 operation skeleton**：先输出最多 3 步的运算图，参数可以引用前一步；
2. **semantic role assignment**：先描述 numerator、denominator、old period、
   new period、component 等角色，再把角色绑定到 candidate；
3. **动态结构示例**：只从 train 中检索少量相似问题的 operation skeleton，
   不泄露当前 calibration 答案。

然后分别测：

```text
E4 v2.3
vs E5-A 多步 skeleton
vs E5-B skeleton + semantic role
vs E5-C skeleton + role + dynamic demos
```

只有同一冻结 cohort 上同时提高 strict、grounded、coverage，并控制
correct-to-wrong、protocol error 和延迟，才允许进入那 40 题 internal
validation。

## 6. 面试时怎么说

不要把 20% 包装成好结果。可以这样回答：

> 我们最初的自由表达式基线在同一 60 题开发校准集上是 51.67%。为了让
> 数字来源、单位和执行过程可审计，我做了 typed program 路线，但第一版
> 只有 26.67%。我没有上线它，而是逐层做失败归因。E3 把候选数字完整率
> 从 80% 提升到 96.67%，E4 重新成对评测后却只有 20%，说明主要瓶颈不是
> retrieval，而是 operation/operand semantic planning 和单步表达能力。
> 项目通过预注册门槛自动拒绝退化版本，保留逐题私有证据、公开聚合 hash
> 和可重算 verifier。下一轮只在开发集上做多步 skeleton、角色绑定和动态
> 示例的消融，内部验证集与 test 继续封存。

这个回答的价值不在“分数高”，而在于你能证明：

- 你知道 RAG 的检索正确不等于答案正确；
- 你能做 paired evaluation 和失败分层；
- 你不会为了简历数字污染 holdout；
- 你能让不合格方案自动停止发布；
- 你能从负结果产生下一轮可证伪实验。

## 7. 外部方法与我们的对应关系

- FinQA 官方系统把 retriever 与 program generator 分开，并公开纠正过
  table row 格式导致的标签泄漏：
  https://github.com/czyssrs/FinQA
- TAT-QA 先抽取表格/文本证据，再执行符号运算：
  https://aclanthology.org/2021.acl-long.254/
- Program of Thoughts 把精确计算交给外部解释器：
  https://arxiv.org/abs/2211.12588
- FINDER 用生成式证据检索和动态 in-context PoT 示例：
  https://aclanthology.org/2025.emnlp-main.1577/
- 结构感知表格检索显式保留 header-value 关系：
  https://arxiv.org/abs/2309.10506

这些工作给出的是设计方向，不是可以直接搬来比较的分数。论文通常使用完整
benchmark、更大模型、训练或不同提示设置；本项目的 60 题本地
`qwen3:8b` 开发校准结果不能与论文 leaderboard 直接横比。
