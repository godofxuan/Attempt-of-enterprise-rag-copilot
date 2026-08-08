# Enterprise RAG 项目教学交接手册

本文解释本轮 enterprise-aligned evaluation 做了什么、为什么这样做、代码
在哪里、遇到了什么问题，以及结果为什么好或不好。它不是运行状态来源；正式
数字以 `docs/enterprise_eval/evidence/` 中的 JSON 和对应 Git SHA 为准。

## 一、为什么重新选择 benchmark

早期项目主要用自建制度文档、FinanceBench、UDA 和 FinQA。它们分别适合做
回归、安全、PDF 页检索和数字推理，但不能单独证明“面向真实企业知识库”。

本轮把证据分成三层：

1. WixQA：真实客服知识库和匿名真实工单问题，回答“客服 RAG 检索是否有效”。
2. EnterpriseRAG-Bench：51 万条、九类企业数据源的合成公司语料，回答“系统
   是否能在大规模异构语料上运行，以及哪里失败”。
3. Finance/PDF 与安全：继续作为专项压力测试，不再冒充主业务 benchmark。

“真实”不等于“盲测”。WixQA ExpertWritten 的问题来自真实支持场景，但标签是
公开的，因此只能叫固定外部评测，不能叫隐藏测试集。

## 二、WixQA 数据与代码流程

关键实现位于：

- `app/external_datasets/wixqa.py`：下载文件校验、官方 ID 保留、规范化。
- `app/external_datasets/wixqa_index.py`：固定窗口切块、BM25 与 BGE-M3 索引。
- `app/external_datasets/wixqa_eval.py`：BM25、Dense、RRF 的同协议评测。
- `scripts/download_wixqa.py`、`build_wixqa_index.py`、`eval_wixqa_retrieval.py`：
  从数据到结果的命令行入口。
- `data_manifests/WIXQA_MANIFEST.json`：版本、来源、许可证和哈希。
- `docs/enterprise_eval/evidence/WIXQA_RETRIEVAL_PROTOCOL_V1.json`：测试前冻结的
  参数和指标定义。

数据流可以理解为：

```text
官方文件 -> SHA-256 校验 -> 保留 article/question ID -> 固定窗口切块
        -> BM25 索引 + BGE-M3 向量索引
问题 -> 三个检索臂分别返回 chunk -> 按 article ID 去重 -> Top-5 article
     -> 与官方 gold article ID 比较 -> Recall/MRR/nDCG/完整性/延迟
```

为什么必须按 article ID 评分？因为标题可能重复或变化，模糊字符串匹配会把
“看起来相似”误当成 gold。官方 ID 让判断可复现。

### 指标怎么理解

- Recall@5：每题需要的 gold article 中，有多少出现在前 5。单 gold 时也可理解
  为前 5 是否命中，多 gold 时会按命中比例给分。
- MRR@5：只关心第一个 gold 出现得多早。第一名是 1，第二名是 1/2，没进前 5
  是 0。
- nDCG@5：同时考虑多个相关文档和排序位置，越相关的文档越早出现，分数越高。
- Multi-article completeness@5：只看需要多个文档的问题，前 5 是否把所有 gold
  都找齐。它比“至少命中一个”严格得多。
- p95：95% 请求都不慢于这个时间，用来观察尾延迟，而不是只看平均值。

### 结果为什么 Dense 最好

ExpertWritten 上，BM25/Dense/RRF 的 Recall@5 分别为 42.75%/66.42%/59.25%。
真实用户会使用同义改写和自然语言，不一定复用文档关键词，BGE-M3 的语义表示
更适合这种情况。等权 RRF 把较弱的 BM25 排名强行混入，反而把 Dense 的正确
文档挤出前五，并把 p95 从 157.4 ms 提高到 304.6 ms。因此“混合检索”不是天然
比 Dense 好，融合权重必须通过独立开发集验证。

## 三、EnterpriseRAG-Bench 为什么难

官方语料包含 511,962 行，来源包括 Slack、Gmail、Linear、Drive、HubSpot、
Fireflies、GitHub、Jira 和 Confluence。它适合测规模、异构来源、多文档和冲突，
但它是合成公司数据，不能说成真实公司内部数据。

原始 schema 只有 `doc_id/source_type/title/content`。没有可靠的线程、作者、时间、
版本或 ACL。因此适配器只能保存官方字段，不能根据正文猜测 metadata。四个
`doc_id` 被不同记录复用，所以内部主键使用“官方 ID + 原始行哈希”，评分仍使用
官方 ID。这是数据工程里“业务 ID 不一定是数据库主键”的典型例子。

## 四、为什么不能直接复用原来的 BM25

容量分析估计固定切块后有 1,702,370 个 chunk。若用 Python 对象保存 BM25 token，
估计需要 36.60 GiB，超过本机约 31.62 GiB 内存；Dense 的 embedding cache 和
FAISS 副本也约 12.99 GiB，完整嵌入按实测速率约需 11.39 小时。

于是没有“硬跑到机器崩溃”，而是实现 `app/external_datasets/
enterprise_rag_bench_fts.py`：

1. SQLite FTS5 把倒排表放到磁盘，不把全部 token 作为 Python 对象常驻内存。
2. `records` 表保存内部 ID、官方 ID、来源和行哈希；contentless FTS 表只保存
   检索 postings，减少重复正文。
3. 每 5,000 行写 checkpoint。进程中断后只有 corpus/manifest 哈希完全一致才能
   继续，防止接着错误版本构建。
4. 新版本先在 staging 构建，完成后检查数据库完整性、行数、artifact hash 和
   ordered-record hash，再原子切换 active pointer。
5. 测试注入中断，验证恢复后结果与一次完成相同。

结果：全量索引 231.35 秒完成，文件 1.37 GiB，峰值工作集约 1.83 GiB。这是明确的
工程改进：解决“全量 benchmark 根本跑不起来”的容量问题。它不代表检索质量比
另一算法提高，因为前后没有同规模可运行的质量对照。

## 五、全量检索结果和失败分类

FTS5 B0 在 470 个有 gold 文档的问题上得到 Recall@5 60.37%、nDCG@5 55.89%、
多文档完整率 28.26%、p95 1821 ms。

`scripts/analyze_enterprise_rag_bench_failures.py` 按固定优先级分类：

```text
Top-5 完全没有 gold        -> RETRIEVAL_MISS
命中部分但多文档没找齐     -> MULTI_DOC_INCOMPLETE
有命中但首位不是 gold      -> WRONG_DOCUMENT
否则                       -> OK
```

这不是 LLM 判断，而是对官方 gold ID 和检索 ID 做集合/排序比较。优点是便宜、
可复现、没有 judge 漂移；缺点是它只能解释检索身份，不能判断答案语义、冲突说明、
引用是否支持某个 claim。最终计数为 153 miss、59 incomplete、58 wrong document、
200 OK。Semantic 类贡献 80 个 miss，因此下一候选应优先解决召回，而不是先加
reranker。Reranker 只能重排已经召回的候选，无法找回候选集中不存在的文档。

## 六、真实 Agent 路径是怎么评测的

实现位于：

- `app/external_datasets/wixqa_agent_eval.py`：把固定 B2 排名映射为生产工具结果，
  运行真实 V2 Runner 并统计工具、证据、引用和延迟。
- `scripts/eval_wixqa_agent.py`：执行并断点保存私有逐题结果。
- `scripts/publish_wixqa_agent_eval.py`：只发布无题目正文的聚合证据。
- `WIXQA_AGENT_PROTOCOL_V1.json`：冻结预算和指标。

运行链不是伪造的 `if agent: score += 1`，而是：

```text
V2AgentRunner -> ToolRegistry -> search -> RetrievedContent Guard
              -> Controller -> Evidence Ledger -> response builder
              -> CitationVerifier
```

Agent 与 B2 使用同一个 RRF 排名，避免 Agent 偷换更强 retriever。预算限制为最多
3 次 search、2 次 find、4 次 open、12 步、12,000 字符上下文和 15 秒 deadline。

### 接入时遇到的三个具体问题

1. 初始代码引用了不存在的 embedding 模块。通过检索实际运行时实现，改为
   `app.runtime.ollama_embeddings`，而不是新增重复客户端。
2. `matched_text` 和 `context_text` 都塞完整 chunk，导致 Guard 输入超过 12,000
   字符预算。修正为短 preview + 完整 parent context。
3. Guard 要求长上下文必须有父子 provenance。补上 `parent_chunk_id` 和
   `context_from_parent=True`，明确长文本来自哪个已检索 chunk。

这些是数据契约错误，不是模型能力问题。修复后 400/400 没有结构化工具错误，
说明链路跑通了；但“跑通”不等于“有效”。每题都只有一次 search，`find/open` 均为
0，检索召回没有提高，最终多文章引用完整率为 0%，p95 增加 1.47-1.59 倍。因此
正确结论是拒绝当前 Agent route。

## 七、哪些能力还没有被外部证明

- Source-aware chunking：只完成设计，未做 paired experiment。
- Evidence Ledger：机制存在，但没有外部 ON/OFF 冲突回答实验。
- Refusal：本轮没有外部 unanswerable precision/recall。
- Answer correctness：WixQA Agent 本轮只测检索/引用身份和工具行为。
- HERB deep search：没有运行。
- Enterprise Dense/RRF/Agent：没有运行。

面试时把 `NOT_RUN` 讲清楚不是减分。它说明你知道指标边界，并通过 Go/No-Go
控制成本和测试集污染。

## 八、下一步应该做什么

停止无边界增加功能。若有独立开发协议和约 12 小时本地计算预算，唯一优先实验
是 EnterpriseRAG 的分片/内存映射 Dense candidate，用它验证 semantic Recall@5
能否明显超过 FTS5，同时报告索引时间、内存和 p95。若没有这些资源，项目应进入
源码学习、演示、简历和面试准备阶段。

最终审计结论和可写简历措辞见：

- `docs/enterprise_eval/FINAL_REPORT.md`
- `docs/enterprise_eval/RESUME_SAFE_METRICS.md`
- `docs/learning/RESUME_BULLET_EVIDENCE_MAP.md`
