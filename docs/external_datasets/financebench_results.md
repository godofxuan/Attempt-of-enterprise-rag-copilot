# FinanceBench 真实文档接入：工程记录与结果

## 1. 本阶段要解决什么

原有 expanded 语料可以稳定验证 ACL、版本、冲突、安全和 Agent contract，
但文档与问题来自同一套合成事实。它适合回归测试，不足以证明系统能处理真实
企业文档。

本阶段新增独立的 FinanceBench external track。目标不是替换合成语料，而是：

1. 用真实财报暴露解析、分块和索引规模问题；
2. 用上游人工问题、答案和页级证据测试域外检索；
3. 保持 dev/test、原始数据和项目内置数据互相隔离；
4. 在没有真实模型结果前明确写 `NOT RUN`，不伪造准确率。

## 2. 代码改在哪里

| 文件 | 作用 |
| --- | --- |
| `app/external_datasets/financebench.py` | 固定上游提交、下载、schema 校验、公司级切分、manifest 和 evidence sidecar |
| `scripts/prepare_financebench.py` | 一条命令下载、准备或只做完整性复验 |
| `scripts/build_financebench_index.py` | 调用现有 PDF parser、治理、chunk 和 index builder；支持 dry run |
| `app/corpus/schemas.py` | 在通用文档类型中加入 `pdf` 和 `filing` |
| `tests/external_datasets/test_financebench.py` | schema、切分泄漏、冻结 hash、缺 PDF fail-closed 回归 |
| `docs/external_datasets/financebench.md` | 操作手册、数据边界与命令 |

原始数据位于：

```text
.private/external_datasets/financebench
```

`.private/` 已被 Git 忽略，因此 84 份 PDF 不会被误推送到 GitHub，也没有占用
C 盘。

## 3. 项目已有的数据处理链

FinanceBench adapter 不是另一套 RAG。它把外部文件转换为项目现有 contract，
然后复用原处理链：

```text
公开上游
  -> 固定 commit 和 JSONL SHA-256
  -> 文件大小、PDF 文件头、引用完整性校验
  -> CorpusManifest
  -> PdfDocumentParser：逐页文本和 page locator
  -> normalize_document：统一 DocumentRecord
  -> govern_documents：版本、权威、重复和当前状态治理
  -> chunk_document：页内 chunk
  -> build_index_version：不可变 index version
  -> EvalCase：检索评测
```

项目更完整的生产型 lifecycle 还包括 `SourceEvent` 幂等/冲突账本、安全 staging、
quarantine、revision catalog、tombstone、ChangePlan、增量 cache invalidation、
原子激活和回滚。本次公开基准适配没有绕过解析与治理，但为了与现有 synthetic
active index 隔离，使用独立 `.private` index root。

## 4. 真实接入中遇到的问题

### 问题一：README schema 与真实 JSONL 不完全一致

第一次准备失败：

```text
FinanceBenchQuestion.justification expected string, actual value null
```

上游 150 题中：

- 50 题的 `justification` 为 `null`；
- 50 题的 `question_reasoning` 为 `null`。

修复不是把空值改成虚构说明，而是让 upstream model 显式允许 `null`，并让
evidence sidecar 原样保留。这样不会把缺失标注伪装成人工标注。

### 问题二：文档元数据存在冲突重复

第二次准备发现 `FOOTLOCKER_2023_annualreport` 有两条元数据，`doc_period`
分别为 2022 和 2023。该文档不被 150 道开放问题引用。

处理规则：

- 未引用的冲突行不进入本次 corpus；
- 如果冲突发生在被引用文档，adapter 直接失败；
- 禁止用“最后一行覆盖前一行”的非确定性方式隐藏冲突。

### 问题三：把 company 错当成版本族

第一次全 PDF dry run 在 governance 阶段失败：

```text
policy 'financebench-company::3m' must have exactly one active authoritative version
```

原因是同一家公司的 10-K、10-Q 是独立有效财报，不是同一个 policy 的互斥
版本。把 company 作为 `policy_id` 会让治理层误以为 3M 同时有多个“当前版本”。

修复为每份 filing 使用独立 governance ID，company 只保留为数据集和评测分组
元数据。修复后 84/84 文档通过版本治理。

### 问题四：短政策 chunk 参数不适合长财报

原 `parent_child` 默认参数：

```text
parent_size=1000, child_size=250, overlap=80
```

在 84 份财报上产生：

```text
289,326 total chunks
242,946 indexable chunks
```

这会造成约 24 万次逐条 embedding 请求，不适合作为本地实验基线。

FinanceBench 改用页内 heading chunk：

```text
chunk_size=1800, overlap=150
```

复验结果：

```text
29,335 total/indexable chunks
```

在保持 page locator 的前提下，chunk 数减少约 89.9%。这不是已经证明的最优
参数，只是通过 dry run 准入的第一版外部基线；后续仍要用 dev 检索结果做
chunking ablation。

## 5. 当前可核验结果

| 项目 | 结果 |
| --- | ---: |
| 固定上游 commit | `cc39aeb4afdf33909ee1412188bf89035950c2eb` |
| 开放问题 | 150 |
| 被问题引用的 PDF | 84 |
| 公司 | 32 |
| PDF 总字节 | 165,527,662 |
| dev | 49 题 / 11 家公司 |
| frozen test | 101 题 / 21 家公司 |
| dev/test 公司交集 | 0 |
| PDF parser | `pypdf 6.14.2` |
| canonical documents | 84 |
| admitted chunks | 29,335 |
| 下载与 manifest 校验 | PASSED |
| 全 PDF parse/govern/chunk dry run | PASSED |
| BGE-M3 external index | PASSED / 29,335 x 1,024 |
| embedding 批次 | 937 computed / 0 corrupt recompute |
| 索引 manifest SHA-256 | `7eae87f4c9ab670a1f10838f553fe2a0a7b53c0ef2958ff950101e7b8305be01` |
| FinanceBench dev baseline Recall@5 | 79.59% / 39 of 49 |
| FinanceBench dev entity-scope v5 Recall@5 | 100% / 49 of 49 |
| dev entity-scope v5 MRR / nDCG@5 | 94.56% / 95.97% |
| dev entity-scope v5 ACL leakage | 0 |
| dev baseline / v5 mean retrieval latency | 743 ms / 799 ms |
| frozen test result | NOT RUN |
| 页级答案/引用评分 | NOT RUN |

以上 100% 仅指 49 道 **development retrieval cases** 的文档级
`Recall@3/5`。它不等于答案准确率、页级引用准确率、冻结 test 成绩或生产流量
效果。

可公开审核的脱敏指标与私有 summary 哈希位于
[`evidence/financebench_dev_retrieval_v1.json`](evidence/financebench_dev_retrieval_v1.json)。
原始 PDF、问题内容和逐题私有输出不会提交到仓库。

## 6. 批量 embedding 与断点恢复

原 builder 对每个 chunk 调一次 Ollama。29,335 个 chunk 意味着近三万次 HTTP
请求，而且中途失败后必须重来。本轮改为：

1. `builder.py` 同时支持原单条回调和新的批量矩阵回调；
2. 每批最多 32 个 chunk，同时最多 48,000 字符；
3. 模型 digest、维度、corpus manifest、parser 版本、chunker 配置和有序
   `chunk_id + text_hash` 共同生成 cache build ID；
4. 每个批次保存 L2-normalized `float32 .npy` 和 SHA-256 sidecar；
5. 已存在分片必须重新通过 canonical manifest、字节数、SHA、dtype、shape、
   finite 和 L2 norm 校验；
6. 缺失或损坏分片单独重算，完整分片直接复用；
7. 索引仍在 staging 中构建并完整校验，最后才原子激活。

真实构建结果：

```text
model                         bge-m3
model SHA-256                 790764642607...f2146bab
dimension                     1024
vectors                       29,335
batches                       937
cache bytes                   120,633,969
published index bytes         344,880,988
end-to-end build duration     1,392.3 seconds
```

数据、embedding cache、索引和评测输出均位于仓库 D 盘 `.private`。真实运行暴露
了 jieba 默认使用系统临时目录的问题，随后增加 `runtime_cache_dir`，新进程会把
`jieba.cache` 写到 `.private/runtime_cache/jieba`。

## 7. dev 失败驱动的检索改进

所有实验使用相同 49 道 dev、相同 BGE-M3 索引、`top_k=5`。没有查看或运行
101 道 frozen test。

| 变体 | Recall@1 | Recall@3/5 | MRR | nDCG@5 | Mean latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline, candidate 20 | 42.86% | 75.51% / 79.59% | 57.82% | 63.35% | 743 ms |
| candidate 100 | 40.82% | 63.27% / 63.27% | 50.34% | 53.64% | 739 ms |
| strict entity + year | 89.80% | 97.96% / 97.96% | 93.88% | 94.95% | 757 ms |
| entity only, year soft | 71.43% | 95.92% / 95.92% | 82.65% | 86.08% | 687 ms |
| dual scope, no reuse | 89.80% | 100% / 100% | 94.56% | 95.97% | 1,206 ms |
| dual scope + query vector reuse | 89.80% | 100% / 100% | 94.56% | 95.97% | 1,082 ms |
| dual scope + dense/BM25 reuse v5 | 89.80% | 100% / 100% | 94.56% | 95.97% | 799 ms |

### 为什么 candidate 100 变差

扩大候选池让更多泛化财务 chunk 同时进入 BM25 和 dense 排名，RRF 对两路都
出现的泛化候选加分，反而稀释公司与财年信号。因此保留 candidate 20，不把
“多取候选”当成默认优化。

### 为什么需要实体目录

baseline 的 10 个 miss 高度集中在 `JnJ`、`AMEX`、公司名和指定财年。实体目录
只由 corpus 侧 document information 构建，不读取 dev/test 的 `gold_doc_ids`：

```text
question
  -> exact alias resolution (for example JnJ -> Johnson & Johnson)
  -> company policy_id scope
  -> exact-year scope + company-history scope
  -> one shared dense/BM25 execution
  -> deterministic merge and per-document diversity
```

实体 alias 有歧义时启动失败；与调用者显式 policy filter 冲突时 fail closed。
实体目录 SHA-256
`7b92868849fa179ff84d2b858820c2719599a772cd4fee864794dc1fd50f7580`
写入评测 manifest，便于检查运行时究竟使用了哪份目录。

### 为什么不能把年份永远设为硬过滤

严格年份达到 48/49，但问题 “Is growth in JnJ's adjusted EPS expected to
accelerate in FY2023?” 的证据来自 `2022Q4_EARNINGS` 中的 2023 前瞻指引。
硬过滤 2023 会错误删除正确文档。完全取消年份约束又使两个 FY2022 问题失败。
最终采用 exact-year + entity-history 双 scope，并在一次逻辑请求中共享 query
embedding、FAISS 全局搜索和 BM25 score 数组。

## 8. 代码位置

| 文件 | 本轮职责 |
| --- | --- |
| `app/runtime/ollama_embeddings.py` | 精确 localhost origin、模型 digest、维度与批量响应校验 |
| `app/indexing/resumable_embeddings.py` | 批次预算、cache identity、原子 `.npy` 分片、损坏重算 |
| `app/indexing/builder.py` | 单条/批量 provider 兼容和 embedding matrix 校验 |
| `app/indexing/store.py` | 把批量 provider 接入 staging、验证、原子发布 |
| `app/retrieval/entity_scope.py` | 通用实体目录、alias 解析、多 scope 和确定性 merge |
| `app/retrieval/pipeline.py` | `search_many` 请求内共享 embedding、FAISS 和 BM25 计算 |
| `app/external_datasets/financebench.py` | 从固定上游 metadata 构建 FinanceBench entity catalog |
| `scripts/build_financebench_index.py` | 真实索引构建、进度输出和 cache summary |
| `scripts/eval_enterprise_v2.py` | `--entity-scope financebench` 受审计 dev 评测入口 |

## 9. 面试时怎样准确表达

可以说：

> 我把 84 份真实财报和 150 道 FinanceBench 开放问题接入现有 ingestion、
> governance 和 index contract，并按公司隔离 49 道 dev 与 101 道 frozen
> test。为构建 29,335 个 BGE-M3 向量，我实现了模型 digest 与 chunk
> fingerprint 绑定的批量分片缓存，支持中断续跑和损坏批次重算。dev 初始
> Recall@5 是 79.59%；失败集中在公司别名和财年定位。增加只由语料 metadata
> 构建的实体目录与 exact-year/history 双 scope 后，dev Recall@5 达到
> 100%，MRR 94.56%，ACL 泄露为 0；再通过逻辑请求内复用 dense/BM25 计算，
> 把延迟从 1,206 ms 降到 799 ms。冻结 test 和页级答案评分尚未运行，所以
> 我只把这些数字表述为 dev retrieval 结果。

不能说：

- “FinanceBench 总准确率已经达到 100%”；
- “项目已经经过真实企业生产数据验证”；
- “29,335 chunk 证明参数最优”；
- “公开数据允许直接重新分发”；
- “dev 结果保证 frozen test 或答案生成同样有效”。

## 10. 下一步

1. 冻结 v5 配置和公开证据摘要，再决定是否执行唯一一次 frozen test；
2. 用 evidence sidecar 实现页级 citation recall/precision；
3. 实现 FinanceBench 数字答案归一化和公式容差评分；
4. 为 PDF parse/chunk 增加持久化 cache，消除重启时约 8 分钟的重复解析；
5. 在 test 运行前继续检查实体目录是否完全由语料元数据生成，防止标签泄漏。

## 11. 只读容器 CI 故障复盘

首次推送 FinanceBench 变更后，普通 Ubuntu 和 Windows 确定性任务通过，但
`linux-container-contract` 在 `Run deterministic gates inside the image`
失败。GitHub 原始日志的关键调用链是：

```text
tokenize_for_bm25
  -> _configure_jieba_cache
  -> ensure_dir
  -> mkdir("/workspace/.private/runtime_cache/jieba")
  -> OSError: [Errno 30] Read-only file system: "/workspace/.private"
```

该任务故意使用 `--read-only` 启动非 root 容器，只把 `/tmp` 和测试索引目录
挂成可写 tmpfs。本地开发环境允许向仓库 D 盘的 `.private` 写缓存，所以普通
测试无法暴露这个环境差异。一次 jieba 全局初始化失败会影响所有后续 BM25
调用，因此日志最终显示 144 个 failed 和 355 个 error；这不是 499 个互不
相关的业务缺陷，而是同一个共享依赖初始化错误造成的级联失败。

修复包含三个互相约束的部分：

1. `Settings.runtime_cache_dir` 在存在绝对 `XDG_CACHE_HOME` 时使用
   `<XDG_CACHE_HOME>/enterprise-rag`，否则仍使用仓库 D 盘
   `.private/runtime_cache`；
2. Docker 基础镜像固定 `XDG_CACHE_HOME=/tmp/xdg-cache`，使 test 和 runtime
   两个 stage 都兼容只读根文件系统；
3. 配置测试和容器 contract 测试分别锁定目录选择与镜像环境变量，避免以后
   只修 CI 命令却遗漏生产 runtime。

本地修复验证包括真实 jieba 首次建缓存、23 个配置/容器定向测试，以及
2,460 个完整确定性测试。远端 CI 的最终状态以修复提交对应的 GitHub Actions
run 为准，不能用本地结果代替远端容器证据。
