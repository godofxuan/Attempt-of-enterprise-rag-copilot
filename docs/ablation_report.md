# E4 Enterprise Agentic RAG Ablation Report

最后更新：2026-07-16

## 1. 实验边界

Artifact：`eval_runs/20260716T135632Z_7aec4b9_dev_ablation/`

固定条件：E1 demo dev 24 cases、answered gold 18、top-k 5、candidate-k 20、fixed 500/80 chunks、stable hash-128 embedding、extractive response、Agent budget 默认值、ACL 永远开启、model calls 0。

这是 synthetic deterministic dev ablation，不是真实 bge-m3/qwen 质量，也不是 frozen test 结果。延迟是本机 Python 小样本 wall-clock，只能用于当前 run 内相对观察。

## 2. Retrieval variants

| Variant | Recall@5 | Full recall@5 | MRR | nDCG@5 | Precision@5 | Authority | Pass | Avg ms | Context chars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.8333 | 0.7222 | 0.3769 | 0.4778 | 0.1889 | 0.7222 | 0.7917 | 0.951 | 14,444 |
| Dense hash-128 | 0.8889 | 0.8333 | 0.6296 | 0.6792 | 0.2111 | 0.8333 | 0.8750 | 0.865 | 12,425 |
| Hybrid RRF | 0.9444 | 0.8889 | 0.6130 | 0.6789 | 0.2222 | 0.8889 | 0.9167 | 0.966 | 13,206 |
| Hybrid + metadata/temporal | 1.0000 | 1.0000 | 1.0000 | 0.9955 | 0.2444 | 1.0000 | 1.0000 | 0.805 | 10,019 |
| Hybrid + diversity/parent | 1.0000 | 1.0000 | 1.0000 | 0.9955 | 0.2444 | 1.0000 | 1.0000 | 0.807 | 10,019 |
| Hybrid + reranker | NOT RUN | | | | | | | | |

所有 retrieval variants 的 ACL leakage count 为 0。

### 解释

1. BM25 的五个失败主要是 multi-document comparison，另有一个 completeness；说明单次词项匹配难以覆盖所有文档。
2. hash dense 改善了排名但仍有三个失败。它不是 bge-m3，不能据此宣称 dense 模型质量。
3. hybrid RRF 将 document recall@5 提到 0.9444，但两个 comparison 仍未完整覆盖。
4. metadata/temporal filters 把当前 dev 的 authority/full recall 提到 1.0，说明 E3 QueryAnalysis filters 在该 synthetic 数据上有可观测贡献。
5. diversity/parent 与 metadata variant 的 retrieval 指标完全相同。当前 index 是 fixed chunks，没有 parent context；因此不能宣称 parent expansion 带来提升。它在本 run 中只证明“没有回归”。
6. 没有重复 failure 证明需要 reranker，因此 reranker admission 失败，保持未实现/默认关闭。

## 3. Workflow comparison

| Workflow | Outcome accuracy | Doc recall@5 | Full recall@5 | Avg ms | Tool calls | Context chars | Model calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fixed RAG | 0.8333 | 1.0000 | 1.0000 | 0.991 | 24 | 10,019 | 0 |
| Bounded Agentic retrieval | 1.0000 | 1.0000 | 1.0000 | 4.685 | 42 | 14,112 | 0 |

Fixed RAG 的四个失败全部是 no-answer：一次 search 命中相关政策后直接预测 answered。Bounded Agent 通过 query-anchor/evidence ledger 把四题停止为 not_found。

收益不是免费的：Agent 增加 18 次工具调用、4,093 context chars，平均本机 deterministic latency 约为 fixed 的 4.7 倍。由于 n=24、无模型调用且计时小于 5ms，不做统计显著性或生产延迟宣称。

## 4. Failure IDs

```text
BM25:
  compare_finance_travel_security_incident
  compare_hr_compensation_legal_contract
  compare_hr_remote_finance_travel
  complete_customer_refund
  compare_legal_contract_hr_remote

Dense:
  compare_hr_compensation_legal_contract
  fact_procurement_vendor_2026_threshold
  compare_legal_contract_hr_remote

Hybrid RRF:
  compare_hr_compensation_legal_contract
  compare_legal_contract_hr_remote

Fixed RAG:
  missing_finance_travel
  missing_customer_refund
  missing_legal_contract
  missing_security_incident
```

## 5. 当前决策

- production E3 path 保持 hybrid + QueryAnalysis metadata/temporal + diversity/parent；
- 不加入 reranker；
- 不把 fixed-parent equality 宣传为 parent-child 无效，因为本实验 index 本来就是 fixed；
- frozen test 只验证开发冻结后的行为，不再用于调参；
- live bge-m3/qwen run 必须单独标注模型、index 和环境。

## 6. Deterministic frozen-test 消融

Artifact：`eval_runs/20260716T135632Z_7aec4b9_test_ablation/`

固定条件与 dev deterministic 相同，但 split 是开发决策冻结后才首次正式读取的 28-case test，其中 answered gold 为 21。test 文件 SHA256 校验值为 `556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338`。本节结果在 E4 内不再用于调参。

| Variant | Recall@5 | Full recall@5 | MRR | nDCG@5 | Precision@5 | Authority | Pass | Avg ms | Context chars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.8095 | 0.7619 | 0.3143 | 0.4292 | 0.1714 | 0.7619 | 0.8214 | 1.020 | 16,304 |
| Dense hash-128 | 0.9048 | 0.8095 | 0.3960 | 0.5110 | 0.2000 | 0.8095 | 0.8571 | 0.614 | 14,329 |
| Hybrid RRF | 0.8333 | 0.7619 | 0.4024 | 0.4933 | 0.1905 | 0.7619 | 0.8214 | 1.062 | 14,895 |
| Hybrid + metadata/temporal | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.2381 | 1.0000 | 1.0000 | 0.784 | 11,551 |
| Hybrid + diversity/parent | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.2381 | 1.0000 | 1.0000 | 0.863 | 11,551 |
| Hybrid + reranker | NOT RUN | | | | | | | | |

| Workflow | Outcome accuracy | Doc recall@5 | Full recall@5 | Avg ms | Tool calls | Context chars | Model calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fixed RAG | 0.8571 | 1.0000 | 1.0000 | 0.997 | 28 | 11,551 | 0 |
| Bounded Agentic retrieval | 1.0000 | 1.0000 | 1.0000 | 4.970 | 47 | 15,732 | 0 |

这个结果没有支持“RRF 永远优于 dense”。在 frozen test 上，hash dense 的 Recall@5 是 0.9048，RRF 反而是 0.8333；两者失败集合也不相同。稳定的收益来自 QueryAnalysis 产生的 metadata/temporal filters。Fixed RAG 的四个失败仍全部是 unsupported no-answer，Bounded Agent 通过 evidence gate 正确停止。

## 7. Live dev 消融

Artifact：`eval_runs/20260716T135632Z_7aec4b9_live_dev_ablation/`

运行条件：active index `20260716T135632Z_7aec4b9_live_bge_m3_fixed`、`bge-m3` 1024D、FAISS `IndexFlatIP`、`qwen2.5:3b`、top-k 5、candidate-k 20、24-case dev。manifest 记录 158 次 embedding 调用、18 次 generation 调用、176 次总模型调用。这里的 wall-clock 包含本机 Ollama 推理，仍不是并发生产延迟。

| Variant | Recall@5 | Full recall@5 | MRR | nDCG@5 | Precision@5 | Authority | Pass | Avg ms | Context chars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.8333 | 0.7222 | 0.3769 | 0.4778 | 0.1889 | 0.7222 | 0.7917 | 23.718 | 14,444 |
| Dense bge-m3 | 0.7222 | 0.6111 | 0.6389 | 0.6276 | 0.1667 | 0.6111 | 0.7083 | 192.666 | 16,251 |
| Hybrid RRF | 0.8333 | 0.7778 | 0.6713 | 0.6875 | 0.2000 | 0.7778 | 0.8333 | 194.322 | 15,123 |
| Hybrid + metadata/temporal | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.2444 | 1.0000 | 1.0000 | 189.651 | 10,026 |
| Hybrid + diversity/parent | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.2444 | 1.0000 | 1.0000 | 187.488 | 10,026 |
| Hybrid + reranker | NOT RUN | | | | | | | | |

| Workflow | Outcome accuracy | Doc recall@5 | Full recall@5 | Avg ms | Tool calls | Context chars | Model calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fixed RAG | 0.8333 | 1.0000 | 1.0000 | 186.093 | 24 | 10,026 | 22 |
| Bounded Agentic retrieval | 1.0000 | 1.0000 | 1.0000 | 2520.830 | 42 | 14,024 | 44 |

### Live 结果怎么解释

1. bge-m3 dense 的 MRR 高于 BM25，表示首个正确文档通常排得更靠前；但 Recall@5 和 full recall 更低，表示 multi-document/completeness 覆盖更差。一个指标好不等于整个检索更好。
2. RRF 改善 MRR/nDCG，但没有解决所有 current-authority 与跨政策覆盖问题。
3. metadata/temporal 把可选候选空间收缩到正确 tenant/region/version/policy 范围，在当前 dev 上把 recall、authority 和 pass 同时提高到 1.0。它是本轮最有证据的 retrieval 增益。
4. diversity/parent 与 metadata 完全相同，是因为 active index 使用 fixed chunks，`parent_chunk_count=0`。这只能说明没有回归，不能证明 parent expansion 有收益。
5. Agent 的 outcome 收益来自 no-answer 停止判断，但代价是更多工具、上下文和生成调用；live 平均耗时约为 fixed 的 13.5 倍。是否接受该成本必须由业务错误成本和 E5 load profile 决定。

## 8. 失败集合与因果结论

Deterministic test 的主要失败：

```text
BM25: 5 cases
Dense hash-128: 4 cases
Hybrid RRF: 5 cases
Fixed RAG: 4 unsupported no-answer cases
Metadata/temporal: 0
Bounded Agent: 0
```

Live dev 的主要失败：

```text
BM25: 5 cases
Dense bge-m3: 7 cases
Hybrid RRF: 4 cases
Fixed RAG: 4 unsupported no-answer cases
Metadata/temporal: 0
Bounded Agent: 0
```

因此本项目当前可以说：在受控 synthetic benchmark 上，metadata/temporal filtering 和 bounded evidence stopping 各自对 retrieval 与 no-answer outcome 有可重复贡献。当前不可以说：bge-m3 在一般企业语料上优于 BM25、RRF 必然提升、parent-child 已证明有效、reranker 已评估，或这些毫秒数代表生产 SLA。

## 9. 与全层 live suite 的关系

消融回答“去掉某个组件会怎样”，全层 suite 回答“最终检索、答案、Agent、安全分别怎样”。修复 Ollama schema 兼容性后，live dev suite `20260716T135632Z_7aec4b9_live_dev_suite_r01` 为 23/24；retrieval/security 各 24/24，answer/agent 各 23/24。唯一正式失败是一次结构化生成 fail-closed；单题重放通过，所以保留为小模型偶发结构输出不稳定证据，不覆盖也不改分。
