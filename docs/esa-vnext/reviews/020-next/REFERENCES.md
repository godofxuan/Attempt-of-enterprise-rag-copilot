# 参考项目和具体实施入口

本次只用官方仓库或官方文档核对机制。查看日期2026-10-29。以下main/master是可变分支；本包没有把它们锁定为依赖版本，不声称永久固定行号、Star排名或最近版本。具体集成应按当前锁依赖检查接口，架构学习不要求安装参考平台。

## Deep Agents：框架、Agent循环和运行时分层

- 架构： https://raw.githubusercontent.com/langchain-ai/deepagents/main/libs/ARCHITECTURE.md
- 装配： https://raw.githubusercontent.com/langchain-ai/deepagents/main/libs/deepagents/deepagents/graph.py
- 阅读点：The three layers、Construction and execution、create_deep_agent；model/tools/middleware与runtime归属。
- 应用：让当前小循环专注选择/调用，把上下文、工具注册、运行终态分别处理。
- 不应用：默认shell、filesystem、subagents和memory全部接入；为复用名词再加一层Agent。

## Onyx：有目的的多查询、相邻片段和丰富来源对象

- 搜索实现： https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/onyx/tools/tool_implementations/search/search_tool.py
- 阅读点：文件首部Queries/Recombination/Selection/Expansion/Prompt Building，search context与query expansion流程。
- 应用：Deep策略分题检索并read/find，Fast仍简洁；结果同时提供模型材料与UI来源对象。
- 不应用：复制所有secondary LLM筛选链到每个普通问题，或迁移其完整数据库与服务栈。

## Dify：执行过程到应用事件

- 实现： https://raw.githubusercontent.com/langgenius/dify/main/api/core/app/apps/workflow_app_runner.py
- 阅读点：流式文字、检索资源、节点开始/结束、停止/失败到Queue事件的映射。
- 应用：产品事件与内部实现解耦，前端稳定处理进度、暂停、结果与终态。
- 不应用：完整工作流画布、队列集群和所有节点类型。

## Paperclip：持续存在的工作项，而不是一次对话

- API： https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/api/issues.md
- 阅读点：issue状态、comments/documents、详情与更新receipt、checkout/release。
- 应用：会话关联task与真实ticket；刷新和后续处理围绕同一业务事实。
- 不应用：层级组织、多Agent调度和整套审批治理，也不按其文档把本地现有回读粗暴删掉。

## Open WebUI：工作空间与日常使用

- 功能组织： https://docs.openwebui.com/features/workspace/
- 应用：模型/资料/会话等对象可配置并持续存在；设置、历史和错误处理也是产品。
- 不应用：所有功能、社区市场、多租户体系或完整前端迁移。

## RAGFlow：召回与生成分开定位

- 检索测试： https://raw.githubusercontent.com/infiniflow/ragflow/main/docs/guides/dataset/retrieval_testing.md
- 应用：用户可查看检索文档/片段，快速分清没找到与找到后答错。
- 不应用：因此再建庞大评测和审计平台。

## Ollama：现有模型接口能力

- 工具调用： https://docs.ollama.com/capabilities/tool-calling
- Chat： https://docs.ollama.com/api/chat
- Embedding批量输入： https://docs.ollama.com/api/embed
- 应用：原生tools/stream和批量input；完整工具参数再执行。输入/输出预算与证据打包一致。
- 边界：接口提供功能不代表当前模型所有场景都可靠；按当前已安装模型运行，不擅自下载安装模型。

## Python：取消是运行生命周期的一部分

- 文档： https://docs.python.org/3.12/library/asyncio-exceptions.html
- 事实：CancelledError自3.8起是BaseException子类，普通except Exception不会捕获它。
- 应用：解释0.2.0 run已cancelled而task仍RUNNING的路径；在统一finally/显式取消处理中释放本run拥有的状态。
- 不应用：为了这个bug新建并行安全状态机。

## 本地源码依据

源归档`ESA_0.2.0_source_8881b000.zip`，归档注释8881b000fe4e216ff035d4f2853c2d7e58087c10。本次读取当前README、docs/esa-vnext的STATUS/RELEASE/START/GOAL/ROADMAP，以及本包01_REVIEW列出的源文件。

具体行号只对应该归档；后续工作区可有修复。6项复现记录见evidence/product_probes.json；实时模型次数0，完整应用启动未在此环境重验。安装和初始测试收集日志说明环境限制，不当作用户项目失败证据。
