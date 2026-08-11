# Bullet Candidates

Select at most three primary bullets plus two backups for one target role.

## Version A: AI Application / RAG / Agent

Primary:

1. 实现由 Python 主机控制的企业知识 RAG 路径，将身份/ACL、检索内容准入、工具预算、Evidence Ledger 与引用过滤拆成可测试边界，避免由模型文本扩权或直接发布无证据结论。
2. 在 200 道 WixQA ExpertWritten 外部检索题上对比 BM25 与 BGE-M3 Dense，使 Recall@5 从 42.75% 提升至 66.42%、nDCG@5 从 32.15% 提升至 52.16%，并明确区分检索指标与答案正确率。
3. 建立分层评测与发布门禁，拒绝完整案例修复数为 0、引用精确率下降 5.83pp 且 p95 延迟增至 1.859x 的多文档 Agent 候选，保持生产默认路径不变。

Backups:

4. 在固定 12 攻击样本的 garak 子集上执行 Guard OFF/ON 成对评测，将观测 ASR 从 4/12 降至 0/12、上下文暴露从 12/12 降至 0/12，平均扫描耗时 1.42 ms。
5. 从全新本地目录重建 11,975 个 BGE-M3 向量与索引，以零容差复现 63/63 个冻结检索质量值，隔离历史缓存对结论的影响。

## Version B: AI Evaluation / GenAI Evaluation

Primary:

1. 构建覆盖 retrieval、Agent action、citation、security、latency 与失败归因的冻结评测证据链，为数据集、协议、模型、执行 SHA、逐题结果和公开聚合建立可复算绑定。
2. 在 200 道 WixQA 检索题上完成 BM25/Dense/RRF 同协议消融，验证 Dense Recall@5 66.42% 高于 BM25 42.75% 与等权 RRF 59.25%，据质量和延迟门禁拒绝无收益融合方案。
3. 对 20 道已消费多文档题做 first-loss attribution，将失败定位为 Top-20 召回 7 题、Top-5 排序 10 题、最终证据选择 3 题，并拒绝零完整案例修复的后续候选。

Backups:

4. 设计 clean-root 回放与独立 verifier，重新下载数据并重建 11,975 个向量，63 个冻结质量比较在绝对容差 0.0 下全部一致。
5. 为间接提示词注入建立同模型/同输入 Guard OFF/ON 评测，在固定 garak 子集报告攻击、暴露、benign utility 与扫描延迟，并公开小样本边界。

## Version C: Python Backend / AI Platform

Primary:

1. 将超出单机内存预算的 Python BM25 方案替换为可恢复的 SQLite FTS5 构建路径，在单机处理 511,962 条/9 类记录，231.35 秒生成并原子激活 1.37 GiB 索引，峰值内存约 1.83 GiB。
2. 实现 single-writer staging、校验和/行数/完整性检查、immutable target 与 atomic active pointer，并通过 30 次 FTS 和 12 次 pointer 硬进程退出试验验证重启后无混合状态。
3. 在 FastAPI Agent 路径中实现服务端身份派生、ACL、类型化工具预算、检索内容准入及安全错误/终态，使用跨平台离线门禁统一验证代码、证据和公开仓库边界。

Backups:

4. 审计 511,962 行语料的复用 source ID，定位 4 组/8 条物理记录及 1/470 受影响问题，将 Macro Recall@5 敏感性变化限定为 -0.1064pp。
5. 建立全新 source/cache/index/output 根目录回放，重建 11,975 个向量并以零容差复现 63 个冻结质量值，避免缓存污染和文档数字漂移。
