# 多文档候选实验学习与面试指南

## 1. 这一轮到底做了什么

上一轮归因已经知道：20 道多文档题中，17 道在检索 Top-5 之前就缺少必需文档，
另外 3 道虽然两份 gold 文档都到了 Agent 状态里，但最终回答只引用了一份。

所以这轮没有直接改线上 Agent，而是先做一个 2x2 对照实验：

```text
因素一：是否拆分查询
因素二：是否选择多份证据

A = 都不做，当前基线
B = 只拆查询
C = 只选择多证据
D = 两者都做
```

这样设计可以分别判断：是检索候选不够，还是回答阶段丢证据，还是两者都存在。

## 2. 代码从哪里开始看

第一站是 `app/evaluation/wixqa_multidoc_candidate.py`。

`decompose_query()` 做保守的规则拆分。它永远保留原问题，只识别少量明确连接词，
每个子句至少三个英文或数字 token，最多返回原问题加两个子句。这里没有调用 LLM，
也绝对不能看 gold、答案和文章标题。

`fuse_query_rankings()` 接收多条完整排名。每篇文档在第 r 名时得到：

```text
score += 1 / (rrf_k + r)
```

分数高的文档排前面。如果分数一样，再按最好名次、完整名次向量和文档 ID 决定顺序，
所以相同输入一定产生相同输出。

`select_preferred_admitted_document_ids()` 不直接读原始检索内容。它只能在
`admitted_document_ids` 中选择，也就是 ACL 和 retrieved-content Guard 之后仍允许进入
Agent 状态的文档。每个查询变体最多贡献一篇，去重后最多三篇。

`SelectiveExtractiveResponseBuilder` 从
`ControllerState.evidence_by_aspect` 读取已准入证据，重新排列并缩小证据集合，然后继续调用
原来的 `ExtractiveResponseBuilder` 和 citation verifier。最后还有断言：输出引用不能逃出
选择后的 admitted 集合。

## 3. 为什么候选代码放在 evaluation 目录

因为这个机制尚未证明有效。直接修改 `app/agent/runner_v2.py` 会让开发假设污染正式路径，
而且失败后很难证明默认行为真的没有变化。

现在的隔离方式是：

```text
生产路径：原 Runner + 原 Builder(max=1)
实验路径：原 Runner + evaluation-only Selective Builder
```

测试 `test_candidate_module_does_not_change_default_response_selection` 会实例化正常 Runner，
确认它仍只输出第一份证据。运行协议还检查八个受保护生产文件从候选起点到执行 SHA 都没有变化。

## 4. 为什么延迟不能直接用实际循环时间

四个臂会重复用到原问题排名。如果先跑 A，再跑 B，而 B 命中缓存，B 会看起来异常快。
这不是算法更快，只是实验顺序带来的缓存偏差。

因此脚本先为每个查询变体记录真实 BM25、BGE-M3 和 RRF 时间，再按每个臂实际需要的查询数
计算检索成本，最后加上该臂的 Agent 机制时间。A 平均一次 embedding，B/C/D 平均 1.8 次。

## 5. 四组数字怎么读

Combined 相比 Current：

```text
Citation completeness  0.00%  -> 0.00%
Citation recall        21.67% -> 24.17%
Citation precision     45.00% -> 39.17%
p95 latency            600.09 -> 1115.59 ms
```

召回提高 2.5 个百分点并不等于成功。多文档题要求所有必需文档都被引用，20 道题仍然没有
一道完整；同时精度下降、尾延迟接近 1.86 倍。因此门禁必须拒绝。

## 6. 为什么 Top-5 变了，召回却没变

8 道题触发了拆分，7 道题的 Top-5 顺序或成员发生变化，但新增文档并不是缺失的 gold。
这说明“排名发生变化”只是机制活动，不是质量收益。面试中不要用 changed cases 冒充 improved cases。

## 7. 为什么多引用了来源，完整率还是零

Combined 在 6 道题里输出了多来源，但总共引用 10 个 gold 和 18 个非 gold。也就是说，
它确实学会了“多拿几篇”，却没有学会“拿到共同回答问题所必需的那几篇”。

在 3 道 Top-5 已经包含全部 gold 的题里，所有 gold 也都进入 admitted evidence，但选择器仍只
选中一篇 gold。这证明第二个瓶颈不是 Guard，而是“查询变体排名不能表达证据角色”。

## 8. 这是不是模型不行

不能直接这么说。

本轮回答没有调用生成 LLM，所以 0% completeness 不能归因于 Qwen 或其他生成模型。
BGE-M3 参与了检索，检索确实是 17/20 的主要瓶颈；但候选还混合了 BM25、RRF、规则拆分、
Top-5 截断和证据选择。因此严谨说法是：当前整套候选机制没有改善多文档 gold 覆盖，
不能仅凭这个实验判定 embedding 模型本身不行。

## 9. 为什么失败结果仍有工程价值

工业项目不是每次都要得到漂亮数字，而是要控制错误决策：

1. 先冻结假设、参数和门槛。
2. 用配对实验隔离因素。
3. 记录质量和成本，而不只看召回。
4. 失败后停止调参，避免污染测试集。
5. 保留可重算 JSON、私有数据哈希和精确代码 SHA。
6. 不把失败候选接入默认服务。

这证明你具备 EvalOps、实验治理和发布控制能力，而不是只会调用模型 API。

## 10. 面试官可能追问什么

### 问：为什么不用 LLM 做 query decomposition？

答：第一步先验证更便宜、确定、可复现的下界机制。规则候选失败后，也不能在同一已消费 20 题上
继续换 LLM 调参。下一次若使用 LLM，必须先建立新的开发/验证/封存测试划分，固定模型、prompt、
temperature、最大查询数和一次重试预算，再做 OFF/ON 成对评测。

### 问：为什么不用 Top-20 全部交给模型？

答：Top-20 完整率比 Top-5 高，但更多上下文会增加噪声、成本和提示注入面。以前 cite-all Top-5
已经让 precision 从 44.44% 降到 18.52%。正确方向是验证一个 Top-20 到 Top-5 的覆盖感知选择器，
而不是把诊断上界直接当产品配置。

### 问：为什么 Guard quarantine 不是根因？

答：Combined 有一个 case 出现候选 quarantine，但 3 个检索完整 case 的全部 gold 都进入了
admitted evidence，`admission_loss_after_complete_retrieval_count=0`。零完整率发生在更早的检索缺失
和更后的选择缺失，不是 Guard 把完整证据集破坏了。

### 问：为什么不进入 validation？

答：预注册门要求 completeness 和 recall 至少各提升 15 个百分点，并至少修复 3 个配对 case。
实际是 0、2.5 和 0。运行 validation 只会继续消耗数据，不会改变候选已经不合格的事实。

### 问：这个结果能写进简历吗？

答：不能写成质量提升。可以在项目经历或面试中写成评测工程能力：构建 2x2 多文档消融、
用哈希和精确 SHA 固化证据、定位 17/20 acquisition failure 与 3/20 selection failure，
并依据质量/精度/延迟门禁拒绝候选。简历的主要结果仍应使用已经验证的 WixQA Dense、
EnterpriseRAG-Bench 规模和 garak Guard 指标。

### 问：下一步真正值得做什么？

答：先建立新的多文档数据协议和证据角色标注，再验证一个 Top-20 到 Top-5 的覆盖感知选择器。
只有新数据证明 Top-20 仍有明显 acquisition miss 子集，才增加一次有界 rewrite/retry。没有新数据时，
继续堆 Agent、框架或模型只会制造无法证明的复杂度。

## 11. 你应该亲自完成的练习

1. 手算两条排名的 RRF，并解释同分时为什么还需要确定性 tie break。
2. 画出 raw retrieval、ACL、Guard、admitted state、response selection、citation verifier 的顺序。
3. 用自己的话解释 citation recall、precision 和 completeness 为什么不能互相替代。
4. 说明一次 timeout 工具错误为什么不算正式实验，以及如何证明没有半成品结果。
5. 模拟面试官要求“把 0% 隐去”，解释为什么这会破坏项目可信度。

完成这些练习后，再阅读 `scripts/eval_wixqa_multidoc_candidate.py` 的 `main()`，从输入绑定、
四臂循环、指标构建、私有/公开输出到最终 gate，逐段对应本文流程。
