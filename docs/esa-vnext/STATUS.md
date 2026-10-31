# ESA 当前进度

当前范围：A01—D02，见reviews/070-next-20261031/GOAL.md；旧T01—T18不再作为并行活动计划。历史状态保留在history/STATUS_THROUGH_070_CANDIDATE.md，既有成果和失败不清零。

- 起点：39c4dbfa说明 / d32bd1b1应用；7个无关未提交文件原地保留。
- A01完成：origin/codex/esa-061-070已推送39c4dbfa756f6a8fb4597928d5695356e28da26b，Draft PR https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/pull/2 。一次内容检查覆盖66个未公开提交，未发现私密路径/凭据；未上传活动数据库、原始调用或审核ZIP。
- 当前运行：原8740仍9f82、原DATA_DIR .private/esa-vnext保持；不执行上一轮被拒绝的关闭操作。后续验证使用保留历史的隔离TEST副本，注明来源及新调用，不能用新空库绕过失败。
- 原件复现：partial_failure、omitted_knowledge均预览存在、turn=DONE、retry409；已保存DEFAULT_RED.json。这是程序替身+真实工厂/SQLite，不是新模型成绩。
- A02完成：产品默认检查与解释实验检查分开；当前132项相关默认离线回归、5项实际浏览器（明确外部模型替身）通过。补充的公共prepare收口回归4项通过；次数不相加当质量指标。实验2项1通过1失败保留，未skip/xfail。
- B01—B05已实现：回合交付保留未决项、仅重试知识；公共prepare复用原propose；command先关闭读连接再读业务；数据库繁忙结构化409；实例报告实际commit与build，新旧不同需显式选择。
- React：保存参数/选设备后直接生成当前预览；部分结果显示可执行重试。前端类型、构建、5个浏览器场景已通过。物理IME未验。
- C01/C02：来源附可信原文节/文档分组/业务metadata，无metadata为unknown；实验schema压缩，旧词法推断只作诊断，来源/Guard仍保留；业务域上下文由宿主kind约束，不猜关键词。实验仍关闭。
- 下一动作：固定rc2实现提交并构建，完整克隆现有TEST历史（不换空库）检查旧失败任务恢复及真实模型/业务主链；小范围同条件解释比较。
- 解释保持关闭；旧24例已经公开，只能作回归。新模型实验只做必要有限诊断，沿用真实记录、不重置历史。Windows原生与物理IME仍未验；没有新通过结论。
