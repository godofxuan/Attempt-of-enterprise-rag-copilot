# 0.2.0 实现与预期对照

## 1. 总体判断

这次不是空壳交付。可安装项目定义、固定数据目录、单FastAPI工作台、文档上传/索引/历史、原生工具调用循环、借用事务和第二个报修服务都进入了源代码。正常借用与完整参数报修的业务路径可以独立执行。
但“有界演示完成”和“长期方案全部能力完成”不是一回事。部分计划只有窄路径实现；自然对话、深入检索、任务恢复和知识到业务的衔接仍不完整。应保留0.2.0作为有效基线，进入产品升级，不回到9月main或重建第三份候选。

## 2. 实现矩阵

| 目标 | 本次判断 | 原始依据 / 备注 |
|---|---|---|
| M0/M1：单入口、固定数据与模型离线可浏览设计 | 已实现源码；完整启动未在本环境复验 | `app/cli.py`、`app/workspace.py`、`app/main.py`、`pyproject.toml`、`uv.lock`。真实init成功；目标Python3.11/3.12的完整安装受本环境DNS阻断。 |
| M2：资料库、解析、索引代次、答案历史 | 核心实现存在；不是只有文档 | `workbench_knowledge.py`上传、build、snapshot、answer；接入已有parser/FAISS/BM25。实时生成的原始日志未在源码包中。 |
| M2/M5：更完整的RAG与深入查找 | 部分实现 | `detailed`仅改变同一runner预算，没有独立的问题分解与主动检索规划。原controller可能多做补读，不等于开关完全无效。 |
| M3：借用、改期、预览、确认、提交、回读 | 核心业务独立复跑通过 | 清空字段、旧revision拒绝、6次连续日期修订与预览、重复提交一单、另进程回读。 |
| M3：Store职责收敛 | 部分实现 | 新TaskService是适配层，`store.py`仍2246行并承担历史goal/delivery等职责；不是简单按行数评价，而是多个业务职责继续混合。 |
| M4：工具选择、run/SSE | 已实现；生命周期和自然交互不完整 | `workbench_agent.py`是真正的原生工具循环，非预设全套工具次序；但ask_user缺字段和cancel终态有实际问题。 |
| M5：知识转任务 | 入口和可选原问题参数提取已实现；语义桥接不足 | UI对任何有来源答案都给电脑借用入口；`linked_answer_id`保存，但借用/报修工具面没有知识检索工具。不能把“关联一条答案”当成“可结合资料做业务解释”。 |
| M5：影响复用与候选 | 已有可用窄实现 | 字段变化依赖表、有效观察复用、实际设备候选；无库存会返回空列表。当前没有未来排期/偏好匹配，不把它算成已实现。 |
| M6：发布与同步 | 本地发布记录存在；产品说明和远端发布未完成 | 发行说明明确未push/PR；README保留大量历史内容，当前ZIP中存在57处指向缺失相对目标的链接（出现次数，不是57个独立文档）。 |
| M7：第二服务 | 共用核心确实成立，但缺字段路径失败 | repair共享Store、工具循环、表单、预览、提交；完整参数创建一张OPEN工单，借用单不变；空参数报修不能正常补问。 |
| M8：目录增量、反馈、缓存 | 源码实现存在；有限现场效果是包内报告 | `sync_directory`、`CachedChunkEmbeddings`、feedback/case。未用无现场依赖的本次审查替代其原49次模型请求证明。 |

LangGraph被移入legacy可选依赖，默认是一个125行原生工具循环。这是允许的合理简化，不因为没用某框架就判失败，也不为了框架名字迁回去。

## 3. 本次实跑结果

详见`evidence/product_probes.json`。全部使用合成数据和临时SQLite，未触碰用户活动库。

- 借用：显式null清除成功；旧revision得到TASK_CHANGED；连续6次改结束日期后均可预览；提交和重复提交只产生1张PENDING_APPROVAL；另起Python进程回读同一receipt。
- 报修：完整参数预览、提交、重复读回成功，产生1张OPEN；借用tickets为0。
- 全库存不可用：候选为空。先前静态怀疑被实际执行否定，不把这一点列为bug。
- 报修缺字段：脚本模型返回合法`ask_user`后，原Agent/Store路径报`KeyError: 'asset_id'`，run失败、task BLOCKED。
- 知识任务自然补充：原message路径在模型调用前报`NO_WRITE_GOAL`，留下FAILED的pending update。
- 运行取消：取消挂起的原run后，run为cancelled，但task仍RUNNING且有active_run_id；随后继续失败为TASK_BUSY_OR_FINISHED。

三处复现并非模型质量实验。完整安装/实时推理/浏览器整链路本次未复验，环境原因见00_README及安装日志。发行文档中的129 passed与49次产品推理属于提交方记录，不冒充本次结果。

## 4. 三个应立刻处理的日常路径问题

### B1：报修缺字段不能补问

代码：`app/agent_runtime/workbench_agent.py:75–78`把missing_fields交给`stop_run`；`app/service_desk/store.py:1177–1181`逐项读取`QUESTIONS[k]`；`app/service_desk/goals.py:989–992`仅有借用等旧字段，没有asset_id/description/impact。

修法不是给三个词打补丁：从现有Service字段schema统一生成必填字段、label、问句和UI字段，借用/报修共用。ask_user返回具体待补字段和用户能读懂的一次性说明。新增服务不再改另一份全局问题词典。

### B2：知识追问被当成业务字段修改

代码：`app/web/workbench.js:47`为非取消、无receipt任务展示自然补充；`TaskService.message`在153–178行先写PENDING，再调用`service_for(task)`；`catalog.py:91–95`不包含knowledge，抛NO_WRITE_GOAL。

短期先让知识任务消息进入知识会话分支，不制造pending facts。长期采用统一turn处理，将提问、参数变更和混合意图区分为同一回合内的动作，而不是所有消息都强制变成字段更新。

### B3：停止run没有释放task

代码：`app/runtime/workbench_runs.py:49–56,86–88`更新run/cancel asyncio task；`workbench_agent.py:119–122`只有`except Exception`收尾，而CancelledError不是Exception；`store.begin_run:948–955`看到残留active_run_id拒绝继续。

这是现有run取消API的复现，不是声称当前UI已有“停止run”按钮；当前UI“结束任务”走的是另一条任务取消路径。

把生命周期清理集中到RunRunner的finally/显式取消分支：只清除本run仍拥有的task活动标识；保留facts、preview和已完成工具观察；取消执行不等于撤销业务单，重启恢复不是唯一解锁办法。消息解释取消也要解除对应pending状态或显示明确待继续输入，不把它遗留成无反馈的PENDING。

## 5. 产品层面未完成的部分

### 服务对话不是完整助手

`TaskService.message:177–225`只产出参数变更；Agent的finish采用host outcome，不是处理任何用户问题的自然答复。用户问“为什么”“押金怎么算”“先改日期再解释政策”仍缺一条完整处理路径。当前设计应称“引导式参数与工具流程”，不是完整会话助手。

### 深入查找仍主要是预算开关

`workbench_knowledge.py:316–341`两模式共用V2AgentController，变化为search 2→3/open 2→4。没有新的一套主动子问题search/read/find计划。下一轮的升级是实际搜索策略，不是更改checkbox文案或继续增加max_steps。

### 文档与业务仍是两套事实来源

`workbench_service.py:310–317`从SQLite读取合成业务规则；`workbench_agent.py:26–28,93–96`仅knowledge类型有knowledge_answer。上传制度不会自动控制借用规则，这是当前明确边界，不应当偷偷改变。下一步要增加业务相关知识查询和版本绑定，同时让可执行规则继续由业务代码管理。

### 来源展示还没真正做到精确定位

`workbench_knowledge.py:248–266`将解析全文转成Markdown后再索引。原页段元数据留在原parsed中，UI可打开整份parsed/locator列表，但不是每条引用都有原PDF页/Word段的精确映射。应在解析到chunk之间传递SourceSpan，而不是让用户在大段文本里自行找答案。

### 业务止于创建申请

借用只有待审批结果，报修主要止于OPEN；README明确没有归还、续借、撤销。现阶段既有申请会阻止重新借用，反复演示需新TEST目录。这是功能范围，不是测试质量问题。下一轮应在原目录完成业务终结后再申请，而不是不断seed新数据绕过流程。

### 工程收敛还要继续

默认单进程成立，但入口仍提前导入历史RAG/容器；doctor也先导入resources。UI是约24KB压在53行的单一脚本；多服务规则在catalog、goals、Store、Agent定义里分散。优先按实际被修改的功能拆职责，不一次重写全部345个Python文件。

## 6. 清晰取舍

保留：现有CLI/固定数据、解析与索引核心、BGE/FAISS/BM25/RRF、业务事务、现有字段revision、确认与读回、轻量工具循环、已有目录缓存。
改造：消息处理、ContextBuilder、工具注册、run清理、知识检索模式、文档locator、业务生命周期、UI和首次使用。
退出默认路径：历史goal/understanding/writer组合、产品启动时的legacy装配、README的大段旧审计叙事。
不建设：新judge平台、全树指纹、平行账本、多Agent扮演、向量库迁移、默认终端/浏览器执行、为了炫技的分布式部署。
