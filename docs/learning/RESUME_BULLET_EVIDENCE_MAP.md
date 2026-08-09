# 简历 Bullet 与证据映射

每条项目描述都要能回答：数据是什么、分母是多少、代码在哪里、如何测试、指标
表示什么、什么不能推出。下列五条是优先候选。

全文中的 `Recall@5` 都是检索 Recall@5，不是答案或业务准确率。

## 1. WixQA 外部检索

**中文原句：** 在 200 条 WixQA ExpertWritten 匿名真实客服问题上对比 BM25、
BGE-M3 Dense 与等权 RRF；Dense 将 Article Recall@5 从 42.75% 提升至 66.42%、
nDCG@5 从 32.15% 提升至 52.16%，p95 由 151.8 ms 增至 157.4 ms。

**English:** Benchmarked BM25, BGE-M3 Dense, and equal RRF on 200 anonymized
real-support WixQA ExpertWritten questions; Dense improved Article Recall@5
from 42.75% to 66.42% and nDCG@5 from 32.15% to 52.16%, with p95 moving from
151.8 to 157.4 ms.

- 代码：`app/external_datasets/wixqa.py`、`wixqa_retrieval.py`；
  `scripts/eval_wixqa_retrieval.py`
- 测试：`tests/external_datasets/test_wixqa_public_evidence.py`
- 数据/协议：WixQA revision `d662dc4`；固定 public-label protocol
- 执行 SHA：`234734657fe354a0ecd767022c6f7c22cdc329da`
- 公开证据：`docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json`
- 限制：检索指标，不是答案准确率；标签公开且已消费，不是 blind test
- 禁止扩大：不得说“RAG 准确率 66.42%”或“SOTA”

追问“为什么 RRF 变差？”：等权 RRF 让明显更弱的 BM25 获得同等影响，把 Dense
正确结果挤出 Top-5，并把 p95 提高到 304.6 ms，因此按门禁拒绝该候选。

## 2. Clean reproduction

**中文原句：** 将数据 revision、模型 digest、冻结协议和消费状态写入证据合同；在
全新目录重建 11,975 个 WixQA chunk，63 项质量指标在零容差下完全复现。

**English:** Bound dataset revision, model digest, frozen protocol, and
consumption state into an evidence contract; rebuilt 11,975 WixQA chunks in
fresh roots and reproduced 63 quality values exactly at zero tolerance.

- 代码：`scripts/reproduce_wixqa_retrieval.py`、
  `scripts/verify_wixqa_clean_reproduction.py`
- 测试：`tests/external_datasets/test_wixqa_public_evidence.py`
- 数据/协议：官方 LF manifest + canonical transport equivalence + protocol v2
- 执行 SHA：`4d07d6a4f14bf4eaded8ff1bd6987b8a094dc064`
- 公开证据：`docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json`
- 限制：本地 clean regression replay，不是第三方复现或新 holdout
- 禁止扩大：不得说“独立机构复现”

追问“为什么第一次失败？”：历史 Windows 副本是 CRLF，官方下载是 LF，每条 JSONL
多 1 byte。代码没有忽略哈希，而是证明 canonical JSON row 与派生 ID 完全相同，
再冻结 transport-corrected v2；检索参数和零容差均未改变。

## 3. 51 万行 FTS5

**中文原句：** 将预计 36.60 GiB 内存的 Python BM25 替换为可恢复 SQLite FTS5，
以约 1.83 GiB 峰值内存在 231.35 秒内构建 511,962 行、9 类来源、1.37 GiB 索引。

**English:** Replaced an estimated 36.60 GiB in-memory Python BM25 design with
resumable SQLite FTS5, building a 1.37 GiB index over 511,962 rows from nine
source types in 231.35 seconds at about 1.83 GiB peak RSS.

- 代码：`app/external_datasets/enterprise_rag_bench_fts.py`
- 测试：`tests/external_datasets/test_enterprise_rag_bench_fts.py`
- 协议：single-writer offline builder + verified staging + atomic activation
- 执行 SHA：`955d86f1ca244bc90025c89806fd786f978b98ff`
- 公开证据：`docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json`
- 限制：词法检索；Recall@5 60.3741%，record-aware sensitivity 60.2677%
- 禁止扩大：不得说“51 万文档系统准确率 60.37%”或“分布式在线索引”

追问“为什么不用 Elasticsearch？”：已测瓶颈是单机 Python 对象内存，不是集群
分片或高可用。FTS5 是最小可验证方案；真实多机写入、HA、在线扩缩容出现后再选型。

## 4. Retrieved-content Guard

**中文原句：** 在固定 garak 子集上，Guard 将 ASR 从 4/12 降到 0/12、上下文暴露
从 12/12 降到 0/12，平均扫描 1.42 ms。

**English:** On a pinned garak subset, the Guard reduced ASR from 4/12 to 0/12
and context exposure from 12/12 to 0/12 at 1.42 ms mean scan latency.

- 代码：`app/security/retrieved_content_guard.py` 及 admission data flow
- 测试：`tests/security/test_retrieved_content_guard.py`
- 协议：同攻击集、同模型、同检索，只切换 Guard OFF/ON
- 执行 SHA：`1e7ea0c9fbd037277fc5feaa733d2063d315e63a`
- 公开证据：`docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json`
- 限制：12 攻击 + 2 benign 的窄子集
- 禁止扩大：不得说“100% 防注入”或“通过完整 garak”

追问“为什么不用 LLM 判断注入？”：Guard 是 host-side admission boundary，需要低
延迟、可复现和 fail-closed；LLM 可用于离线语义研究，不能单独决定是否把原文送入
Controller。规则也有误报风险，所以同时报告 benign controls。

## 5. Bounded Agent 与负结果门禁

**中文原句：** 实现 host 控制的 search/find/open Agent、ACL、工具预算、Evidence
Ledger 与 citation gate；在同检索器成对评测中发现 Agent 无外部质量增益并阻止升级。

**English:** Implemented a host-controlled search/find/open Agent with ACL,
tool budgets, evidence ledger, and citation gate; paired evaluation found no
external quality gain and blocked promotion.

- 代码：`app/agent/controller_v2.py`、`app/agent/tools_v2.py`、
  `app/agent/citation_verifier.py`
- 测试：`tests/agent_v2/`、`tests/security/`
- 数据/协议：WixQA 同 retriever control/candidate，400 cases
- 执行 SHA：`07b156ed4d1b4e7ff24a06aac7a8d8b41630e03b`
- 公开证据：`docs/enterprise_eval/evidence/wixqa_agent_public_v1.json`
- 限制：证明机制与工程决策，不证明 Agent 提升质量
- 禁止扩大：不得写“Agent accuracy 100%”或“自适应检索已上线”

追问“负结果为什么值得讲？”：它证明用 trace 和 paired metrics 决定是否上线，避免
为了技术栈保留无收益链路。当前 controller 的 find/open 未被真实问题触发，应该等待
新未消费多文档数据，而不是继续叠框架。
