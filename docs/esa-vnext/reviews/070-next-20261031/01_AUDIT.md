# 0.7候选独立审核

## 1. 读了什么
阅读00_READ_FIRST、TARGET_IDENTITY、VALIDATION、SEMANTIC_REVIEW、当前STATUS/RELEASE、当前API/回合/运行/Agent/启动器/知识发布源码，抽查真实语义正文、来源与业务失败记录。原包共1403成员；本次未做全树哈希重审，因为那不是产品质量结论。

## 2. 改善已存在
原请求保存和Deep重试、空会话补库、历史分页、移动工作区拒绝自动空库、一次模型提出的完整工具批次、索引更新期间旧发布版本、WAL初始化都进入真实代码。部分已在本次76项通过测试中被独立执行，例如tests/product/test_061_recovery.py的恢复、150历史分页、预览后修改、WAL读快照与事实更新。不要再把这些当全新功能重写。

原包123通过/1失败与4条浏览器旅程属于提交证据。Windows两次4.703/3.282秒及复用1.031秒也属于提交证据。WindowsZIP并未附在当前上传包中，只有本机路径与报告；本次不能验证其真实文件或重新启动它。

## 3. 独立复现A：部分失败结果被永久标为DONE
真实产品HTTP入口，临时SQLite，原ServiceAgent/Store；替身只产生工具选择及知识错误。
输入：准备借用预览，并解释押金制度，不提交。
实际：预览存在、知识工具报EVIDENCE_INSUFFICIENT、task为BLOCKED且文案写尚未完成；run为succeeded，user turn为DONE；原消息重试HTTP409 TURN_NOT_RETRYABLE。
业务表0张新申请，已有预览没有丢失。

源码：
- app/agent_runtime/workbench_agent.py:301-326：批次失败只落到task状态，随后正常return。
- app/runtime/turn_coordinator.py:97-133：无异常路径最终将turn写为DONE。
- app/runtime/workbench_runs.py:111-126：调用返回就记succeeded。
- app/api/product_routes.py:74-94：只允许FAILED/CANCELLED/INTERRUPTED重试。

这不是“所有run必须失败才正确”。run可以成功保存部分成果；缺少的是交付结果与重试范围。不要简单把所有BLOCKED抛异常并清空成功预览。

## 4. 独立复现B：模型漏选知识工具时，宿主仍宣布完成
同样的产品HTTP、业务和用户输入；替身执行真实规则/库存/已有申请查询后仅提出prepare_preview。
实际：preview存在，知识工具0次，knowledge为空；task=COMPLETED，turn=DONE，run=succeeded，重试409。

源码app/agent_runtime/workbench_agent.py:301-326的退出条件仍是有效预览，不是当前输入全部交付项。新实现修好了“同一批已提出的工具被丢掉”，但没有解决“用户要求的工具根本没提出”或“下一轮才该补做”的问题。替身复现证明宿主不能区分该情况，不是声称真实模型每次都会漏选。

需要轻量TurnResult/待交付项和确定性完成条件；自然语言解释仍可能错，不能宣称代码可证明任意诉求的语义完整。不要为此添加固定分类模型+planner+judge三层调用。

## 5. 默认和实验必须分开
WorkspaceConfig.experimental_grounded_expression=False；QueryOperations显式按开关选择。新解释不是正式默认能力。
实验验证器answer_blocks.py:19-73用数字集合、词项重叠、极性、符号等作硬拒绝。测试文件保留的复合否定用例失败，本次因jieba/FAISS依赖限制未独立重跑该实验。不能把程序规则当语义蕴含证明。

我抽查原始真实模型正文而不只看实现者标签：
- condition-3：问报修却发布借用的“待审批”，其引用确实来自另一个制度；partial标签不修正错误正文。
- comparison-3：正文声称借用未限定身份，下面原文却写只有有效维修记录员工可申请，自相矛盾。
- context-4：报修追问再次混入借用待审批。

原包实现者逐例标注（小样本，不是独立准确率）：基线开发12例5PASS/6PARTIAL/1FAIL；实验候选开发12例3PASS/6PARTIAL/3FAIL；实验留出12例4PASS/5PARTIAL/3FAIL。该留出已经使用并公开分析，后续只是回归集，不能再声称全新盲测。本次没有重跑模型。默认回退后的当前候选未有新真实语义结论。

## 6. 启动已经改善，但升级身份不完整
app/launcher/core.py:61-117识别同工作区同实例就复用，没有比较应用构建版本；195-202的instance_info没有commit/version。原包实际8740还是9f82而不是d32，与这个机制一致。
这不是要求启动器强杀旧进程。需要显示“正在运行哪个版本、当前包哪个版本”，允许打开旧版或经用户选择正常重启；有活动工作先等待/取消。环境拒绝关闭操作时不能换工具绕过。

## 7. SQLite
bootstrap.py:34-40在工作区lease下启用WAL；test_history_reader_does_not_block_real_fact_commit本次通过。它证明特定读快照场景已改善，不证明所有写争用已解决，也不能算9f82原实例500已修好。
仍应检查网络await是否位于事务外、同一用例是否嵌套新写连接、诊断写入是否拖住主业务。暂不换数据库，不用无限延长timeout处理结构问题。

## 8. 本次独立执行边界
- 支持Python下载失败：DNS不可达，未获得3.11/3.12。
- 完整目标集合：5个模块因依赖在收集时失败，没跑完。
- 不含这些模块的集合：76 passed，12 failed；12项都是FAISS缺失，不能判作12个新缺陷。
- 两个独立产品探针成功复现；第三个实验验证器尝试因jieba缺失未执行。
- 未独立运行真实模型/Windows/完整浏览器，不使用旧截图冒充0.7界面验收。

原日志与探针JSON在evidence/，精确源码摘录在SOURCE_EXCERPTS.md。不要把环境阻塞写成通过，也不要因此否定已通过的局部产品检查。
