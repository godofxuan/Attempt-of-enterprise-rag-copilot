# 参考实现与源码落点

核查日期：2026-10-29。以下外部官方文档和源码在本轮实际打开；使用当前可读分支定位，不把它们冒称为用户依赖环境已经安装的版本。Codex实施时先查项目实际版本，再借鉴结构，不追着HEAD升级。

本轮不以Star数判断架构是否适合，也不重复引用之前未经本轮重新确认的Star统计。借鉴和直接复用代码是两件事：优先学习职责与数据流；真的复制实现时按该版本许可保留必要说明，不整套搬入商业/品牌相关部分。

## 阅读方法

每个参考只解决一类设计问题：先看对象和入口，再顺着一次请求的数据流看状态在哪里、哪些工作确定性执行、结果怎样送到页面。能对应到当前工作项才继续深入；不要求读完整个大型仓库。

## R01 — Open WebUI：产品工作空间与统一入口

- https://docs.openwebui.com/features/workspace/
- https://docs.openwebui.com/features/workspace/knowledge/
- https://raw.githubusercontent.com/open-webui/open-webui/main/backend/open_webui/__init__.py

已看内容：Workspace将模型、知识等组织为可配置对象；知识库提供资料到问答的使用路径；CLI具有明确serve入口。

学习：先让用户进入应用、选择资源、继续历史；安装/运行/资源配置分工。落点M1、M2、M5。不要照搬全部模型预设、工具生态、完整知识工具列表或前端技术栈。

## R02 — Deep Agents：运行时、循环与上层装配分层

- https://raw.githubusercontent.com/langchain-ai/deepagents/main/libs/ARCHITECTURE.md
- https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md

已看内容：架构说明区分LangGraph运行时、LangChain Agent循环和Deep Agents上层harness；middleware、backend、profile各自负责不同能力。

学习：一个明确装配入口、上下文与工具边界、能力按需加入。落点M4。不把文件系统、shell、子Agent和长期记忆整套接到借用任务，也不再造一个类似框架。

## R03 — Onyx：知识工具的整体数据流

- https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/onyx/tools/tool_implementations/search/search_tool.py

已看内容：文件开头解释查询、结果融合、连续片段、选择与扩展，以及面向模型的输出和保留给UI/持久化的丰富对象。

学习：检索是应用能力，不只是返回一段文本；来源结构必须跨层保留。落点M2/M5。默认不复制其全部多轮LLM查询、筛选和文档扩展步骤。

## R04 — RAGFlow：知识质量从解析/召回定位

- https://raw.githubusercontent.com/infiniflow/ragflow/main/docs/guides/dataset/retrieval_testing.md

已看内容：文档解析完成后检查期望片段是否被召回；正确片段存在但答案不好，和根本没召回，是不同问题。

学习：资料库、检索查看和故障定位形成完整路径。落点M2/M8。不要把源站默认参数直接认定为本项目最佳参数，不因学习RAGFlow而迁移整个存储与部署。

## R05 — Dify：应用运行与事件投影分工

- https://raw.githubusercontent.com/langgenius/dify/main/api/core/app/apps/workflow_app_runner.py
- https://raw.githubusercontent.com/langgenius/dify/main/api/app_factory.py

已看内容：runner接收工作流/节点事件并转换到应用队列事件；应用工厂集中装配组件。

学习：运行有明确开始、暂停/失败、资源与结果事件，UI消费应用事件而不是理解图内部结构。落点M4。不复刻Dify图引擎、图形编辑器、插件daemon和全部运行基础设施。

## R06 — Paperclip：工作对象与修订

- https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/api/issues.md

已看内容：issue作为工作单元，支持状态、关联文档、原子checkout及部分带预期值的更新；详情与列表投影分开。

学习：任务长期存在，用户可回来继续，更新不是覆盖一段聊天全文。落点M3/M5。不要将组织级Agent调度、公司预算体系搬进本项目。

## R07 — LangGraph：工作流、动态工具循环与持久化边界

- https://docs.langchain.com/oss/python/langgraph/workflows-agents
- https://docs.langchain.com/oss/python/langgraph/persistence

已看内容：固定流程与动态Agent的区别；checkpointer与store是不同持久化能力。

学习：在一个产品中组合确定性业务与动态工具选择。落点M4。当前继续采用业务状态恢复，不把图checkpoint误当业务事务幂等，也不无条件添加第二份状态真相。

## R08 — 标准工具与Ollama集成

- https://docs.langchain.com/oss/python/langchain/tools
- https://docs.langchain.com/oss/python/integrations/chat/ollama
- https://docs.ollama.com/capabilities/tool-calling

已看内容：类型化工具输入、结构化返回、context/state访问；ChatOllama工具调用与异步/流式等集成；具体模型需支持工具协议。

学习：模型可见参数与服务端上下文分开，工具适配器薄，错误可解释。落点M1/M4。不假定当前模型与文档示例模型相同，不自动下载示例中的大模型。

## R09 — FastAPI生命周期

- https://fastapi.tiangolo.com/advanced/events/

学习：用现成lifespan组织资源初始化与释放，API采用清楚依赖。落点M1。不是为每个资源再写自有启动守护框架。

## R10 — uv项目锁与同步

- https://docs.astral.sh/uv/concepts/projects/sync/

学习：安装/同步与运行分离，实际生成锁文件；日常运行可使用已同步环境。落点M1/M6。不要手编锁文件，也不要每次serve无提示更改依赖。

## R11 — Ollama资源与运行配置

- https://docs.ollama.com/faq

学习：观察模型加载与资源、配置上下文/驻留/并发；实际性能受本机环境影响。落点M1/M8。不要把更大上下文或更多并发当作无成本默认值。

## R12 — Codex原生Goals

- https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex

已看内容：`/goal`及pause/resume/clear；目标属于当前线程，按目标、终止条件与预算推进；支持该功能的构建才有原生命令。

学习：给Codex有限、可判定的产品目标和迭代空间，不要求每阶段用户再说继续。`GOAL.md`文件不等于激活Goal，客户端中断/预算仍会停止持续工作。

## R13 — Codex项目指令

- https://developers.openai.com/codex/guides/agents-md
- 本轮该官方入口跳转到：https://learn.chatgpt.com/docs/agent-configuration/agents-md

学习：AGENTS.md用于项目工作约定；大的计划通过链接按需读取，不把全部长文塞进根指令。合并现有约定，不覆盖用户已有文件。

## R14 — Codex持续计划

- https://developers.openai.com/cookbook/articles/codex_exec_plans

学习：阶段可验证、决定与发现可持续更新，换会话仍能继续。这里只用一份STATUS保存实施落点，避免生成平行计划和庞大证据材料。

## R15 — Superpowers的根因调试

- https://raw.githubusercontent.com/obra/superpowers/main/skills/systematic-debugging/SKILL.md

学习：先调查根因再修症状；多次失败时重新审视共同机制。落点所有阶段。采用方法，不逐条复制完整技能规范或额外引入反复审批。

## 本项目源码依据：已抽查的实际位置

来源：`ESA_AGENTOPS_RESULT_20261013_FINAL_R2.zip`。这是旧候选定位资料，具体修复是否仍需要，以Codex读取当前工作区为准。

| 路径 | 本轮可确认的内容 | 对应工作 |
|---|---|---|
| 顶层`README.md`、`CHANGES_AND_LIMITS.md` | R2主要为只读AgentOps增量，不能当作产品重构已完成 | 不围绕诊断继续扩张 |
| `docs/COMPONENT_ADRS.md` | 双worker、现有技术与无checkpointer的明确选择；当前仅dense BGE路径 | 了解旧决定后有意识调整 |
| `tools/launch_local.py` | 双索引、runtime与三端口实验启动入口 | M0/M1 |
| `source_candidate/scripts/dual_track_worker.py` | 正常prepare依赖tests/eval、选择源码树、替换settings | M1默认依赖收敛 |
| `source_candidate/app/main.py` | 已有create_app、lifespan、ServiceContainer与路由 | 直接复用，不另造Web框架 |
| `source_candidate/app/api/service_tasks.py` | TaskCreate/GuidedTaskRequest、readiness、模型/配置/授权绑定、Service路由 | 简化产品入口与API |
| `source_candidate/app/service_desk/contracts.py` | UserFacts、执行范围、动作schema、参数规范化 | 复用字段和契约，不增第三套 |
| `source_candidate/app/service_desk/store.py` | SQLite事务、预览/确认/提交/读回、运行、修改与事件 | M3拆职责，保留业务实现 |
| `source_candidate/app/service_desk/goals.py` | guided上下文与大量历史目标重释/审查分支 | M4保留主路径，隔离历史组合 |
| `source_candidate/app/service_desk/knowledge.py` | 知识结果转接与正文/引用再组织 | M2共享KnowledgeService |
| `source_candidate/app/agent_runtime/task_agent_graph.py` | 模型选择、工具观察和多类writer/reviewer混合 | M4薄循环与上下文分离 |
| `source_candidate/app/service_desk/capabilities.py` | 现有小型能力目录 | M7演进为真实服务目录 |
| `source_candidate/app/retrieval/pipeline.py` | 已有HybridRetrievalPipeline等排序/过滤能力 | 保留有效检索，不因热门迁库 |
| `source_candidate/app/indexing/store.py` | ActiveIndexPointer、activate_version、发布锁和build_index_version | M2复用索引代次切换 |
| `source_candidate/app/indexing/builder.py` | 解析/向量/构建与验证入口 | M2接入资料导入 |
| `source_candidate/app/indexing/incremental_computation.py` | 现有增量计算、来源绑定和checkpoint结构 | M2/M8复用有效计算，收敛过量包装 |
| `source_candidate/app/indexing/resumable_embeddings.py` | 可恢复分批embedding与进度结构 | M2中断继续，不从零重做 |

没有在本轮运行用户的模型，没有修改上传源码，没有声称最新本机27项变化已完成合并。这个包把下一步实施组织完整；真实实施与Git同步由有工作区访问权限的Codex执行。
