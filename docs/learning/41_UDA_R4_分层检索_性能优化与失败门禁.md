# 第 41 章：UDA R4 分层检索、性能优化与失败门禁

这一章讲清楚一次先被原门禁拒绝、后来只晋级到限定 canary 的改进。重点不是把
81.25% 写得好看，而是理解：
RAG 检索如何组合多路信号、为什么延迟会突然变差、怎样避免 ACL 重复计算，以及
为什么不能篡改旧门禁，以及为什么“未达到全量发布门槛”不等于“完全没有价值”。

## 1. 我们到底在测什么

每道题已经知道属于哪一份财报，系统需要从这份财报中找出答案所在页面。这里测的是
`known-report page localization`，不是在所有企业文档中先找公司和财报，也不是让 LLM
生成最终答案。

- `Hit@5`：前 5 个返回页面里是否至少有一个 gold page。64 题命中 52 题就是
  `52/64 = 81.25%`。
- `MRR@5`：gold page 越靠前越好；第 1 名得 1，第 2 名得 1/2，第 5 名得 1/5。
- `nDCG@5`：也奖励正确页面靠前，并能自然处理多个相关页面。本项目的 R4 问题主要
  是单 gold page，因此它与 MRR 方向相近，但折扣公式不同。
- `p95`：95% 请求不超过这个耗时，用来防止平均值掩盖慢请求。

## 2. 为什么只用 Dense 还会漏

BGE-M3 Dense 擅长语义相似，但财报问题常包含年份、指标缩写和精确财务术语。例如：

```text
What was the percentage change in R&D expenses from 2015 to 2016?
```

原问句包含很多普通语言。`focus_financial_query()` 会得到：

```text
r&d expenses 2015 2016
```

这个短查询更适合 BM25，因为 BM25 重视精确词和数字。代码在
`app/external_datasets/uda_finance_hierarchical.py`。

## 3. 三路候选是怎样合并的

最终 v3 有三条路：

1. 原问题 Dense，权重 1.0；
2. 原问题 BM25，权重 0.5；
3. focused query BM25，权重 0.5。

每条路先返回 chunk。`fuse_unique_page_rankings()` 用 `(doc_id, page)` 去重，同一页
即使有多个 chunk 也只获得一个页面名次。随后计算 weighted RRF：

```text
page_score += channel_weight / (60 + page_rank)
```

RRF 不直接比较 Dense cosine 与 BM25 分数，因为两者数值尺度不同；它只使用各通道
内部名次。最终返回的仍是原始 `SearchHit`，所以 page locator、ACL、版本和 source
provenance 不会在融合时丢失。

## 4. 为什么“并发执行三次检索”反而慢

v2 最初把三次完整 `search()` 放入线程池。看起来它们可以同时完成，但每次 search
都会扫描 10,383 个 chunk 做 ACL/metadata 判断，BM25 还会给全库算分。与此同时，
本地 Ollama 正在用 CPU/GPU 生成 Dense query embedding。线程并发只是让这些工作
争抢资源，开发集 p95 达到基线的 2.304 倍。

第一层修复位于 `app/retrieval/pipeline.py::_rank_bm25()`：先完成 ACL 和 metadata
筛选，再调用 `BM25Okapi.get_batch_scores()`，只给可能返回的 chunk 算分。它把倍率
降到 1.700，但三条通道仍重复算可见范围。

第二层修复是 `search_many_same_scope()`：

```python
if any(request.user != first.user or request.filters != first.filters ...):
    raise ValueError(...)
visible_scope = self._resolve_visible_scope(first)
```

只有 `UserContext` 和 `QueryFilters` 完全一致，才能共享 scope；否则 fail closed。
因此它不是跳过 ACL，而是由服务端算一次 ACL 后，在同一批只读检索中复用结果。
最终开发 p95 倍率降到 1.041，validation 是 1.066。

## 5. 中间遇到的真实错误

`rank-bm25 0.2.2` 的 `get_batch_scores(query, doc_ids)` 表面上接受一组 ID，但内部
使用 NumPy 索引。传 `(0, 2)` 这样的 tuple 会被 NumPy 当成二维索引，触发
`IndexError: too many indices`。修复不是捕获异常继续，而是在依赖边界显式执行
`batch_indices = list(visible_indices)`。76 个检索与 R4 测试随后全部通过。

另一个问题是评测脚本原本只锁定 validation/test 各运行一次，却没有检查 validation
前的 dev 是否在同一 Git SHA、同一 protocol 下通过。新增的
`require_development_authorization()` 会验证这些哈希和三项 gate 后，才创建一次性
validation marker。

## 6. 为什么原始结果仍然叫门禁失败

开发 96 题：

| 指标 | Dense | v3 | 变化 |
|---|---:|---:|---:|
| Hit@5 | 83.33% | 88.54% | +5.21pp |
| nDCG@5 | 66.82% | 73.95% | +7.13pp |
| p95 | 112.68 ms | 117.29 ms | 1.041x |

独立 validation 64 题：

| 指标 | Dense | v3 | 变化 |
|---|---:|---:|---:|
| Hit@5 | 76.56% | 81.25% | +4.69pp |
| nDCG@5 | 64.41% | 72.61% | +8.20pp |
| p95 | 112.65 ms | 120.06 ms | 1.066x |

预注册门槛是三个条件同时成立：Hit@5 至少 +5pp、nDCG@5 至少 +3pp、p95 不超过
1.5x。validation 的 Hit@5 少 0.3125pp，所以决定必须是
`VALIDATION_REJECTED_TEST_FORBIDDEN`。不能看到结果后把门槛改成 +4.5pp，也不能只
挑 nDCG 写“项目已经通过了原门禁”。冻结 test 没有运行。

## 7. 为什么后来又能晋级到 canary

`5pp` 是预先约定的全量候选门槛，不是自然定律。如果系统从 90% 到 94%，虽然只加
4pp，但错误率从 10% 降到 6%，相对错误减少 40%，当然可能有价值。正确做法不是
偷偷把旧门槛改成 4pp，而是保留旧结论，再建立一个明确标注为 post-hoc 的灰度决策。

本项目把 64 道题逐题配对后得到：

- 46 题两种方法都命中；
- 6 题只有新方法命中，也就是被救回；
- 3 题只有旧方法命中，也就是新方法发生退化；
- 9 题两种方法都没命中。

因此漏检从 15 题降到 12 题，相对减少 `3/15 = 20%`。但 Hit@5 增益的 bootstrap
95% 区间是 `-4.69pp～+14.06pp`，仍然跨过 0；McNemar 检验 p 值是 0.5078，不能
把它说成已经证明的普遍提升。nDCG@5 增益区间是 `+1.58pp～+15.04pp`，说明正确页
排得更靠前这一点更稳定。

所以晋级级别是：只允许调用 `build_finance_known_report_canary()` 显式构建
`finance_known_report_page_fusion_v1`。运行时还必须显式设置
`RETRIEVAL_PROFILE=finance_known_report_page_fusion_v1`，并且请求只能绑定一份已知
报告，还要由运维在 `RETRIEVAL_CANARY_POLICY_IDS` 白名单中明确列出它；否则配置
直接失败或请求自动走默认检索。canary 产生的候选池仍要经过 Retrieved-content Guard，
不能因为是实验配置而绕过安全准入。默认检索不变，旧 test 仍不运行。要扩大范围，
必须使用新的 company-disjoint 数据。这个过程相当于软件发布中的小流量 canary，
不是宣布“全局上线”。

## 8. 面试时怎样回答

**问：结果没有晋级，这次开发有价值吗？**

有三类价值。算法层面证明多路 lexical signal 对页面排序有稳定帮助；系统层面把
一个 2.30x 延迟候选优化到约 1.07x，并且不绕过 ACL。更重要的是，独立 validation
阻止了开发集上的乐观结论直接进入全局默认；后续又用逐题配对分析把候选限制在
可回滚 canary，而不是简单丢弃。

**问：为什么不把 72.61% 当准确率？**

它是 nDCG@5，衡量 gold page 在前 5 页里的排序质量，不是回答正确率。题目还假设
已知目标财报，所以也不是 open-corpus 检索准确率。

**问：下一步应该怎么提升？**

不能再用这 64 道 validation 或冻结 test 调参。需要新的外部评测人口。R4 的 28 份
PDF 生成了 10,383 个 page chunks，但 structured table chunks 为 0，因此新的合理
假设是 table/layout-aware parsing；必须在新数据上做 current parser vs table-aware
parser 的 paired ablation，而不是直接重写 ingestion。

## 9. 你应该亲自完成的练习

1. 手算一个页面分别排在 Dense 第 2、BM25 第 4、focused BM25 第 1 时的 RRF 分数。
2. 解释为什么共享 scope 必须比较完整 `UserContext` 和 `QueryFilters`。
3. 找出 `FocusedPageFusionPipeline.search()` 中保证三个结果来自同一 index snapshot
   的检查。
4. 说明为什么 p95 不能只看一次请求，而 Hit@5 必须保留分子和分母。
5. 用自己的话回答：为什么不能放宽旧 gate，但仍可建立一个限定 canary 决策？

代码与证据入口：`docs/r4/ENGINEERING_JOURNAL.md`、
`docs/r4/evidence/uda_finance_r4_public_v1.json`、
`docs/r4/evidence/uda_finance_r4_canary_review_v1.json`。

## 10. 这套链路从哪里学来

它不是复制某个框架，而是组合了几类公开工程经验：

- Anthropic 的 *Building Effective Agents* 强调从简单、透明、可测量的结构开始，
  只有指标证明收益时才增加复杂度；这对应本项目保留 bounded controller、失败门禁
  和 negative results，而不是为了“Agent 感”继续堆框架。
  <https://www.anthropic.com/engineering/building-effective-agents>
- OpenHands SDK 把 Agent 表达为 reasoning/action loop，并将 action、observation、
  error 和 execution status 保存为事件/状态；本项目因此把 plan、tool、observation、
  Evidence Ledger 和终态做成可回放轨迹，而不是只保留最终回答。
  <https://docs.openhands.dev/sdk/arch/sdk>
- LangGraph 的 persistence/interrupt 文档强调 checkpoint、thread identity、恢复和
  human-in-the-loop；本项目只在需要恢复的审批草稿链路使用这些能力，不让框架绕过
  ToolGateway、ACL 和副作用幂等边界。
  <https://docs.langchain.com/oss/python/langgraph/persistence>
- Azure AI Search 公开说明了 BM25/vector 多路召回经过 RRF，再用二阶段语义排序的
  检索结构；R4 采用的是相同思想层级，但自行实现并评测 Dense + dual BM25 的
  page-level weighted RRF，没有照搬其服务代码。
  <https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking>
- Google SRE 将 canary 定义为小范围、限时部署，并要求对照评估后决定是否扩大；
  这正是“旧门禁失败仍保留，但候选可晋级到显式小范围 canary”的发布依据。
  <https://sre.google/workbook/canarying-releases/>

最重要的共同点不是某个库，而是链路：**明确状态和权限边界 -> 记录动作与证据 ->
离线成对评测 -> 小范围发布 -> 监控和回滚 -> 新数据决定是否扩大**。
