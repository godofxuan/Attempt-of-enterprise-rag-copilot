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

---

## 2026-08-09 Rapid Quality Sprint：从“有功能”走到“有可信结论”

这一轮没有继续添加框架，而是围绕四个已测量问题做收口：引用判断的否定句漏洞、公开证据不完整、FTS 激活并发边界、多文档 Agent 效果不成立。最后只在条件满足时做 Dense 容量资格测试。

### 1. 否定句为什么会击穿朴素的引用支持

旧逻辑把“Revenue was 10 million”和“Revenue was not 10 million”看成词面高度重合：数字一样、关键词一样，只差一个否定词。如果系统只看 token overlap，就可能把矛盾证据判为支持。

修复思路不是让另一个 LLM 打分，而是先找与 claim 相关、数字/日期一致的 evidence 句，再比较两边是否出现显式否定。只有不相关的负面句子不会否决真正支持句。

| 学习入口 | 位置 |
|---|---|
| 源码 | `app/agent/citation_verifier.py`：`_negation_mismatch`、`_negation_comparable`、`_has_explicit_negation` |
| 测试 | `tests/agent_v2/test_citation_verifier.py`：英文/中文、数字/非数字、年份、权限、数量双向否定 |
| 实验结果 | focused `22 passed`；Agent 132、FinQA 19、Guard/ACL 72、domain/retrieval 48 回归通过 |
| Commit | `0848fc0 fix(grounding): reject asymmetric negation contradictions` |

这仍不是语义蕴含模型。它解决的是可确定编码的不变量，遇到同义改写、反讽或复杂条件逻辑仍需要人工或经过校准的语义 judge。

### 2. 为什么 Agent 类存在，不等于 Agent 有效果

旧 WixQA Agent 的真实轨迹是每题 `search=1, find=0, open=0`。这说明 Runner、Controller 和工具边界确实执行了，但行为退化成一次检索后立即回答。机制运行成功与质量提升是两个问题。

代码审计又发现 `ExtractiveResponseBuilder` 对每个 supported aspect 只取 `hits[0]`。因此即使 top-5 已经包含两篇 gold 文章，最终答案也只可能引用一篇，多文档引用完整率自然是 0。

本轮给 Builder 增加显式的 `max_evidence_per_aspect`，默认仍为 1，实验候选设为 5。这样只改变最终证据聚合，不偷换 retriever、embedding、Guard、ACL 或 top-k。

| 学习入口 | 位置 |
|---|---|
| 源码 | `app/agent/runner_v2.py`：`ExtractiveResponseBuilder` |
| Agent 状态 | `app/agent/controller_v2.py`：`evidence_by_aspect`、`next_decision`、`observe` |
| 评测 | `scripts/eval_wixqa_multidoc_fast_track.py` |
| Cohort | `docs/rapid_upgrade/evidence/MULTIDOC_DEV_COHORT.json` |
| 测试 | `tests/agent_v2/test_runner_v2.py`、`tests/external_datasets/test_wixqa_multidoc_fast_track.py` |
| 证据 | `docs/rapid_upgrade/evidence/MULTIDOC_FAST_TRACK_PUBLIC.json` |

结果是完整率 `0% -> 22.22%`，但引用精确率 `44.44% -> 18.52%`。这证明“单来源坍缩”是真根因之一，也证明“把 top-5 全引用”不是合格产品解法。因为这 27 题已经观察过，不能称 fresh validation，更不能写成简历上的 Agent 提升。

### 3. multi-document completeness 到底测什么

- `Article Recall@5`：每题所有 gold article 中，有多少比例进入前 5。
- `Multi-document Retrieval Completeness`：只要少一篇就记 0；全部进入前 5 才记 1。
- `Required Evidence Completeness`：所有必须证据是否进入最终 accepted evidence。
- `Citation Completeness`：所有 gold source 是否最终真的被引用。
- `Citation Precision`：已引用 source 中有多少是 gold。

它们不能互相替代。候选的 Recall 没变，但 completeness 提高，是因为它把已检索证据保留到了最终输出；precision 大跌，则说明它同时保留了不相关候选。Evidence completeness 也不等于 answer correctness：证据齐了，模型仍可能算错、漏答或错误解释。

### 4. 为什么 Dense 可能比 BM25 好，RRF 却可能更差

BM25 依赖词面匹配，适合专有名词、编号和原词复用。Dense 把问题和文档编码成语义向量，适合同义改写和自然客服问法。WixQA ExpertWritten 上 Dense Recall@5 `66.42%`，BM25 `42.75%`，说明语义匹配在该数据集更重要。

RRF 只融合名次，不理解哪一路更可靠。等权融合把较弱 BM25 的高排名注入 Dense top-5，可能挤掉正确文档；本项目 Equal RRF Recall@5 `59.25%`，低于 Dense，p95 又从 `157.4 ms` 增至 `304.6 ms`，所以被拒绝。技术名词更多不代表效果更强。

对应源码和证据：

- `app/external_datasets/wixqa_retrieval.py`：Dense/BM25/RRF 排名；
- `scripts/eval_wixqa_retrieval.py`：同协议三臂评测；
- `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json`：完整聚合；
- `tests/external_datasets/test_wixqa_public_evidence.py`：协议三臂和字段完整性。

### 5. 511,962 条数据为什么不能继续用 Python 内存 BM25

容量 profiler 估计 1,702,370 chunks。Python token/list/string 对象不仅保存文本，还带对象头和指针，估算约 36.60 GiB，超过本机约 31.6 GiB RAM。SQLite FTS5 把倒排表放磁盘，最终 1.37 GiB artifact、约 1.83 GiB peak RSS，并支持 checkpoint、校验和原子 active pointer。

本轮新增 single-writer lock：第二个 builder 在接触 staging/SQLite 前就 fail fast。流程是：获取根级 lock -> 私有 staging 构建 -> 完整性/行数/hash 校验 -> 原子提升 immutable version -> 原子替换 active pointer -> token 所有者释放 lock。进程硬崩溃后保留 stale owner 信息，要求显式处理，不会偷偷抢锁。

| 学习入口 | 位置 |
|---|---|
| 源码 | `app/external_datasets/enterprise_rag_bench_fts.py` |
| 测试 | `tests/external_datasets/test_enterprise_rag_bench_fts.py`：中断、验证失败、并发、路径穿越 |
| Contract | `docs/rapid_upgrade/02_FTS_ACTIVATION_CONTRACT.md` |
| 外部证据 | `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json` |

### 6. mmap/sharded Dense 为什么没有直接实现

真实 1k/10k/50k BGE-M3 资格测试得到 `35.74/35.93/36.76 chunks/s`，吞吐稳定，但全量投影 12.87 小时；向量矩阵约 6.49 GiB，若再保留平面索引副本约 12.99 GiB。磁盘够，但项目没有 full-corpus resumable shard builder，也没有未消费的 Enterprise development protocol。此时直接烧 12.87 小时只能得到一个已消费 fixed regression，不能形成更可信的简历指标。

源码/测试/证据：`app/external_datasets/enterprise_dense_capacity.py`、`scripts/qualify_enterprise_dense_capacity.py`、`tests/external_datasets/test_enterprise_dense_capacity.py`、`docs/rapid_upgrade/evidence/ENTERPRISE_DENSE_CAPACITY_PUBLIC.json`。

### 7. public-label fixed、consumed benchmark 和 blind holdout

- public-label fixed：题目和标签公开，但协议冻结后只做一次正式比较；不是盲测。
- consumed：结果或逐题错误已经看过，之后只能做回归/开发，不能再称独立验证。
- blind holdout：开发期间看不到标签或样本，由独立流程一次性揭盲。

本轮 27 题 Agent cohort 明确写 `RETROSPECTIVE_DEVELOPMENT_ONLY_ALREADY_OBSERVED`；这比把旧 test 改名成 validation 更可信。证据入口是 `docs/enterprise_eval/CONSUMPTION_LEDGER.md` 和各 public JSON 的 `consumption/claim_boundary` 字段。

### 8. ACL admission 的准确边界

ACL 在候选进入融合、parent context、Agent state 和 citation output 前执行。项目能证明“不可见内容不能进入可见 evidence 流”。但当前 FAISS 仍可能先做全局 ANN 候选搜索，再对候选执行 visible filtering；因此不能声称物理层 pre-ANN tenant partition。准确说法是 logical pre-context admission，不是独立向量分区。

源码：`app/retrieval/pipeline.py`、`app/security/access.py`；测试：`tests/retrieval/test_pipeline_acl.py`；架构说明：`docs/architecture.md`。

### 9. 最终工程结论

项目已经有三类外部证据：WixQA enterprise retrieval、EnterpriseRAG scale、garak retrieved-content security。Agent mechanism 强，但外部正向 effect 未证明；full Dense 因预注册门失败停止。正确下一步不是继续堆 LangGraph/GraphRAG/更多模型，而是学习源码、准备演示和面试，并只在拿到真正新数据或业务验收集时恢复效果开发。
