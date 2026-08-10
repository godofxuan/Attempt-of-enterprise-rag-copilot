# 多文档证据失败归因学习手册

## 1. Recall@5 为什么不等于多文档完整率

假设一题必须引用文档 A 和 B，Top-5 只找到 A：

```text
gold recall = 1 / 2 = 50%
all-gold complete = false
```

Recall 给“找到一部分”部分分；完整率只有“全部找到”才记 1。本次 20 题
在 Top-5 的平均 gold recall 是 48.33%，但全部 gold 都进入 Top-5 的只有
3/20。这两个数字并不矛盾。

对应代码是
`app/evaluation/wixqa_multidoc_attribution.py` 中的 `gold_coverage()` 和
`all_gold_recalled()`。

## 2. “命中至少一篇”和“命中全部文档”的区别

企业问题经常需要联合证据。例如“开通权限并完成账单设置”可能分别来自
权限文档和账单文档。只找到其中一篇，答案可能看起来合理，但并不完整。

因此多文档评测必须保留集合：

```text
G = {所有必需 gold 文档}
S = {当前阶段保留的文档}
complete = G subset-of S
```

不能只问 `G intersect S` 是否非空。

## 3. 为什么必须按 stage 定位 Agent 失败

最终 0/20 只告诉我们“结果失败”，没有告诉我们改哪里。如果直接加 query
rewrite、planner 或第二次搜索，可能修不到真正问题，还会增加延迟和风险。

本项目把路径拆成：

```text
Top-20 候选 -> Top-5 -> Controller -> ACL -> Guard -> Ledger
-> Response Builder -> Grounding -> Final
```

对每题找 gold 第一次不完整的位置。结果是 7 题在 Top-20 已缺失、10 题
在 Top-20 有但 Top-5 缺失、3 题到 Response Builder 才丢失。这样后续
实验才有因果依据。

## 4. Query Analyzer、Controller、Evidence Ledger 分别做什么

`RuleFirstQueryAnalyzer` 把问题变成 `intent`、`required_aspects`、过滤条件等
结构。本次得到 16 个 `answer` 和 4 个 `process_steps`，每题都只有一个
aspect。

`V2AgentController` 根据尚未尝试的 aspect 决定工具调用。它对每个 aspect
先搜索一次；Ledger 返回 `answer` 后就终止。本次 20 题都是一次 search，
没有 find/open，Controller 自身 20/20 返回 `answer/completed`。

`build_ledger()` 判断每个 required aspect 有没有 supporting evidence，并
计算：

```text
coverage = supported_aspect_count / required_aspect_count
```

它不是在计算 gold document recall。

## 5. Ledger coverage 为什么能和 benchmark completeness 不一致

本次每题只有一个 required aspect。只要任意检索结果支持这个 aspect：

```text
supported aspects = 1
required aspects = 1
ledger coverage = 1.0
```

但 benchmark 可能要求两篇或三篇指定文档。于是 17/20 出现：

```text
ledger coverage = 1.0
gold-document completeness < 1.0
```

这叫相对 benchmark 的 representation gap，不是说 Ledger 代码算错了。
它说明当前 contract 表达不了“一个 aspect 必须由多篇独立文档共同支持”。

## 6. 为什么要区分 pre-gate 和 post-gate

如果模型或 response builder 已经提出 A、B 两个引用，而 grounding gate
删除 B，那么根因在 gate。相反，如果 gate 前就只有 A，就不能怪 gate。

本次 pre/post source set 在 20 题中都没有减少。只有 1 题因
`negation_mismatch` 从 Controller 的 answered/completed 降为 partial，
但来源集合不变。因此 gate 不是 0/20 的主因。

## 7. Oracle 为什么不能当最终 benchmark

Gold Retrieval Oracle 直接把正确文档排在最前面，它使用了测试标签，现实
系统不知道 gold 是什么。它只能回答反事实问题：

> 如果检索已经完美，后面的 Guard/Ledger/response 路径还能否完成引用？

结果是 gold 20/20 通过 Guard，但最终仍 0/20，证明下游也有结构性阻塞。
这个 0/20 是诊断结果，不能写成线上系统质量。

## 8. 为什么这 20 题以后只能作为 DEV / CONSUMED

我们已经查看逐题失败位置，未来还会据此设计候选方案。如果再用同样 20 题
宣布最终提升，就相当于针对测试题调参。正确做法是：

1. 用这 20 题诊断和开发。
2. 冻结候选与参数。
3. 新建未看标签的 multi-document cohort。
4. 只在最后运行一次 blind validation。

## 9. 为什么不能看到失败就直接加 query rewrite

数据只支持“17 题在 retrieval Top-20/Top-5 首次丢失”，并没有证明 query
rewrite 是最小有效机制。可能的原因还有候选深度、ranking、多意图拆分、
语料标题表达或 chunk 表示。候选必须分别做 bounded ablation，比较质量、
延迟和额外工具调用，不能凭框架流行度选择。

更重要的是，即使 Gold Retrieval Oracle 完美注入，最终仍为 0/20，所以只
修 rewrite 也不会自动解决 response builder 的一证据上限。

## 10. 如何在面试中解释一次负实验

可以按“事实、定位、决策、边界”回答：

> 原始 60 题回顾评测中，Agent 与 control 的 Recall@5 都是 61.11%，多文档
> 引用完整率是 0/20。我没有立即堆 planner，而是给 20 题建立逐阶段集合
> 归因。结果显示 7 题在 Top-20 已缺 gold，10 题在 Top-5 选择阶段缺失，
> 另外 3 题检索完整但被 extractive builder 的每 aspect 一条证据限制丢失。
> Gold Retrieval Oracle 又证明，完美检索仍无法通过当前响应 contract 得到
> 完整引用。因此我把下一阶段定义成 retrieval 与 multi-evidence contract
> 的分开消融，并把这 20 题标记为 consumed，停止在同一测试集上追漂亮数字。

这个回答体现的是科学调试、证据纪律和上线决策，而不是把负结果包装成提升。

## 11. 这次新增代码如何工作

`app/evaluation/wixqa_multidoc_attribution.py` 定义严格 Pydantic schema、有限
first-loss enum、覆盖率计算、只读 Recording wrappers 和 aggregate 纯函数。

`scripts/diagnose_wixqa_multidoc_failure.py` 校验 source/protocol/index/model
哈希，运行当前路径与 Gold Retrieval Oracle，把问题文本留在 `.private`，
只公开 ID、hash、集合和计数。

`scripts/verify_wixqa_multidoc_attribution.py` 不信任 aggregate：它重新解析
20 行 schema、重算全部指标、核对 artifact hash，并拒绝公开 JSON 中的
question、answer、prompt 和 raw output 字段。

测试证明 Recording wrappers 不改变 answer、claim、citation、source、预算
和 security trace；另一个负向测试篡改 aggregate 后 verifier 必须报错。

