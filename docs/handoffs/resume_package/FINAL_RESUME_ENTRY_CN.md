# Enterprise Agentic RAG Copilot - 中文简历终稿

适用岗位：AI Agent 开发、RAG 应用开发、AI 平台工程、GenAI Evaluation。

## 推荐项目标题

**Enterprise Agentic RAG Copilot｜企业知识库智能体与评测系统**

Python / FastAPI / Streamlit / Ollama / BGE-M3 / FAISS / BM25 / SQLite FTS5

## 推荐项目描述

面向企业政策、邮件、文档和知识条目的本地 Agentic RAG 系统。由 Python
宿主程序控制身份、ACL、检索工具、证据准入、执行预算和引用发布，并通过
外部数据集、成对安全实验、故障注入和冻结证据门禁验证质量与工程边界。

## 推荐简历要点

1. 设计并实现受控 Agentic RAG 闭环，将问题拆分为 required aspects，由
   Controller 在预算内调度类型化 `search/find/open`，使用 Evidence Ledger
   跟踪证据完整性；身份、ACL、间接提示词注入防护及 Claim 级引用过滤均由
   Python 宿主执行，避免模型文本扩权或直接发布无证据结论。
2. 在 WixQA ExpertWritten 的 200 道真实匿名支持检索题上完成
   BM25/BGE-M3/RRF 同协议消融，BGE-M3 Dense 将 Recall@5 从 `42.75%`
   提升至 `66.42%`、nDCG@5 从 `32.15%` 提升至 `52.16%`，p95 延迟仅从
   `151.8 ms` 增至 `157.4 ms`；通过 clean-root 重建 11,975 个向量并以
   零容差复现 `63/63` 个冻结质量值。
3. 将超出单机内存预算的词法索引方案改造成可恢复的 SQLite FTS5
   single-writer 构建链路，在单机处理 `511,962` 条、9 类知识记录，
   `231.35 s` 生成并原子激活 `1.37 GiB` 索引，峰值内存约 `1.83 GiB`；
   实现 staging、完整性校验、immutable snapshot、tombstone、增量失效和回滚。
4. 为检索内容间接提示词注入建立 Guard OFF/ON 成对评测；在固定的 12 条
   garak 攻击子集上，将观测攻击成功从 `4/12` 降至 `0/12`、上下文暴露从
   `12/12` 降至 `0/12`，平均扫描耗时 `1.42 ms`，并公开小样本和非通用安全边界。

## 一页简历如何取舍

AI Agent/RAG 岗优先使用第 1、2、3 条；岗位强调安全时，用第 4 条替换第 3
条。不要把四条全部塞进空间紧张的一页简历。

## 禁止改写

- 不把 Recall@5 写成“回答准确率”或“RAG 准确率”。
- 不写“Agent 效果优于固定 RAG”；外部配对实验没有证明这一点。
- 不写“100% 安全”“生产可用”“达到 SOTA”或“企业真实线上部署”。
- 不把开发集、合成集、Oracle 或被拒绝候选的数字包装成最终效果。

数字来源与限定条件见
[PROJECT_EVIDENCE_MAP.md](../PROJECT_EVIDENCE_MAP.md) 和
[RESUME_METRIC_LEDGER.md](../RESUME_METRIC_LEDGER.md)。
