# 全面复测与有限修复的阅读入口

这是本地候选的记录入口，不表示 main 或 GitHub 已更新。原始全面复测报告保留在 `docs/broad_validation_20260910/REPORT.md`，不要拿它的旧数字代替下面最终修复结果。

实际源码：`D:\文档\agent\RAG_try\.private\runtime_closure_20260907T160738`。

- [最终报告](D:/文档/agent/RAG_try/.private/runtime_closure_20260907T160738/docs/validation_followup_20260910/REPORT.md)
- [WixQA、财务、安全等补测结果](D:/文档/agent/RAG_try/.private/runtime_closure_20260907T160738/docs/validation_followup_20260910/EXTERNAL_RESULTS.md)
- [逐步排查和代码解释](D:/文档/agent/RAG_try/.private/runtime_closure_20260907T160738/docs/validation_followup_20260910/LEARNING_NOTES.md)
- [核心前后对比数据](D:/文档/agent/RAG_try/.private/broad_validation_fixes_20260910/FINAL_SUMMARY.json)
- [外部补测对比数据](D:/文档/agent/RAG_try/.private/broad_validation_fixes_20260910/EXTERNAL_FINAL_SUMMARY.json)
- [源码与证据审核包](D:/文档/agent/RAG_try/.private/broad_validation_fixes_20260910/RAG_VALIDATION_FIXES_20260910.zip)
- [审核包 SHA256 与体积](D:/文档/agent/RAG_try/.private/broad_validation_fixes_20260910/DELIVERY.json)

企业 TEST 自动回答合同 28/56→42/56；认证 API 合同 170/240→193/240，错误 answered 5→0。WixQA raw50 Recall@5=74.25%、nDCG@5=59.93%，本轮重测不变。软件回归 3921 passed、2 个历史绑定 failed、32 skipped，不是全绿。

所有新结果位于 D 盘；未提交、推送、部署或更改默认检索配置。审核包不含模型权重、完整外部数据、原始索引和私钥，不能声称是自包含运行镜像。
