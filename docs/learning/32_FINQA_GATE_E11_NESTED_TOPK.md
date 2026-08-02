# 32. FinQA Gate E11：怎样让一次模型提升既真实，又不被调参污染

## 1. 这一步最终得到了什么

E11 是一个 descriptor 排序器，不是大语言模型，也不是最终答题模型。它先在
FinQA train 做严格的 nested company CV，再获得一次内部 40 题验证资格。

```text
train outer OOF：84.8894% -> 86.0881%  (+1.1987pp)
internal roles： 84.21%   -> 86.84%    (+2.63pp)
internal complete cases：28/37 -> 30/37
internal role changes：64 保持、0 退化、2 修复、10 都错
```

它通过了协议门禁，但仍没有上线。原因是这里测的是“正确 descriptor/候选是否
进入 Top-K”，不是最终回答正确率；内部真正发生差异的角色也只有两个。

## 2. descriptor 是什么

原始证据里有很多数值候选，但不能把数值、候选 ID 和 provenance 全部发给一个
自由模型排序。项目先把一组同类候选投影成安全 descriptor，例如：

```text
metric: net revenue
row_header: net revenue
column_header: 2019
local_context_hint: net revenue in 2019
source_kind: table_cell
candidate_count: 1
```

descriptor 不含实际金额。模型先为每个 semantic role 选最多四个 descriptor，
host 再通过私有映射找到真实数值候选并进行第二阶段 rerank。

所以 `Descriptor Recall@4` 的问题是：

> 每个操作数角色真正需要的数值，是否至少被一个 Top-4 descriptor 覆盖？

## 3. E10 为什么差一点，E11 改了什么

E10 把每个正 descriptor 与最多八个 E8 高分负 descriptor 配对。这比 E9 的
独立二分类更贴近排序，但仍有许多训练对不会改变 Recall@4。

例如 E8 排序：

```text
1  wrong-A
2  wrong-B
3  wrong-C
4  wrong-D       <- Top-4 截止线
5  correct-X
6  wrong-E
```

真正有价值的是让 `correct-X` 超过 Top-4 中至少一个 wrong。`correct-X` 是否比
第 20 名 wrong 高，对 Recall@4 没有直接影响。

E11 的 `fit_topk_weighted_ridge_v1()` 只构造两类边界 pair。

### 漏检 pair

如果 Top-4 没有正例，选择 E8 排名最高的正例，与 Top-4 中最多四个负例比较。
模型学习把正例推过截止线。

### 保序 pair

如果 Top-4 恰好只有一个正例，它是当前命中的唯一保障。把它与截止线下最近的
负例配对，降低 learned residual 把唯一正例挤出去的概率。

如果 Top-4 已有两个正例，一次正负交换仍会保留一个正例，所以这个 group 不为
单次 swap surrogate 生成训练对。

## 4. 权重为什么按 role 归一化

某个 role 可能有四个边界负例，另一个只有一个。如果每个 pair 权重都等于 1，
第一个 role 会贡献四倍损失，只因为候选更多。

E11 先给整个 role 一个总权重，再平均分给 pairs：

```python
pair_weight = group_weight / len(opponents)
```

漏检 group 总权重固定 1。保序 group 的总权重是候选配置中的 0.25 或 1。这样
配置选择可以控制“积极修复”和“谨慎保序”的平衡，而不是让 descriptor 数量偶然
决定权重。

## 5. 为什么是 18 个配置

E11 在协议冻结时写死三个维度：

```text
最大 E8 分数调整      2 / 4 / 8
L2 正则               1 / 10 / 100
保序权重              0.25 / 1
总数                  3 * 3 * 2 = 18
```

`max_adjustment` 越大，模型越可能跨过 E8 的分数间隔，也越可能造成回退。`L2`
越大，系数越保守。`preservation_weight` 越大，训练越重视已有唯一 Top-4 正例。

这些值在正式 outer 结果前冻结。看到结果后没有临时加入第 19 个配置。

## 6. 普通 CV 为什么还不够

假设对 18 个配置都做五折 CV，然后挑最高的，并直接把这个最高分报告为结果。
即使所有配置真实水平一样，也可能有一个因为抽样波动碰巧最高。这叫 selection
bias，类似反复考试后只展示最高一次。

E11 使用 nested CV。以 outer fold 0 为例：

```text
outer fold 0：完全锁住，不参与配置选择

fold 1/2/3 -> train，fold 4 -> inner validation
fold 1/2/4 -> train，fold 3 -> inner validation
fold 1/3/4 -> train，fold 2 -> inner validation
fold 2/3/4 -> train，fold 1 -> inner validation

对 18 个配置汇总以上 inner 结果
选一个配置
用 fold 1/2/3/4 重新训练
只在 outer fold 0 测一次
```

然后把 outer 1、2、3、4 分别锁住重复。每家公司始终完整属于一个 fold，不能
把同一家公司的年报模板泄漏到训练和验证两边。

## 7. 配置是怎样确定的

`nested_company_cross_validate_v1()` 的 inner 选择顺序是：

1. challenger 命中数更多的优先；
2. 命中数相同，regressed 更少的优先；
3. 仍相同，使用协议里提前冻结的安全顺序。

五个 outer round 分别选择：

```text
adj08-l2-001-p025
adj08-l2-100-p025
adj08-l2-010-p100
adj08-l2-100-p025
adj08-l2-010-p025
```

`adj08-l2-100-p025` 出现两次，其他各一次，所以按“出现次数降序，再按安全顺序”
成为最终 artifact 配置。最终 artifact 在全部 train role 上重新拟合。

## 8. outer 结果怎样理解

五个 outer fold 的增量分别是：

```text
+0.4230 / +2.2298 / +1.6625 / +1.0888 / +0.5942 pp
```

全部为正，合计从 84.8894% 到 86.0881%，提升 1.1987pp，通过冻结的 1pp 门槛。
5,923 个 role 中：

```text
retained     5000  E8 对，E11 也对
regressed      28  E8 对，E11 错
gained         99  E8 错，E11 对
missed both   796  两者都错
```

净改善是 `99 - 28 = 71` 个 role。只报“+1.20pp”会隐藏 28 个回退，所以项目同时
保存 transition counts。

## 9. internal 40 为什么更重要

E9、E10、E11 的设计都看过同一 FinQA train。即使 E11 用 nested CV，研究者仍
可能通过多轮架构选择逐渐适应 train。因此 outer CV 被明确标记为 train-
development，不是最终独立确认。

内部 40 题此前从未用于 E9-E11 调参。协议只允许 outer 全门禁通过后读取一次。
审计器先验证：

- 私有 split 文件 SHA；
- 旧 retrospective details SHA；
- 40 个 case ID 的集合 SHA；
- 每题十条 selected unit 的整体 SHA；
- E11 protocol、CV、artifact 和实现文件 SHA。

任何一项变化都会在模型比较前停止。

## 10. 内部执行事故说明了什么

第一次命令在第一个 case 停止，错误是 strict semantic skeleton 不允许一个 step
重复使用同一 reference。异常发生在 E8/E11 selector 运行前，而旧 E8 helper
的 `try` 从 catalog 构建才开始，所以没有捕获 oracle 构建错误。

修复不是放宽 `SemanticProgramSkeletonV2`。正确做法是：

```text
共同 oracle 构建失败
  -> 两个 arm 都标记 FALLBACK_ROUTED
  -> 保存 capability boundary 原因

selector 之后失败
  -> 仍然是 arm error，不能伪装成 fallback
```

失败命令没有写 artifact、private details 或 public result，事故 JSON 明确记录。
修复后的完整运行仍是模型质量的 ordinal 1。

## 11. 为什么内部通过仍不能上线

37 个 typed case 有 76 个 role。E11 修复 2 个、回退 0 个。对 discordant pair
做 exact McNemar 检验，双侧 `p=0.5`。样本太小，不能排除这两个修复来自波动。

此外：

- 3/40 case 仍无法进入 typed contract；
- 10/76 role 两个系统都没找对；
- 没有运行最终 LLM planner 和答案执行准确率；
- outer train-development 中确实有 28 个回退；
- frozen test 尚未运行。

所以协议只允许进入 shadow-only：后台同时算 E8/E11，但用户答案仍由原路径决定。

## 12. 面试回答模板

> 我先发现 pointwise ranker 在 train CV 提升、真实开发集回退，于是把训练证据改成
> 不注入 gold 的 retrieval-realistic Top-10，并把 learned score 限制为 E8 的
> bounded residual。E10 五折都改善但只 +0.9455pp，低于预注册 1pp 门槛，所以
> 我没有改阈值。E11 进一步用 Top-4 swap-aware weighted pairs，并用 nested
> company CV 把超参选择与外层评价分开，outer 提升 +1.1987pp。它随后在一次性
> 内部 40 题上得到 2 gain / 0 regression，Recall@4 +2.63pp，但 McNemar p=0.5。
> 因此我只批准 shadow 集成，不宣称答案准确率或上线收益，并保留 frozen test。

这个回答的价值在于：既讲模型改进，也讲数据泄漏、评测预算、负结果、事故修复
和发布门禁。

## 13. 下一步 E12 做什么

E12 不继续用内部 40 题调模型。它要证明工程接入是否安全：

- 同一请求后台计算 E8 和 E11；
- E11 不改变当前答案、工具调用或引用；
- 只记录不含问题、数值、候选 ID 和 provenance 的聚合差异；
- artifact 缺失、SHA 错误、超时或异常时立即回到 E8；
- 有 circuit breaker 和可验证的 shadow-disabled 默认值；
- 不访问 frozen test。
