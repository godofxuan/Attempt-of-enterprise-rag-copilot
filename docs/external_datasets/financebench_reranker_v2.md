# FinanceBench 页面重排 v2：从质量实验到成本可控 Cascade

## 1. 这一步到底解决什么问题

旧版已经把 FinanceBench 的文档级检索做到了：

- dev Document Recall@5：`100%`；
- frozen test Document Recall@5：`95.05%`。

但“找到了正确财报”不等于“找到了能引用的正确页”。旧版 dev 的
Page Hit@5 只有 `48.98%`，frozen test 只有 `30.69%`。因此这一轮不改答案
生成器，专门解决：

```text
问题
  -> 找到候选财报
  -> 在候选财报内召回页面
  -> 将真正包含答案证据的页面排进 Top-5
```

本轮仍然只评估页面定位，不是 FinanceBench 答案正确率。

## 2. 网上项目通常能做到多少

不同论文的任务、切分、语料、模型和指标不同，不能把一个百分数直接当成统一
排行榜：

- [FinanceBench](https://arxiv.org/abs/2311.11944) 原论文的 16 组配置，
  答案成功率约为 `20%-78%`；把正确证据页直接交给 GPT-4-Turbo 的 oracle
  约为 `85%`。这是答案成功率，不是 Page Recall。
- [CRAG](https://arxiv.org/abs/2406.04744) 报告高级 LLM 在其动态问答基准上
  准确率不超过约 `34%`，直接 RAG 约 `44%`，其评测中的工业 RAG 系统约
  `63%` 问题能够在不产生幻觉的情况下回答。这也不是 FinanceBench 页召回。
- [HiREC](https://aclanthology.org/2025.findings-acl.855.pdf) 在其
  FinanceBench 子集上报告 Dense Page Recall `26.11%`、HiREC
  Page Recall `40.00%`，对应答案准确率 `33.33%` 和 `50.00%`。
- [2026 retrieval-gap 研究](https://proceedings.mlr.press/v318/kobeissi26a.html)
  将 FinanceBench 拆成文档、页面和 chunk 三层，结论同样是页面检索明显落后
  于 oracle，需要 query expansion、cross-encoder 或领域页排序器。

我们的 frozen test Macro Page Recall@5 为 `27.72%`，数量上接近 HiREC 报告
的普通 Dense 层级；但公司隔离切分、PDF parser、索引语料和 cutoff 不完全
一致，所以只能说“处于 dense baseline 档位”，不能声称是同榜比较。

## 3. 改进思路是怎样产生的

### 3.1 先分开候选召回和最终排序

旧系统只保存最终 Top-5，无法判断：

1. 正确页根本没有进入候选池；
2. 正确页已进入 Top-10，但被排在第 6-10 名。

因此 `FinanceBenchPageCaseResult` 新增：

- `page_candidate_score`：重排前候选 Top-5/10/20；
- `page_reranker_score`：LLM 原始完整排序；
- `page_score`：最终交给下游的 Top-5；
- `page_candidate_scores`：不含 gold 的 dense 分数，用于门控；
- reranker 调用、重试、隔离数量和完整延迟。

开发集显示：

| 阶段 | Page Hit | Complete Page Recall | Macro Page Recall |
| --- | ---: | ---: | ---: |
| dense 最终 Top-5 | 48.98% | 38.78% | 43.88% |
| dense 候选 Top-10 | 61.22% | 51.02% | 56.12% |

所以候选池仍有缺失，但当前更直接的瓶颈是 Top-10 到 Top-5 的排序。

### 3.2 为什么不是直接扩大到多个文档

新增 `global_page_score` 后，系统可以从多个候选文档各取页面，按 BGE-M3
cosine score 全局合并，并按 `(doc_id, page)` 去重。

两文档、每文档 10 页的候选 Top-20 命中达到 `65.31%`，但最终 Top-5 只有
`40.82%`，低于旧基线。原因是不同文档内的相似度高分不能代替问题级证据
判断，第二文档页面还会挤掉第一文档的正确页。

结论：多文档候选池提高了理论上限，但在可靠 reranker 出现前不能成为默认。

### 3.3 为什么加入本地 LLM reranker

[BGE reranker 文档](https://bge-model.com/bge/bge_reranker.html) 展示的标准
两阶段模式是先用 embedding 召回较大候选池，再用更昂贵的模型重排到较小
Top-K。当前环境没有安装 cross-encoder 权重，但已有 D 盘本地
`qwen3:8b`，所以先把它作为 listwise reranker 原型：

1. 输入问题和最多 20 个候选页面；
2. retrieved-content Guard 在文本进入模型前扫描；
3. 候选 chunk ID 映射为 `candidate-01` 形式的临时白名单 ID；
4. 模型必须返回每个 ID 恰好一次；
5. 缺失、重复、未知 ID 或非 JSON 均拒绝；
6. 最多一次显式纠错重试，重试计入 generation calls。

LLM 不接收 gold page，也不能扩大候选池。

## 4. 代码具体改在哪里

### `app/retrieval/page_reranker.py`

新增独立重排组件：

- `LocalLLMPageReranker`：本地模型调用、Guard、白名单和重试；
- `PageRerankResponse`：严格结构化输出；
- `parse_page_rerank_response()`：拒绝不完整或越权排序；
- `PageRerankResult`：返回排序、admit/quarantine 数和尝试次数。

它独立于 FinanceBench，可以继续接入普通企业检索链路。

### `app/external_datasets/financebench_page_eval.py`

新增：

- 多文档 page candidate pool；
- 按页去重的 `global_page_score`；
- candidate/raw-reranker/final 三层指标；
- dense Top-1 保护融合；
- dense confidence gate；
- reranker 完整延迟和阶段计数；
- run schema v1/v2 向后兼容迁移。

### `scripts/eval_financebench_pages.py`

新增 CLI：

```text
--drilldown-merge-mode
--page-reranker
--reranker-model
--reranker-timeout-seconds
--reranker-dense-head-count
--reranker-max-attempts
--reranker-gate-mode
--reranker-gate-threshold
```

旧 frozen test 强制保持 `quota + no reranker`，因此 v2 参数不能偷偷改写 v1
测试协议。

### `app/ollama_chat.py`

增加可选 `timeout_seconds`。默认线上 API 仍使用 `12s`，只有离线 reranker
评测显式使用 `120s`，且该值写入 manifest。

### 测试

- `tests/retrieval/test_page_reranker.py`：结构化排序、注入隔离、白名单、
  非法输出和纠错重试；
- `tests/external_datasets/test_financebench_page_eval.py`：候选合并、页去重、
  dense-head 融合、门控、summary 和旧 run migration；
- `tests/test_ollama_chat.py`：离线 timeout override 不改变线上默认值。

## 5. 实验结果

同一 49 题 dev、同一 BGE-M3 索引：

| 方案 | LLM calls | Hit@5 | Complete R@5 | Macro R@5 | Mean | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| dense baseline | 0 | 48.98% | 38.78% | 43.88% | 1.29s | 1.71s |
| qwen3 全量替换 | 49 | 51.02% | 36.73% | 43.88% | latency invalid | latency invalid |
| qwen3 + 保留 dense Top-1 | 49 | **57.14%** | **42.86%** | **50.00%** | 8.86s | 45.12s |
| qwen2.5:3b + Top-1 | 57 | 42.86% | 32.65% | 37.76% | 3.07s | 4.09s |
| qwen3 confidence cascade | 13 | **53.06%** | **40.82%** | **46.94%** | **2.46s** | **5.95s** |

相对 baseline，cascade：

- Page Hit@5 `+4.08` 个百分点；
- Complete Page Recall@5 `+2.04` 个百分点；
- Macro Page Recall@5 `+3.06` 个百分点；
- 比全量 qwen3 少 `73.47%` 的 generation calls；
- 全量 qwen3 的 p95 从 `45.12s` 降到 `5.95s`。

这些都是 dev 结果，不是新 holdout 结果。

## 6. 遇到的失败和修复

### 离线任务复用了线上 12 秒超时

首个 qwen3 run 在模型冷启动时 `transport_timeout`。修复不是放宽线上 SLA，
而是给离线 CLI 单独的 timeout override，并写入 provenance。

### 第一版漏算 reranker 延迟

第一版 timer 在检索结束后停止，LLM 时间没有进入总 latency。该运行的质量
指标仍可诊断，但 latency 明确作废。后续每题保存
`page_reranker_latency_ms`，总延迟为宽检索、page drilldown 和 reranker
之和。

### qwen3 会救回题，也会破坏题

直接替换排序时，qwen3 救回 5 题，却破坏 4 题；其中 3 个退步题的正确页原本
就是 dense rank 1。因此采用“保护 dense Top-1，其余位置由 Qwen 补齐”。

### 小模型更快但更差

qwen2.5:3b 首题就返回重复 ID；加入一次严格纠错后，49 题仍产生 57 次调用，
且质量低于 baseline。它被保留为 negative control，不进入候选默认方案。

### 离线门控估算高于真实运行

离线模拟预计 14 次调用和 Macro Recall `48.98%`；真实运行是 13 次调用和
`46.94%`。边界分数和本地生成存在轻微波动，所以只能以真实不可变运行包为
准，不能以模拟表代替。

### 新 schema 一度破坏旧运行验证

新增 `reranker_case_count` 后，旧 run 没有该字段。修复采用输入期 migration：
当旧 summary 有 `reranker_cutoffs` 且缺字段时，从 cutoff 的 case count 推导。
七组历史运行随后全部重新验证通过。

## 7. 为什么这比“堆一个 LLM”更工业化

- LLM 之前有 retrieved-content Guard；
- LLM 只能重排白名单候选，不能越权检索；
- 输出协议错误不会静默修补；
- 线上和离线 timeout 分开；
- quality、candidate ceiling、模型调用和延迟同时记录；
- negative control 和无效运行也保留；
- 用置信度 cascade 控制成本；
- immutable run 绑定 Git SHA、dataset/index hashes 和 artifact hashes；
- frozen test v1 不允许复用 v2 参数。

## 8. 当前不能声称什么

不能说：

- “FinanceBench 答案准确率是 53.06%”；
- “已经超过 HiREC”；
- “cascade 已泛化到 test”；
- “p95 5.95 秒已经是生产 SLO”；
- “qwen3 一定比所有 reranker 更好”。

可以说：

> 在 49 题 FinanceBench 开发集的页面定位任务上，我先把候选召回和最终排序
> 拆开，发现 Page Hit@10 为 61.22%，而 Top-5 只有 48.98%。我实现了带
> retrieved-content Guard、严格 ID 白名单和结构化重试的本地 Qwen 页面
> reranker。全量 qwen3 将 Macro Page Recall@5 提升到 50%，但 p95 达到
> 45 秒；随后用 dense 置信度 cascade 把调用从 49 降到 13，Macro Recall
> 达到 46.94%，p95 为 5.95 秒。该阈值只在 dev 上选择，因此下一步必须使用
> 新的独立 holdout 才能形成简历中的泛化结论。

## 9. 下一门禁

1. 选取未参与本轮分析的新外部金融 QA 数据作为 holdout；
2. 在看到标签前冻结 parser、candidate depth、dense-head、gate threshold、
   模型 digest 和最大重试；
3. 同时报 candidate、final、answer、citation 和 latency；
4. 若 cascade 未同时满足质量不退化、调用下降和超时预算，不晋级默认；
5. 旧 FinanceBench test v1 只保留历史回归，不再用于 v2 调参声明。

公开聚合和私有 artifact hashes：
[financebench_dev_page_reranker_v2.json](evidence/financebench_dev_page_reranker_v2.json)。

## 10. 本轮代码交付验证

- 全仓确定性测试：`2496 passed, 30 skipped, 0 failed`；
- 公开仓库脱敏审计：`946 candidates, 0 findings`；
- 七组私有不可变评测运行包全部通过哈希和 schema 复验；
- 公开仓库只提交聚合指标、边界、代码版本和 artifact hash，不提交受限数据、逐题内容或本地绝对路径。

这里的 `0 findings` 表示审计规则在 946 个候选文件中没有发现敏感内容，不表示系统没有检索错误。模型效果由 Page Hit、Page Recall 和后续独立 holdout 决定，仓库清洁度由 public audit 决定，两者不能混为一个指标。
