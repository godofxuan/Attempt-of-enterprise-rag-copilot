# 2026-09-10 本地模型、改写、轻量排序试验入口

本轮真实代码与证据在保留未提交修改的候选工作树，不是本主目录的生产源码。

- [完整结果与决定](D:/文档/agent/RAG_try/.private/runtime_closure_20260907T160738/docs/local_advisor_v1/REPORT.md)
- [代码、改进原因和失败过程讲解](D:/文档/agent/RAG_try/.private/runtime_closure_20260907T160738/docs/local_advisor_v1/LEARNING.md)
- [机器可读结果](D:/文档/agent/RAG_try/.private/runtime_closure_20260907T160738/docs/local_advisor_v1/RESULTS.json)
- [最终证据ZIP](D:/文档/agent/RAG_try/.private/runtime_closure_20260907T160738/.private/local_advisor_v1/LOCAL_ADVISOR_FUSION_20260910_v2.zip)

已完成：D盘下载qwen3.5:4b，有限对象适用性修复，三模型改写试验，
36个合成检索场景、18场景双模型生成、200题WixQA改写检索对照、512题合成数据XGBoost F0/F1训练。

结论：新模型生成有局部收益；本轮LLM改写和XGBoost没有超过原问题混合候选+BGE。
不切默认模型/检索、不提交或推送、不修改简历，不宣称已生产上线。

所有量化结论的样本、指标与限制以完整报告为准。
