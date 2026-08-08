# 简历 Bullet 与证据映射

每条简历描述都必须能回答：数据是什么、代码在哪里、指标是什么、对照是谁、
限制是什么。面试官追问时不要只背数字。

## Bullet 1：真实客服知识库检索

**可写描述**

> 在 WixQA ExpertWritten 200 条匿名真实客服问题上，对比 BM25、BGE-M3 Dense
> 与 RRF；Dense 将 Article Recall@5 从 42.75% 提升至 66.42%，nDCG@5 从
> 32.15% 提升至 52.16%，p95 仅由 151.8 ms 增至 157.4 ms。

**证据与代码**

- 数据：WixQA revision `d662dc42479c14e202eccd832f8c4b66a035c4cc`。
- 代码：`app/external_datasets/wixqa.py`、`wixqa_index.py`、`wixqa_eval.py`。
- 协议：`docs/enterprise_eval/evidence/WIXQA_RETRIEVAL_PROTOCOL_V1.json`。
- 聚合结果：`wixqa_retrieval_baseline_public_v1.json`。
- 执行 SHA：`234734657fe354a0ecd767022c6f7c22cdc329da`。

**为什么这个指标合理**

检索器的任务是把 gold article 放进有限上下文，所以 Recall@5 衡量“证据有没有
机会被模型看到”，nDCG@5 衡量“证据是否排得足够靠前”。它们不等于答案正确率。

**可能追问**

问：为什么 RRF 反而更差？

答：等权融合假设两个检索器质量和互补性相近，但本数据上 Dense 明显更强。
BM25 的较差排名通过 RRF 获得同等影响，导致 Dense 的正确文档被挤出 Top-5；
同时需要执行两套检索，p95 接近翻倍。因此根据 paired result 拒绝等权 RRF。

问：这算真实准确率吗？

答：不是。这是公开标签固定外部集上的 article retrieval 指标。问题来源真实，
但不是隐藏盲测，也没有在本轮测生成答案正确率。

## Bullet 2：51 万文档可落地索引

**可写描述**

> 面向 EnterpriseRAG-Bench 511,962 条异构企业文档，将预计 36.60 GiB 的 Python
> 内存 BM25 改为可恢复、原子激活的 SQLite FTS5 索引；以约 1.83 GiB 峰值内存
> 在 231.35 秒构建 1.37 GiB 全量索引，并建立 60.37% Recall@5 词法基线。

**证据与代码**

- 代码：`app/external_datasets/enterprise_rag_bench_fts.py`。
- 构建入口：`scripts/build_enterprise_rag_bench_fts.py`。
- 评测入口：`scripts/eval_enterprise_rag_bench_retrieval.py`。
- 容量证据：`enterprise_rag_bench_capacity_public_v1.json`。
- 结果证据：`enterprise_rag_bench_bm25_public_v1.json`。
- 执行 SHA：构建/评测 `955d86f1ca244bc90025c89806fd786f978b98ff`。

**为什么这是工业化内容**

真实系统不仅要“算法能写出来”，还要能处理中断、版本错配、内存上限和半成品
索引。Checkpoint 解决长任务恢复；哈希绑定防止接错数据版本；staging + 验证 +
active pointer 解决半成品被线上读取；故障注入测试证明恢复路径不是纸面设计。

**可能追问**

问：60.37% 好不好？

答：它是全语料、无 source oracle 的 B0 Recall@5，不是最终答案准确率。优点是
规模和协议真实；缺点是 semantic 只有 36%，多文档完整率只有 28.26%，p95 1.82
秒。它的价值是建立可信基线并定位下一瓶颈，而不是声称已经达到生产质量。

问：为什么不直接做向量索引？

答：容量测量显示约 170 万 chunk，按当前速率嵌入约 11.39 小时，cache+FAISS
约 12.99 GiB。先用低风险 FTS5 证明全量数据、ID、评测和恢复链路，再决定是否
投入一次受控 Dense 实验，避免把长时间计算当成默认动作。

## Bullet 3：用负结果约束 Agent

**可写描述**

> 构建同 retriever 的 RAG/Agent 成对评测；在 400 条 WixQA 问题上发现现有
> controller 的 `find/open` 调用均为 0、检索无增益、多文章引用完整率为 0%，
> 且 p95 增加 1.47-1.59 倍，因此阻止该 Agent 路径升级。

**证据与代码**

- 代码：`app/external_datasets/wixqa_agent_eval.py`。
- 执行：`scripts/eval_wixqa_agent.py`。
- 证据：`docs/enterprise_eval/evidence/wixqa_agent_public_v1.json`。
- 执行 SHA：`07b156ed4d1b4e7ff24a06aac7a8d8b41630e03b`。

**为什么负结果有价值**

Agentic 不等于工具类存在。必须观察真实 trace 中工具是否被调用、是否获得额外
证据、质量是否提高、成本是否合理。这里链路无报错，但策略没有展开检索，说明
瓶颈在 controller/aspect 分析，而不是基础设施。拒绝升级比继续包装更可信。

**可能追问**

问：为什么引用完整率会变成 0？

答：规则分析器只产生一个 required aspect，response builder 最终选择一个来源；
而 open 分支只对显式 completeness intent 开启，真实客服问法没有触发。因此多
文章问题即使初始 Top-5 含多个 gold，最终也被压缩成单引用。

问：接下来怎么改？

答：不能直接加更多 Agent。先用 development-safe 多文档样本验证“required
aspects 分解 + 条件 open”能否提高 citation completeness，再与相同 B2 检索做
paired comparison；达不到质量/延迟门槛则继续默认关闭。

## 禁止写法

- “RAG 准确率 97.88%”：这是 WixQA Synthetic development Recall@5。
- “Agent 回答准确率 100%”：只是 answered rate，没测语义正确性。
- “51 万文档系统准确率 60.37%”：这是检索 Recall@5。
- “Evidence Ledger 解决冲突”：没有外部 ON/OFF answer experiment。
- “已完成 HERB / source-aware / 企业 Dense”：这些状态都是 `NOT_RUN`。
