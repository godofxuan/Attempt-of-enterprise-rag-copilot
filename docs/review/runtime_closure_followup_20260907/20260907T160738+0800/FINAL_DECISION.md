# 最终有限收尾结论

**READY_WITH_LIMITS：可作离线确定性机制演示与历史证据审查；不是新真实模型问答/生产验收。**

## 交付身份

- base/head：`c9984e92a10a6f417e2c1d8082af7e8f1e11aee1`。
- branch：`fix/runtime-closure-20260907T160738`。
- 工作区：原项目 `.private/runtime_closure_20260907T160738` 独立worktree；当前为未提交改动。
- 最终源码指纹、逐文件实际字节、tracked diff hash：`SOURCE_FINGERPRINT.json`。它覆盖app/scripts/tests、CI及列出的配置依赖文件，不是整个仓库指纹。
- 旧 `runtime_delivery_20260905` 保持只读；最终文件hash检查见 `FINAL_INTEGRITY.json`。
- 没有commit/push/merge/tag/deploy，没有改真实活动索引，没有同步成已发布版本。

## 三项工作结果

| 工作 | 完成什么 | 没有完成什么 |
|---|---|---|
| A | 已证实两类发布缺口，修改3个生产文件、39行；真实应用路径确定性反例与正例通过 | 任意语义充分性、复杂表格/跨页推理、真实模型新质量提升 |
| B | 证实旧supporting夹具与authority-only冲突；合法单文档冲突/来源排除进入真实HTTP；非法双权威索引被拒绝 | 两独立权威文档LLM冲突裁决，当前合法模型下不可达 |
| C | gold映射与一个离线核验入口；五文件字节重放、800 gold计分、775服务记录和87聚合组复算；失败、模板、演示指南齐全 | 新独立题、人审结果、历史dirty源码完整恢复、新真实模型确认 |

`TEST_RESULTS.json`保存最终相关/完整离线结果、源指纹、时间、退出码和日志；各轮有重叠，不将通过数相加。最后一次完整离线运行是 `full_offline_release`，之前的 `full_offline_final` 是行为相同但核验器换行格式调整前的检查点。
基线+同组新增业务测试6失败/19通过，修后25全通过；最终完整离线实际计数以该release记录为准，不拿历史3650/36替代。

## 分层状态

- 工作项可执行部分：完成并记录边界。
- 旧公开制品/聚合/gold：VERIFIED_WITHIN_SCOPE，分别保留三层状态；模型没有重跑。
- 新代码确定性行为：相关/完整离线测试结果及身份已记录。
- 新真实模型：NOT_VERIFIED；唯一一次准备因GPU环境缺docx在推理前停止（0主请求、0预热、0推理）。不能解释成质量通过或0%准确率。
- 真人语义：NEEDS_HUMAN，模板为空；机器工程分析不是真人评分。
- 历史跨平台CI：c9984e9四任务success已核对；本轮未提交修改的新CI NOT_RUN。
- 生产：NOT_EVALUATED。

## 当前能相信什么

旧检索数值仍是Dense65.92%、Top20 72.25%、Top50 74.25%的Macro Recall@5，对应nDCG52.08/59.20/59.93。此次补齐gold复算，不宣称产生新检索提升。
三个39行修复收紧“来源真实但对象/关系不对”的两个明确模式，并保留数值/条件支持规则和正常正例。权限/索引一致与回答正确性不是同一证明。
默认仍Hybrid，Top20显式可选GPU，Top50不晋升；旧budget超额7条、503、冲突未验收、语义局限全部保留。

## 停止决定

停止增加功能。本轮未实施learned ranker、未增加模型/框架/依赖、未调检索参数。
目前继续添加ranker不能修复已识别的语义/契约边界；继续刷旧题也不能产生独立证据。
后续最小外部条件是完整的现有服务环境（准备检查必须覆盖parser传递依赖）和独立审核者提供冻结问题/预期。正式发布需要用户另行决定，不因本报告READY_WITH_LIMITS自动推送。

阅读顺序：本文件 -> FIXES_AND_REGRESSIONS -> EVIDENCE_REPLAY -> TRACE_MATRIX -> KNOWN_LIMITATIONS -> DEMO_GUIDE。所有JSON/CSV/log及其最终摘要由ARTIFACT_MANIFEST索引；无自引用摘要。
