# 02｜产品与代码：成熟的本地知识/服务应用

## 1. 本轮不再追求“多一项能力”，追求完整、自然和可维护

范围仍是独立知识问答、电脑借用、IT报修、本地合成服务台。既有完整流程保留，本轮不增加第三种业务。用户一次输入应能提问、补充和改期；所有确定的写入由业务函数执行；真正提交只需一次清楚的确认。

三个主入口：**助理、我的事项、资料库**。设置和演示服务台置于次级导航。助理兼容纯RAG与有事项的会话，不再让用户在三个聊天页重复输入。“我的事项”是列表和详情，不再是另一套聊天实现。

## 2. 目标架构

```text
Windows桌面快捷方式 / ESA.exe
             │
        Launcher（本地实例与环境）
             │
      单FastAPI + 内置静态前端
             │
     路由 + 应用服务 + 共享ViewModel
       ┌─────┴────────┐
  Conversation/Turn   KnowledgeService
       │                 │
  小型Agent循环       Fast / Deep策略
       │                 │
  typed ToolRegistry  文档/检索/统一答案发布
       │
  Loan / Repair领域服务 + Lifecycle
       │
  SQLite事务 / 版本迁移 / 索引 / Ollama适配
```

launcher是运行生命周期，不承载业务；FastAPI路由只做协议映射；Service/Domain只负责用例和规则；模型不承担表单校验、事务完成判定和页面状态维护。

不引入第二后端、常驻Node、Electron完整壳、Redis/Celery、LangGraph迁移、多Agent或新向量库。

## 3. 前端技术选择：React + TypeScript + Vite，构建后随Python发行

明确调整此前“不引入前端框架”的约束：当时是为了不增加部署单元，但当前多视图、异步事件、表单和DOM搬移已超过手写脚本的合理复杂度。现在引入**开发/构建时组件框架**，不引入用户日常运行的Node服务。

采用React/TypeScript/Vite；TanStack Query集中管理服务端状态；简单UI primitives统一Dialog/Drawer/Select/Toast，优先使用少量Radix组件，不复制整套商业后台模板。路由使用React Router或项目已有等价能力，不能同时维护两套路由。Markdown采用成熟渲染器，禁用任意原始HTML；来源为可点击稳定对象。

构建流程为`frontend/dist → app/web_dist → wheel/portable bundle`。用户只启动Python服务。Open WebUI静态构建并将前端打入wheel的方式是直接参考，不要求采用它的Svelte或整套依赖。

服务端状态只放Query cache；组件本地只保存未提交表单和展开状态；URL保存会话/事项/知识库定位。SSE只更新相关query或单次运行状态，不复制一个第三份全局store。不再搬动DOM节点。

## 4. 代码组织：逐步迁移现有模块，不另建第二产品

```text
app/
  cli.py                         # 开发者命令，保留兼容
  launcher/                      # 实例发现、启动、打开浏览器、错误入口
  bootstrap.py                   # 显式依赖装配
  api/                           # 轻路由、DTO、统一错误映射
  conversations/                 # 会话、回合、活动事项和历史关联
  knowledge/                     # library/ingestion/retrieval/answer service
  service_desk/                  # 现有目录、借用/报修、lifecycle
  runtime/                       # run coordinator、模型、事件
  persistence/                   # 连接与版本迁移，明确repository
  web_dist/                      # 构建产物
frontend/src/
  app/                           # shell/router/providers
  features/assistant/
  features/requests/
  features/library/
  features/service-desk/
  features/settings/
  components/                    # 小型、可复用组件
  api/                           # OpenAPI类型、query、SSE
```

不是要求一开始创建所有空文件。迁移调用方再删除旧实现；短期兼容适配器只允许转发，不允许复制新业务。原legacy RAG入口与研究脚本放在明确extra/历史路径，退出默认导入。

### 当前到目标的具体映射

| 当前 | 目标职责 | 不做什么 |
|---|---|---|
| workspace.py | Config、bootstrap、DTO、各API路由分离 | 不再添加几百行内嵌路由 |
| workbench_service.py | TaskApplicationService + TaskView assembler | 不把整个存储payload作为UI协议 |
| conversations.py | ConversationService + TurnCoordinator | 不在纯知识和任务分支分别维护取消逻辑 |
| workbench_runs.py / run_lifecycle.py | 一个run/turn终态协调入口 | 不保留多层重复finish和互相覆盖status |
| Store | 事务仍用SQLite，按任务/预览/票据/资源提取repository与领域函数 | 不做全项目ORM迁移，不以拆文件复制规则 |
| workbench_knowledge.py | LibraryCatalog、IngestionJob、KnowledgeQuery三个服务 | 不在一个类里继续扩文档+目录+会话+反馈+回答 |
| generation_v2.py | 当前产品单一协议+独立legacy adapter | 不一边说唯一schema一边兼容多种隐藏格式 |
| UI scripts | React feature组件+共享hooks | 不将旧JS打包当作完成前端重构 |

## 5. 减少防御性if/else的具体手段

1. 输入只在API/工具边界做一次Pydantic校验；内部函数接收有效类型，而不是到处重复dict.get/类型猜测。
2. 服务目录提供字段、默认值、工具和用户标签；渲染与补问不再维护平行词典。
3. 借用/报修状态转移继续用明确ActionSpec/transition表；只在有真实领域差异处保留分支。
4. Typed ToolResult/TurnOutcome收敛`success/error/missing/preview/current-ticket`形状，前端按有限类型渲染。
5. 业务错误在边界统一映射`code + message + recovery_action`；不能所有异常都成为“重新确认范围”，也不能吞掉异常返回success。
6. 当前知识协议只允许一条产品装配路径；历史协议隔离，不在热点请求中来回猜格式。
7. DB迁移按版本执行一次，移除构造器中的重复ALTER与全量历史回放。
8. 先Ruff/Prettier展开压缩代码，再提取实际职责。不要为了“少if”把逻辑压缩成难读的字典或lambda。

保留真正有价值的检查：业务日期、状态、当前版本、单次确认、幂等唯一性、引用能否定位。删除的是重复审查与分散规则，不是业务正确性。

## 6. 回合与事项：一次清晰的生命周期

`TurnCoordinator`唯一负责一次输入的接受、attempt、run、输出和终态。开始前确定当前活动事项；纯知识和业务回合复用同一结束流程。内部实现可利用async context manager，但不能增加新的LLM调度层。

- 同一用户输入只有一个Turn，重试建立新attempt；成功结果不重复追加。
- run失败/取消/中断，turn必须进入对应终态并给出可重试动作。
- 取消运行不取消事项；取消事项清除活动绑定但保留历史；业务单据照常保留。
- 已提交/已归还/已关闭的事项仍可查询，但不能因消息失败重新变成待填写。
- 会话可关联多个历史事项，当前选中的活动事项明确可切换。收到无明确服务意图的政策问题，不强行进入已取消事项。
- 改期后只失效库存/预览等受影响观察，保留不受影响资料与事实。

既有task状态暂时由ViewModel转成中文用户状态；不要同一轮无必要重写所有存储枚举。先统一拥有者，再做有证据的数据迁移。

开始和收尾分别用短数据库事务，模型/网络await期间不持有SQLite写事务。停止运行并不撤回已经提交的命令；重试先读回确定结果。运行事件用于页面与诊断，不另做完整event-sourcing系统。

建议视图：

```json
{
  "task_id":"…",
  "status_label":"待确认",
  "summary":"借用电脑 · 11月2日至11月4日",
  "next_action":{"type":"confirm_proposal","label":"确认并提交"},
  "fields":[],
  "proposal":null,
  "current_ticket":null,
  "notices":[]
}
```

此为目标示例，不是既有API。正式DTO从后端OpenAPI生成前端类型，逐一迁移，不维护手写第三套schema。

## 7. Agent：保留小循环，清楚的模型和工具边界

仍用现有原生工具调用。build入口装配模型、上下文、工具目录和运行协调器；工具只是领域/知识服务的适配器。明确按钮直接调用用例，不额外运行意图分类Agent。

模型依据当前可用动作和真实观察选择下一步；工具返回结果、来源、可供用户选择的选项；模型解释取舍。提交仍由预览后的明确操作调用事务，不允许模型决定“是否用户已经确认”。

ContextBuilder保留当前问题、结构化参数、当前事项、有效观察、最近必要回合和最后展示的选项ID。`选第二台`依据当前候选列表定位，不能从历史自由文本猜一台。过去回答用于理解指代，不作为新知识证据。只读结果也应有简短自然语言+结构卡，而不是整段JSON。

异常只分为可恢复连接错误、用户信息不足、业务不满足、内部错误；一次有限协议修正可保留，不新增“审查Agent”。无进展检测依赖动作及事实是否变化，不把用户正常改期计入终身次数。

## 8. RAG：保持已有Deep，收敛上下文和交付

Fast/Deep继续共用检索及AnswerResponse。Deep已能计划子问题和read，不再重写；完善缺条件、跨文档差异及来源定位即可。

当前`旧问题>500字符就无法追问`应改成预算化ContextWindow：保留最新问题、已选来源/对象和重要结构化条件，较旧完整回合按预算舍弃；必要时给用户明确的上下文提示。默认不新增一轮模型摘要。最终输出必须是当前问题的答案，不把历史问过的所有内容再回答一次。

文档进入流程完成后自动排队增量索引，页面显示“上传/解析/索引/可检索”。高级用户可暂停或手动重建。文档失效和重建期间显示旧索引状态与已完成时间，不悄悄查询半成品。现有缓存、批量embedding与稳定来源位置保留。

知识结果与Service共享，不再做字符串转结构再转字符串。读回当前业务状态由业务对象提供，不能拿提交时快照当成今天的状态。

## 9. 运行与数据

程序安装目录、应用运行环境、用户DATA_DIR分开。先关联已有工作区，不能复制出空库假装历史消失。历史数据迁移有版本且只执行一次，SQLite交易和现有数据结构可继续用。

正式默认应用不扫描项目源码、不导入pytest、不需要历史模型授权账本才能运行。调试诊断保留按需入口，主界面不显示源码哈希、内容digest、内部动作名或原始账目。

## 10. 可辨识的产品价值

本轮的新意不在“更多Agent”：同一助理理解资料、推进事项、展示真实结果；已结束事项不绑死会话；改一个日期只重算受影响结果；现有数据升级后仍可用；双击运行的发行包包含完整前端和运行时。这些是现有能力转为可靠产品的关键差异。
