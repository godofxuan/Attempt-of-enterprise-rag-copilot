# 0.3 会话、工具与运行边界

继续单FastAPI、SQLite、Ollama原生工具循环；不再新建图或固定分类/审查模型链。

- ConversationService保存真实回合和task关联；原知识记录通过兼容列与历史投影接入。task、ticket和原receipt继续来自既有Store，不以会话文本代替业务事实。
- ContextBuilder只装配当前事实、业务现态、有效观察和小段完整近期用户回合。当前自然消息作为真正的user消息出现一次；不埋进system JSON后又要求模型把它当指令。
- ToolCatalog从当前服务schema和执行范围生成能力。主模型可在一回合选择归一化字段、知识和业务读取；知识结果直接交付原publisher产物。工具无提交/升权能力，用户对当前预览的明确确认仍走原事务。
- 完整知识/工具原件保留在原记录；模型视图保留正文、来源、条件与不足，不重复传送trace和全部span JSON。它不是另做模型摘要，也不截短必要条件。
- RunLifecycle在发终态及序列化快照之前释放匹配nonce/fence；取消run不结束事项或撤销ticket。相同知识问题在当前run复用同一结果，无进展时停止。
- 页面API、事件、会话、任务、资料、显示模块拆开。SSE提供进展和已完成结果块；未经正式发布的半截结构化答案不冒充最终文本。断线从cursor/快照恢复，不重新执行模型。

参考的是职责而不是依赖安装：[Deep Agents架构](https://raw.githubusercontent.com/langchain-ai/deepagents/main/libs/ARCHITECTURE.md)区分装配/循环/运行时；[Dify应用运行器](https://raw.githubusercontent.com/langgenius/dify/main/api/core/app/apps/workflow_app_runner.py)将内部过程映射成应用事件；[Ollama工具协议](https://docs.ollama.com/capabilities/tool-calling)把完整工具结果送回下一轮。均于2026-10-30核读，不复制整个平台或引入其默认shell/多Agent能力。

测试输入迁移见CONTRACT_MIGRATIONS.md。程序替身只证明调度与事务路径；真实理解质量以本地模型的原始回合与实际结果另记。
