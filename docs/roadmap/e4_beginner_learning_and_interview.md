# E4 评测与消融：从代码到面试的完整学习笔记

最后更新：2026-07-16

这份文档面向第一次系统学习 RAG/Agent 评测的人。目标不是让你背指标，而是让你能回答四个问题：系统哪里做对了，哪里做错了，为什么这样判断，改动是否真的有效。

## 1. E4 到底解决什么问题

E3 已经有 QueryAnalysis、ACL-aware retrieval、search/open、EvidenceLedger、生成和引用验证。但只看最终答案，会把完全不同的故障混在一起：

```text
问题输入
  -> query analysis
  -> retrieval
  -> evidence decision
  -> generation
  -> citation verification
  -> final response
```

例如用户问“当前远程办公最多几天”，系统回答错，可能有四种根因：

1. 正确文档根本没有召回，这是 retrieval failure。
2. 召回了 2025 旧版而不是 2026 当前版，这是 authority/conflict failure。
3. 正确证据存在，但生成漏掉“3 天”，这是 generation omission。
4. 答案写了“3 天”，却引用无关 chunk，这是 citation failure。

E4 的核心改进是把这些层分开评分，并为每次运行保存可复查证据。最终准确率只是结果，分层指标才告诉工程师下一步改哪里。

## 2. 四层评测的心智模型

```text
Retrieval layer
  找到正确、完整、当前、授权的文档了吗？

Answer layer
  最终 claim 覆盖 required facts，并由可见证据支持了吗？

Agent layer
  意图、工具、分解、停止、预算和轨迹合理吗？

Security layer
  是否越权、泄漏 trace、被注入诱导，或无界执行？
```

四层不是互相替代，而是依赖关系。retrieval 失败通常会导致 answer 失败，但 answer 失败不一定说明 retrieval 失败。E4 会把最早可观测的根因记为 primary failure，后续连锁反应记为 secondary failures。

## 3. 代码地图

### 3.1 数据契约

`app/evaluation/contracts.py`

它定义 `EvaluationCaseDetail`、`LayerEvaluation`、`FailureSignal`、`RateMetric`、`AblationRow` 和整个 run result。Pydantic 使用 `extra="forbid"`，字段拼错或多写字段会直接失败。

为什么重要：评测输出也是产品接口。如果不同脚本随意写 dict，就可能把 0/0 写成 0%，把未运行写成失败，或者让字段名变化后仪表盘静默读错。

### 3.2 通用指标

`app/evaluation/metrics.py`

这里实现 unique-document Hit/Recall/Precision/MRR/nDCG 和固定 seed bootstrap CI。计算前先按第一次出现的 `doc_id` 去重，避免同一文档的多个 chunks 被重复计分。

### 3.3 四层 evaluator

```text
app/evaluation/retrieval.py
app/evaluation/answer.py
app/evaluation/agent.py
app/evaluation/security.py
```

每个 evaluator 都返回同一种 `LayerEvaluation`，包括：

```text
layer       哪一层
applicable  该题是否适用
passed      hard gate 是否通过
metrics     可比较的数字
failures    全部结构化失败信号
```

### 3.4 统一编排

`app/evaluation/suite.py`

`all` suite 对每题做一次 Agent response，answer/agent/security 共用同一个 response，避免三个 evaluator 分别调用模型后得到三份不同答案。retrieval baseline 单独执行，便于隔离“直接检索效果”和“Agent 最终行为”。

### 3.5 运行环境

`app/evaluation/runtime.py`

它有两种明确模式：

```text
deterministic:
  fixed 500/80 chunks + hash-128 embedding + extractive answer
  用于 CI、契约和稳定回归

live:
  active v2 index + configured bge-m3 + qwen2.5:3b
  用于真实本机模型质量和延迟观察
```

live 缺索引或模型时直接失败，绝不偷偷回退 deterministic。否则 manifest 写着 live，实际却跑 fake，实验就失去可信度。

### 3.6 Provenance 与不可覆盖 writer

```text
app/evaluation/run_manifest.py
app/evaluation/writer.py
```

manifest 保存 Git HEAD/branch/dirty、数据集 hash、corpus/index manifest、模型、维度、chunker、top-k、Agent budget、Python、平台、依赖版本和 artifact hashes。敏感 key 会递归替换为 `<redacted>`。

writer 先写 sibling staging，重新读取并校验 JSON/JSONL，再计算 SHA256，最后原子发布。目标 run ID 已存在就失败，没有 `--force`。这样失败实验不会被后一次成功运行覆盖。

### 3.7 CLI

```text
scripts/eval_enterprise_v2.py
scripts/eval_ablation_v2_enterprise.py
scripts/generate_human_review_v2.py
```

第一条跑四层 suite，第二条跑受控消融，第三条把 dev/test 机器结果汇总为 50 条空白人工抽检表。

## 4. Retrieval 指标逐个讲

假设 gold 文档是 `{A, B}`，系统 top-5 unique docs 是 `[A, C, D, B, E]`。

### 4.1 Hit@k

只问 top-k 里有没有至少一个 gold。

```text
Hit@1 = 1，因为第 1 个是 A
Hit@3 = 1，因为前 3 个里有 A
```

缺点：只找到 A、完全漏掉 B，也会是 1。所以 comparison/completeness 不能只看 Hit。

### 4.2 Document Recall@k

公式：

```text
召回到的 gold 数 / gold 总数
```

例子：

```text
Recall@3 = 1/2 = 0.5
Recall@5 = 2/2 = 1.0
```

### 4.3 Full Document Recall@k

这是更严格的 0/1 指标。所有 gold 都找到才是 1。

```text
Full Recall@3 = 0
Full Recall@5 = 1
```

### 4.4 Precision@k

公式：

```text
top-k 中 gold 文档数 / k
```

例子中 `Precision@5 = 2/5 = 0.4`。它衡量给模型的上下文是否混入太多无关文档。

注意：gold 只有一个且固定返回 5 个结果时，Precision@5 理论上最多 0.2。不能脱离 gold 数量解释 0.24 “很低”。

### 4.5 MRR

MRR 只看第一个 gold 的排名：

```text
第一个 gold 在 rank 1: 1/1 = 1
第一个 gold 在 rank 2: 1/2 = 0.5
第一个 gold 在 rank 5: 1/5 = 0.2
```

它适合问“正确答案多久出现”，但不测全部 gold 是否完整。

### 4.6 nDCG@k

nDCG 同时考虑相关文档数量和排序位置。越靠前的 gold 贡献越大，再除以理想排序的 DCG，结果落在 0 到 1。

项目使用 binary relevance：gold 是 1，非 gold 是 0。它比 MRR 更关注多个 gold 的整体排序，但仍不知道文档内容是否真的支持 claim。

### 4.7 Authority 与 ACL

`authority_accuracy` 检查 expected current authoritative docs 是否完整出现。`acl_leakage_count` 检查 forbidden 或当前 UserContext 不可见文档是否进入结果。

ACL 必须是 0 泄漏。它不是可以用 Recall 换取的质量指标，所以所有消融都不允许关闭 ACL。

### 4.8 无 gold 题为什么不算 Recall=0

permission/no-answer 本来就没有 gold。如果把它们写成 Recall=0，系统正确拒答也会拉低召回。因此这类题的 ranking metric 是 `None`，但 ACL 和 answer mode 仍必须检查。

## 5. Answer 指标怎么避免“有引用就算对”

代码明确区分四个集合：

```text
retrieved chunks
response.sources
claim.cited_chunk_ids
verifier-supported cited chunks
```

只有最后一个集合中的 chunk `fact_ids` 才能覆盖 required facts。

### 例子

问题要求 facts `{金额=50000, 报价数=3}`。模型输出两个 claim：

```text
claim-1: 达到 50000 元需要审批，引用 chunk-A
claim-2: 至少 3 家报价，引用 chunk-X
```

如果 chunk-A 含第一个 fact，chunk-X 是无关文档，那么：

```text
atomic_fact_completeness = 1/2 = 0.5
citation_coverage = 2/2 = 1.0
citation_correctness = 1/2 = 0.5
```

所以 citation coverage 100% 不等于 citation correctness 100%，更不等于答案正确。

`expected_answer_signal` 只做词面诊断，不进入 hard correctness。因为“3 个工作日”和“三个工作日”可能词面不同，而无关文本也可能碰巧包含同一个数字。

## 6. Agent 指标为什么不只比 exact sequence

同一道题可能有多条合理路径：

```text
search -> answer
search -> open -> answer
search -> find -> open -> answer
```

如果只要求 exact sequence，第二、三条即使正确也会被判错。因此 E4 把行为拆开：

```text
intent_correct
tool_choice_correct
decomposition_rewrite_correct
retry_rewrite_decision_correct
budget_compliant
stop_reason_correct
trace_complete
final_outcome_correct
```

`exact_trajectory_contract` 仍保留，用于 deterministic regression，但不是 live 唯一 hard gate。

no-answer 是结果，不是输入 intent。例如“制度是否规定 2027 年自动翻倍”可以先按 completeness 搜索，证据不足后得到 `not_found`。E4 第一轮错误地强制 intent=`no_answer`，导致 4 个误报，后来用 RED/GREEN 修正了 evaluator label。

## 7. Failure attribution 是否需要另一个 LLM

当前不需要。每一层已经掌握可验证事实：

```text
gold 是否召回
authority 是否正确
forbidden 是否暴露
required facts 是否被 supported citations 覆盖
trace 是否完整
budget 是否越界
mode/stop 是否匹配
```

因此 failure attribution 使用固定优先级，选择最早可观察失败：

```text
system/runtime
-> evaluation label
-> ACL
-> parse/chunking/metadata
-> query analysis/decomposition
-> retrieval/ranking/diversity
-> evidence/conflict
-> generation/citation
```

优点是便宜、稳定、可复现，并能精确对应代码不变量。缺点是规则无法判断所有语义同义表达，所以项目同时生成 50 条人工表；未来可加入经人工校准的 LLM judge 作为辅助，但不能替代 gold facts、ACL 和运行时硬约束。

## 8. 消融实验在代码里怎么做

`app/evaluation/ablation.py` 不复制五套检索算法，而是给同一个 `HybridRetrievalPipeline` 构造不同 `SearchRequest`：

```text
bm25
dense
hybrid_rrf
hybrid_metadata_temporal
hybrid_diversity_parent
hybrid_optional_reranker
```

固定不变的条件包括 dataset、split、top-k、candidate-k、ACL、index 和预算。只有被研究的变量改变，这样结果才有因果解释。

workflow 消融比较：

```text
Fixed RAG:
  一次原问题 search，然后直接预测 answered/not_found

Bounded Agent:
  按 required aspects 搜索，必要时 open，并依据 evidence ledger 停止
```

质量以外同时记录 latency、tool calls、context chars、model calls。Agent 提高 outcome 但增加成本时，报告必须同时展示两边。

## 9. 本轮三个实验层次

### 9.1 Deterministic dev

24 cases，hash-128，extractive。修正 evaluator label 后四层 24/24。它证明 contract 和工作流在固定替身上可重复，不证明真实模型准确率。

### 9.2 Deterministic frozen test

28 cases，开发冻结后校验 SHA256 再正式运行。四层 28/28；消融中 metadata/temporal 与 bounded Agent 维持 1.0。test 结果没有用于 E4 内继续调参。

### 9.3 Live dev

真实 active index：

```text
index run: 20260716T135632Z_7aec4b9_live_bge_m3_fixed
embedding: bge-m3, 1024 dimensions
chat: qwen2.5:3b
chunks: 64 fixed chunks
```

第一次 live suite 只有 6/24，因为 18 个 answered cases 全部发生 Ollama grammar 400。修复采样 schema 后第二次为 23/24：retrieval/security 24/24，answer/agent 23/24。唯一失败保留，不覆盖。

## 10. Ollama JSON Schema 故障详细解释

### 症状

评测不是抛到命令行，而是每个 answered case 返回 `mode=system`。failure report 统一显示 `system_runtime`。

### 最小复现

直接把 `GENERATION_RESPONSE_FORMAT` 传给 `/api/chat`，Ollama 返回：

```text
HTTP 400
Failed to initialize samplers: failed to parse grammar
```

### 根因

原 schema 同时包含：

```text
minLength/maxLength
minItems/maxItems
pattern
additionalProperties
```

当前 Ollama/llama.cpp grammar parser 无法编译这组约束。问题发生在采样器初始化，不是 bge-m3 检索，也不是答案事实错误。

### 修复位置

`app/agent/generation_v2.py` 的 `GENERATION_RESPONSE_FORMAT` 只保留 Ollama 可接受的结构：

```text
type
properties
items
required
```

完整严格校验仍在 `GeneratedClaim` 和 `GeneratedAnswer` Pydantic 模型中：长度、claims 数量、唯一 claim ID、S<number> 格式、未知字段仍会在应用侧拒绝。

### 测试位置

`tests/agent_v2/test_generation_v2.py::test_ollama_sampling_schema_uses_only_grammar_compatible_constraints`

测试先 RED，证明原 schema 含不兼容关键字；生产代码最小修改后，generation 文件 10 tests 全部 GREEN。原来的非法 JSON、空 claims、S999 和模型异常 fail-closed 测试也继续通过。

### 结果

正式旧 run 6/24，修复 run 23/24。单题重放剩余失败时又通过，所以不继续为刷分加重试，而把它记录为小模型结构输出偶发不稳定。E5 再决定是否做一次有界 generation retry 和结构化错误 telemetry。

## 11. Artifact 怎么读

每个目录下：

```text
manifest.json
  这次到底跑了什么环境和配置

summary.json
  四层总体指标、CI、probe 结果

details.jsonl
  每题每层 metrics 和 failure signals

failures.csv
  只列失败，便于 Excel 筛选

metrics_by_category.csv
  按 task type/tag 看哪类题退化

ablation.csv
  每个变体的质量与成本

human_review.csv
  机器预填上下文，人工判断列为空
```

阅读失败的顺序：先看 `summary.primary_failure_counts`，再看 `failures.csv` 找 case ID，最后去 `details.jsonl` 看各 layer。不要先翻最终 answer 猜根因。

## 12. 人工抽检要怎么做

当前 `20260716T135632Z_7aec4b9_human_review/human_review.csv` 有 50 行，8 个判断列共 400 个单元格全部为空。建议本人按下面顺序审核：

1. 先审核所有 machine failures。
2. 再覆盖 fact、comparison、completeness、version、permission、no-answer。
3. 逐条看 system answer 与 visible sources，不参考机器 pass 先做判断。
4. 填“答案正确/完整/引用支持/应拒答/越权/主要失败阶段/说明”。
5. 统计人与规则不一致的 case，反向改 evaluator，而不是直接改答案。

人工审核完成前，不能把 28/28 写成“人工 factuality 100%”。

## 13. 结果数字怎么讲才诚实

可以说：

```text
在 28-case frozen synthetic deterministic test regression 上，
metadata/temporal retrieval 和 bounded Agent 均达到 28/28 layer pass，
ACL leakage 为 0；live dev 修复 Ollama schema 集成故障后为 23/24。
```

不能说：

```text
系统生产准确率 100%
bge-m3 一定比 BM25 好
RRF 一定提升
parent-child 已证明有效
引用检查等于语义蕴含
人工审核已完成
```

## 14. 面试高频问题与参考答案

### Q1：为什么不只报一个 accuracy？

因为 Agentic RAG 是多阶段系统。一个最终错误可能来自检索、版本选择、生成、引用或工具停止。单一 accuracy 不能指导修复，分层指标才能做 failure attribution 和消融。

### Q2：Precision@5 低是不是系统很差？

不一定。若每题只有一个 gold 且固定返回 5 个结果，理论上最高就是 0.2。必须结合 gold 数、Recall@5、context budget 和 invalid extras 一起解释。

### Q3：Hit@5 和 Recall@5 有什么区别？

Hit 只要命中任意一个 gold 就是 1；Recall 衡量覆盖了多少 gold。跨文档比较题可能 Hit=1、Recall=0.5，所以需要 full recall。

### Q4：MRR 与 nDCG 有什么区别？

MRR 只看第一个正确文档的位置；nDCG 关注多个相关文档的整体排序，并对靠前位置给更高权重。

### Q5：为什么先按 doc_id 去重？

因为一个长文档会切成多个 chunks。不去重会把同一文档的多个命中当成多个正确文档，虚增 precision/recall，也会挤占其他 gold 文档位置。

### Q6：为什么 no-answer 不进入 retrieval recall 分母？

它没有 gold 文档，0/0 不应被写成 0。它仍接受 ACL、mode、source-free 和 stop reason 检查。

### Q7：为什么不用 LLM judge 做所有判断？

gold doc、fact ID、ACL、预算、工具序列和引用可见性都有确定性真值，用代码判断更稳定、便宜、可复现。语义自然度和同义改写适合人工或校准后的 LLM judge 作为补充。

### Q8：规则评估会不会误判？

会，所以 lexical signal 不进入 hard correctness，并生成 50 条人工抽检表。规则负责可验证硬约束，人工负责语义和业务判断，两者要做 disagreement analysis。

### Q9：为什么 exact tool sequence 不是 live hard gate？

因为同一任务可能有多条正确轨迹。E4 单独评分是否调用必要工具、是否完成 decomposition、是否越预算和是否正确停止，exact sequence 只做 deterministic contract。

### Q10：怎么保证 test 没被用来调参？

E1 冻结 `test.json` SHA256；E4 先完成 dev 代码、消融和全量门禁，再校验 hash 后正式运行 test。test run 后 E4 不依据结果修改参数。

### Q11：为什么保存 dirty Git 状态？

因为当前 E0-E4 前置尚未提交。仅保存 HEAD 不足以复现，manifest 必须明确 `dirty=true`，避免把 artifact 错归因到基线 commit。

### Q12：为什么 run ID 不能覆盖？

覆盖会抹掉失败和调试顺序，导致 selection bias。不可覆盖目录让 before/after 都存在，也能用 artifact hash 验证结果未被改写。

### Q13：消融怎样保证公平？

固定 dataset/split/top-k/candidate-k/index/ACL/budget，只改变一个检索开关或工作流。质量和成本一起记录，且未运行的 reranker 写 NOT RUN，不写 0。

### Q14：本轮哪个组件贡献最大？

在 deterministic test 与 live dev 中，metadata/temporal filtering 都把 Recall@5、authority 和 retrieval pass 提到 1.0。bounded Agent 主要把 fixed RAG 的四个 unsupported no-answer 从 answered 改为 not_found。

### Q15：为什么 bge-m3 dense 反而低于 BM25？

当前数据很小、政策标题和数字词面强，dense 单独检索对 multi-document coverage 不稳定。它的 MRR 更高但 Recall@5 更低，说明首个正确文档靠前，不代表所有所需文档都覆盖。不能用一个小 synthetic dev 推广到一般语料。

### Q16：RRF 为什么不是稳定提升？

RRF 只能融合已有排名，不能自动修复候选范围、版本和 metadata 错误。frozen test 上 hash dense Recall@5 甚至高于 RRF；真正稳定的是先把查询约束映射到 filters。

### Q17：Agent 提升是否值得？

它把 no-answer outcome 从 0.8333 提到 1.0，但 live 平均耗时从约 186ms 增到 2521ms，工具调用从 24 增到 42，context 也增加。是否值得取决于错误回答的业务成本，E5 还要做并发 load profile。

### Q18：Ollama grammar 故障怎么定位？

先看分层结果确认 retrieval 全过、answered 全 system；再最小化为一次 `/api/chat`，得到 400 `failed to parse grammar`；缩减 schema 后调用成功；最后加 RED 测试并最小修改生产 schema，端到端从 6/24 提到 23/24。

### Q19：移除 schema 约束是否降低安全性？

只移除了 Ollama 采样 grammar 里的高级关键字，应用侧 Pydantic 严格校验仍保留。模型输出不合规时返回 source-free system，不会把未验证答案继续交付。

### Q20：为什么不马上给剩余失败加无限重试？

无限重试会放大延迟、成本和不可预测性。当前先保留 fail-closed 证据；若 E5 加重试，也只能一次有界重试，记录原因和调用数，并通过 load/security gate。

### Q21：bootstrap `[1,1]` 是否代表真实准确率 100%？

不是。24 或 28 个样本全部为 1 时，nonparametric bootstrap 只能重复抽到 1，所以区间也是 `[1,1]`。它只描述当前样本没有变异，不代表总体无误差。

### Q22：为什么还需要人工审核？

代码可以验证 fact/source/ACL/trace，却无法完全判断表达是否自然、语义是否等价、答案是否满足真实业务期望。人工审核也是校准未来 LLM judge 的基准。

## 15. 你应该亲手完成的练习

1. 从 `test_ablation/ablation.csv` 手算一个 variant 的 Recall@5 与失败数。
2. 从 `live_dev_suite_r01/details.jsonl` 找唯一失败，解释四层为什么分别通过或失败。
3. 打开 `generation_v2.py`，指出 sampling schema 与 Pydantic validation 的边界。
4. 打开 `suite.py`，证明同一题的 answer/agent/security 共用一次 Agent response。
5. 打开 `writer.py`，按 staging、validate、hash、manifest、rename 顺序画写入流程。
6. 本人填写 50 条 `human_review.csv`，统计 rule-human disagreement。

能独立完成这六项，才算真正掌握 E4，而不是只记住 23/24 和 28/28。

## 16. 设计来源与本项目取舍

- OpenAI 的 agent 实践指南强调先建立 eval baseline、分层 guardrails、失败阈值和 human intervention。本项目把它落成 frozen dataset、四层 security checks、bounded budget 和空白人工抽检，而不是照搬某个 SDK：[A practical guide to building AI agents](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/)。
- Anthropic 的 agent eval 文章强调 Agent 多步工具调用和状态变化使评测更难，需要组合 grader 类型。本项目因此同时使用 code-based hard gates、trajectory metrics、cost metrics 和 human review：[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)。
- LangSmith 官方文档把 Agent eval 分为 final response、single step 和 trajectory，并指出 exact trajectory 可能错罚多条合理路径。本项目据此保留 exact contract 作为辅助，同时把 intent/tool/decomposition/budget/stop 分开评分：[Application-specific evaluation approaches](https://docs.langchain.com/langsmith/evaluation-approaches)。

这些资料提供方法论，不是代码来源。`app/evaluation/*`、CLI、writer、failure taxonomy 和本地 artifacts 都是按当前仓库 contract 独立实现的。
