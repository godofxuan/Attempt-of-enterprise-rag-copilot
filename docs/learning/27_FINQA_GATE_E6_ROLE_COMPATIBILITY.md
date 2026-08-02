# 27. Gate E6：为什么“数字都找到了”仍然会选错

## 1. 三层问题

金融 RAG 的一道题至少经过：

1. **Source pool**：哪些文档数字进入安全候选池。
2. **Role compatibility**：某个计算角色能看到哪些候选。
3. **Planner binding**：模型最终把哪个候选绑定给哪个角色。

E3 主要修第 1 层，E5 暴露第 3 层，E6 专门测第 2 层。

如果正确数字在 source pool 中，却不在角色 Top-8 中，planner 再聪明也选
不到。反过来，Top-8 含正确数字也不代表模型一定选对。

## 2. 指标怎么读

假设 `old_value` 的正确候选是 100：

```text
Top-4 = [120, 95, 80, 100]
```

该角色 recall@4 为 1。如果 100 排第 6，则 recall@4 为 0、recall@8 为 1。

全体 `role recall@8` 是：

```text
Top-8 含正确候选的角色数 / 所有证据角色数
```

`complete case@8` 更严格：一道题有 5 个角色，只要 1 个没进 Top-8，整题
就是 0，所以它通常低于 role recall。

## 3. 代码在哪里

### 3.1 受控 Decimal 程序

`app/external_datasets/finqa_controlled_program.py` 定义：

- `ControlledConstantRef`：只能取冻结枚举；
- `ControlledProgramStep`：最多 5 步；
- `ControlledTypedProgram`：严格 DSL；
- `compile_and_execute_controlled_program()`：校验并执行。

三类参数分别解析为：

```text
CandidateRef          -> source-bound candidate state
ControlledConstantRef -> host enum，不产生 citation
StepRef               -> 前一步 Decimal state
```

候选继续经过 `finqa_typed_contract_v23._validated_candidates_v23()`，所以篡改
candidate ID、值或 provenance 会被拒绝。

### 3.2 v2 角色矩阵

`build_role_candidate_compatibility_matrix_v2()` 位于
`app/external_datasets/finqa_role_compatibility_v2.py`：

1. 校验问题、候选数和证据数预算。
2. 拒绝非 operand 或未准入候选。
3. 校验 semantic skeleton。
4. 对每个 role 做硬过滤。
5. 做确定性 lexical/period 排序。
6. 每个 role 截到 8 个。
7. 校验合计不超过 32 个不同 candidate ID。
8. 对矩阵计算 SHA-256。

硬过滤只处理确定错误：已知周期冲突、除数为 0、非 operand、未经 Guard
准入。未知 metadata 不会被误删。

## 4. 为什么不能直接改旧文件

E3 清单同时哈希输出和候选抽取源码。给旧
`finqa_typed_program.py` 加常量类型后，候选输出没变，但源码 SHA 变了，
历史证据不能复算。

正确修复是：

```text
旧模块：保持字节不变
新模块：承载新 DSL 和版本号
```

面试回答：

> 我们把源码也视为实验 provenance。一次功能修改破坏了旧 manifest 的源码
> 哈希，因此没有重写 manifest，而是恢复旧模块、创建版本化扩展层并跑完整
> 回归。

## 5. `const_7` 为什么重要

不能把数据集字段名当业务语义。

额度从 5B 增到 7B 的题里，`const_5/const_7` 是文档事实。若当 host
constant，40% 可能算对，但引用是缺失或错误的。

离线 oracle 因此检查值能否从 gold evidence 重建。能重建就保持 evidence
role；不能重建且在枚举内才是 host constant。运行时不使用 gold。

## 6. v1-v4 分别发生了什么

### v1：调用边界错误

source corpus 含 operand、year、scale 等数字，矩阵只接受 operand，调用方却
传了全部 corpus。58 题全部前置失败。修复是在调用边界显式筛选：

```python
candidates = tuple(
    candidate
    for candidate in corpus.candidates
    if candidate.role == "operand"
)
```

矩阵没有被放宽。

### v2：第一份有效结果

源池召回 100%，recall@8 83.74%。完整源池后按角色截断有效，但还不够。

### v3：失败消融

加入通用局部窗口和多样性惩罚后，recall@8 降到 77.24%。工程上正确的动作
是撤销、记录，不是反复调参直到开发集好看。

### v4：权威失败结果

恢复保守排序，只保留两项有反例支持的修复：

- “weighted average price increased”不再误判为 table average；
- “2013 compared to 2012”的新旧年份方向被规范化。

recall@8 回到 83.74%，route accuracy 达到 100%，门禁仍失败。

## 7. v3 为什么是架构修复

五个角色都写成 `component / none` 时，排序器收到五个相同查询。继续调权重
无法补回 schema 已丢掉的年份和业务对象。

`finqa_semantic_program_v3.py` 增加：

```text
role_query
expected_period
```

`finqa_role_compatibility_v3.py` 用角色自己的查询排名，并在 period 未被抽取器
结构化时，用表头/证据文本中的年份做软匹配。已知 period 冲突仍然硬拒绝。

角色查询 schema 拒绝：

- `num-...` candidate ID；
- `table_3` / `text_2` evidence ID；
- `step-01`；
- `const_100`；
- JSON 片段。

模型负责表达语义，host 负责候选权限、解析和执行。

## 8. 99.19% 能不能写成项目准确率

不能。

可以说：

> 离线 gold-descriptor upper bound 的 role recall@8 为 99.19%，证明角色查询
> 合同足以消除候选层的信息瓶颈。

不可以说：

> Agentic RAG 准确率是 99.19%。

上界的 role query 来自 gold evidence descriptor，不是模型从问题生成；也
没有测最终答案。

## 9. 面试追问

### 为什么不用 LLM 直接选数字？

LLM 可以生成 role query 和 binding，但候选必须来自 Guard 准入池，响应必须
匹配 per-role enum，最终计算必须由 Decimal 编译器执行。Prompt 不是权限
边界。

### Top-8 为什么不直接扩大？

扩大候选可提高 recall，却增加模型混淆、token、延迟和攻击暴露。E6 同时
冻结 recall、edge reduction、每角色上限和 unique-ID 上限。

### 下一步最重要的实验？

冻结真实 planner，让它只看问题生成 v3 role contract。配对报告 schema
validity、candidate recall、最终 strict/grounded accuracy、对 B0 的回归、
延迟和模型调用数。上界通过后才值得花这次模型成本。
