# ESA 当前进度

当前范围：A01—D02，见reviews/070-next-20261031/GOAL.md；旧T01—T18不再作为并行活动计划。历史状态保留在history/STATUS_THROUGH_070_CANDIDATE.md，既有成果和失败不清零。

- 起点：39c4dbfa说明 / d32bd1b1应用；7个无关未提交文件原地保留。
- A01完成：origin/codex/esa-061-070已推送39c4dbfa756f6a8fb4597928d5695356e28da26b，Draft PR https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/pull/2 。一次内容检查覆盖66个未公开提交，未发现私密路径/凭据；未上传活动数据库、原始调用或审核ZIP。
- 当前运行：原8740仍9f82、原DATA_DIR .private/esa-vnext保持；不执行上一轮被拒绝的关闭操作。后续验证使用保留历史的隔离TEST副本，注明来源及新调用，不能用新空库绕过失败。
- 原件复现：partial_failure、omitted_knowledge均预览存在、turn=DONE、retry409；已保存DEFAULT_RED.json。这是程序替身+真实工厂/SQLite，不是新模型成绩。
- 当前：A02默认/实验CI分离，B01—B03交付与公共准备用例。下一动作：用正确行为断言先RED，然后实现部分结果与仅补缺项。
- 解释保持关闭；旧24例已经公开，只能作回归。新模型实验只做必要有限诊断，沿用真实记录、不重置历史。Windows原生与物理IME仍未验；没有新通过结论。
