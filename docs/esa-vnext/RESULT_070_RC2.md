# 0.7rc2 本轮结果与复核入口

应用源码：`70a5005022e234e047d6c8e9ef515d86dccbcbb8`。最后的文档/CI说明提交与它区分；应用和前端不再改动。

## 交付出口

| 项目 | 实际结论 |
|---|---|
| A01 | 已推feature，Draft PR #2；未合并/未发stable |
| A02 | 产品CI与解释研究独立；共享引用/解析/开关仍跑产品检查，研究红例保留 |
| B01/B03 | 预览成功、知识失败不再DONE+409；程序路径证明只补知识、保持后续参数，公共prepare完成剩余预览后才DONE |
| B02 | 保存参数/选设备/明确生成预览与Agent工具共用业务用例；不额外调用模型 |
| B04 | command关闭读连接再投影业务；真实SQLite并发及结构化STORAGE_BUSY回归通过 |
| B05/B07 | 真实build身份、不同版本显式选择；部分交付可行动重试、保留当前预览；现有三入口/单输入框 |
| B06 | 最终70a50050真实UI借用/报修全周期通过，旧确认409、当前精确确认、唯一工单、幂等读回；只读原回合恢复 |
| C01/C02/C03 | 可信分组/上下文与稀疏实验协议已实现；四组配对仍有错主体证据、残句/关系倒置，保持关闭，不转正 |
| D01 | 最终Windows包、中文路径、离线模型、端口冲突、重复复用、同TEST库正常升级通过；原生GUI/物理IME未验 |
| D02 | 源码/文档推feature并更新Draft PR；无合并权限，不合并main |

应用冻结commit的[产品CI（Windows/Linux）](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/41175705182)成功；[研究检查](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/41175705201)真实失败。旧全仓CI在ubuntu-latest 26.04找不到固定Python3.11.9，已将旧作业OS固定22.04，不改测试/冻结标签；后续运行不能自动记为通过。

程序替身、实时模型和Windows测试分别记录，不相加成准确率。解释实验的旧复合否定误拦断言仍失败，不skip/xfail。

## 身份与证据

本机私有证据根：`.private/esa-vnext/upgrade-070-next/`（不会上传GitHub）。复核顺序：

1. `START.json` / `PUBLIC_CONTENT_CHECK.json`：真实起点、7个未提交文件保留、首次公开内容检查。
2. `DEFAULT_RED.json` / `DELIVERY_RED.xml`：原DONE+409缺陷。`DELIVERY_FINAL2.xml`、`SCOPE_PROJECTION.xml`及当前product CI：修后实际代码路径。
3. `LIVE_START.json`：原SQLite backup保留75任务/历史工单/旧调用ID；不是重建空库。
4. `FINAL_INSTANCE.json` / `UPGRADE_CHOICE.json`：真实运行身份和正常版本切换；原8740旧版未操作。
5. `FINAL_SCOPE_RECOVERY.json`：同一原失败只读输入/任务/回合恢复。模型错误brief及宿主范围投影保留，不能说成模型已理解准确。
6. `LIVE_JOURNEY_RELEASE.json`及同名前缀截图：最终模型/UI/工具/预览/确认/读回。`DATABASE_FINAL.json`保存库行，`VALIDATION.json`检查每任务唯一工单及实际终态。
7. `FINAL_DUAL_KNOWLEDGE.json`：最终双入口原始答案，逐项与未改来源核对；借用七项内容均交付。
8. `EXPERIMENT_COMPARISON.json` / `LIVE_CHECKS_219b0ff8.json`：四组旧开发/新短变体配对的负结果。它们不是外部fresh基准，没有独立人审。
9. `NEW_MODEL_CALLS.jsonl` / `COST.json`：全部新请求响应及准确成本；`CODE.patch`从39c4dbfa重建本轮实现差分。更早账本保持原位，不虚构全项目累计。
10. `WINDOWS_PORTABLE_70a50050.json`：最终发行程序实测，原生首次目录/自动开页GUI/物理IME分别NOT_RUN。

实时调用已停止，后续交付整理不发送模型。新30chat/13query文本/0index；工作台累计412chat/227embedding，旧1个SENDING未知结果保留。总已记录新模型请求延迟174389ms；没有同条件性能对照，不声称整体更快。

## 有限演示

1. 打开当前8748，核对设置中的rc2与70a50050；选择合成资料库，问借用资格/期限/押金并打开来源。
2. 新借用明确上限，输入未来日期、用途/规格；模型选择实际规则、资格、库存和本人申请工具。
3. 选设备或保存参数直接生成预览；改期后旧确认拒绝，当前精确确认产生待审批，不是已批准或分配。
4. 重复提交读回同command_id；合成服务台按状态预览并明确确认批准/领用/归还。报修为本人设备，经OPEN、处理、解决至关闭。
5. 部分解释失败时保留预览，点重试解释；若期间改参数，只重建当前预览，不重放旧参数。

这条流程是测试用户真实UI操作，不是模型预置动作。实例不运行时按START中的ESA.exe/esa open命令打开完整TEST目录。

## 不夸大的限制

默认报修资料的一种问法仍漏掉提交状态并partial。新解释无稳定改善，保持关闭。原生桌面首选目录/自动开页及物理IME待验。没有同条件main实验，尚未证明追平main。当前本地单用户、合成TEST，不宣称企业生产或可靠多人审批。

下一项具体待完成：对冻结Windows包做原生首次目录选择、自动开页和物理中文输入法检查；报修知识漏答留作独立后续问题，本轮不扩题或继续调参。
