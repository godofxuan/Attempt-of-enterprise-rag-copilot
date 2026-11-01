# 07｜参考实现：研究职责与数据流，不复制整个平台

核查日期：2026-10-30。以下为本轮实际打开的官方源码/文档；main/master为滚动引用，不宣称锁定成某个不可变版本。未重新统计Star，也不沿用此前可能变化的星数。Codex实施时只对涉及具体API与构建参数的部分再次核对，不每轮把全部项目读一遍。

## R1 Open WebUI：前端构建随Python发行

- https://raw.githubusercontent.com/open-webui/open-webui/main/pyproject.toml
- 直接定位：`[tool.hatch.build.targets.wheel]`、`force-include`，将构建后的`build`纳入Python包前端。
- 学习：现代组件框架不等于用户必须运行Node；构建产物和后端一起发行。
- 我们：React/TypeScript/Vite构建到`app/web_dist`，同一FastAPI服务；不复制Open WebUI全部依赖。

## R2 Open WebUI Desktop：启动也是产品职责

- https://raw.githubusercontent.com/open-webui/desktop/main/README.md
- 学习：面向用户的下载、启动、连接配置与首次使用路径。
- 限制：该Desktop README明确是Early Alpha，不能称它所有行为已经生产成熟。它的首次联网策略也不是我们“运行时不装Python依赖”的现成证明。
- 我们：私有运行时、已安装实例复用、模型向导；不直接移植它整个Electron/模型运行引擎或强制更新策略。

## R3 Onyx：上下文与来源分工

- https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/onyx/chat/README.md
- 直接定位：`How Files are handled`、`How documents are represented`、`Tool Calls`。
- 学习：按上下文预算组织资料；模型收到简洁的引用编号材料，UI保留丰富来源链接；旧长工具结果不无限重复。
- 我们：ContextBuilder保留当前事实与选中来源；结构化来源一直到答案抽屉；不照搬全部多代理、连接器和项目管理。

## R4 Deep Agents：明确谁拥有行为

- https://raw.githubusercontent.com/langchain-ai/deepagents/main/libs/ARCHITECTURE.md
- 直接定位：`The three layers`、`Construction and execution`。
- 学习：能力装配、模型/工具循环、运行状态分层；构建阶段与执行阶段分离。
- 我们：保留现有小型原生工具循环，用TurnCoordinator/服务目录/领域服务划分职责；不为对齐项目名字迁移LangGraph或装整套Deep Agents。

## R5 Dify：运行事件到应用事件

- https://raw.githubusercontent.com/langgenius/dify/main/api/core/app/apps/workflow_app_runner.py
- 直接定位：EngineEvent与AppQueueEvent相关映射、text/retriever resources/finish事件。
- 学习：把底层运行细节转换成前端可用的稳定事件；让用户看到实际进度与结果。
- 我们：只保留小型run/step/text/source/need-input/preview/finished协议，不接工作流画布、Redis/Celery或整套部署。

## R6 PyApp：构建时预装、发行时内嵌

- https://ofek.dev/pyapp/latest/config/distribution/
- https://ofek.dev/pyapp/latest/config/installation/
- 文档支持自定义distribution及嵌入；`PYAPP_DISTRIBUTION_PATH`可指定本地归档，`PYAPP_SKIP_INSTALL=true`结合内嵌让预定义发行免运行时项目安装。
- 这些能力不自动保证ESA的FAISS/Windows/DLL适配；必须在目标平台实际构建验证完整运行时和wheel。仅将应用wheel放入exe而依赖仍在线安装，不满足本计划。
- 保留单一主打包路线；真实平台阻塞时可改完整portable runtime，不用反复切五个框架。

## R7 Vite与TanStack Query：构建与服务器状态

- https://vite.dev/guide/build
- https://tanstack.com/query/latest/docs/framework/react/overview
- 学习：Vite产生可静态服务的构建；Query集中管理异步服务端状态和缓存。
- 我们：组件只保存本地草稿/展开状态，URL定位对象，服务端数据一个cache；避免bridge/uiState/localStorage再维护互不一致的多份数据。

## R8 Playwright：测用户看得见的行为

- https://playwright.dev/docs/best-practices
- 学习：角色/可见文本定位、自动等待、隔离用例、浏览器真实交互。
- 我们：重点验证单输入、导航往返、来源、提交结果和恢复，不以函数存在、CSS类或截图存在证明旅程通过。

## R9 Codex Goals：明确的持续目标

- https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex
- 官方说明`/goal`、当前线程的继续执行以及暂停、预算/阻塞等停止条件。
- 我们：客户端支持时显式建立当前目标；仅写GOAL.md不代表已启动原生Goal。不承诺无限后台或跨客户端关闭仍自行工作。

## 引用与复用方式

以上主要借鉴架构，不把大量源码复制进本项目。真的复用代码或资产时保留其适用许可证/归属信息，避免不加判断整库粘贴。只引入能减少本项目重复工作且实际用上的依赖。
