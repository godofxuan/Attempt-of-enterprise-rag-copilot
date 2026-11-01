# 一手参考与迁移取舍

核对日期2026-10-30。下列main/latest页面可能继续变化；实施时确认实际依赖版本，采用机制而不是复制最新版全部配置。本轮没有重新宣称Star排名。

| 来源与直接入口 | 本轮学习点 | 明确不做 |
|---|---|---|
| Open WebUI `pyproject.toml`：https://raw.githubusercontent.com/open-webui/open-webui/main/pyproject.toml | 前端build纳入后端发行物，用户无需Node开发服务 | 不照搬其全量依赖或多租户平台 |
| Onyx chat context：https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/onyx/chat/README.md | 上下文预算；模型材料简化、UI来源丰富；历史工具内容有策略地裁剪 | 不把旧答案当原始证据，不照搬全部检索栈 |
| Deep Agents architecture：https://raw.githubusercontent.com/langchain-ai/deepagents/main/libs/ARCHITECTURE.md | 区分能力装配、Agent循环、运行状态和工具；职责明确 | 不迁框架，不增子Agent/长期记忆/终端工具 |
| Dify runner：https://raw.githubusercontent.com/langgenius/dify/main/api/core/app/apps/workflow_app_runner.py | 运行事件投影为应用进展与结果，状态层次区分 | 不搬工作流引擎或完整事件总线 |
| TanStack Query keys：https://tanstack.com/query/latest/docs/framework/react/guides/query-keys | Query key对应真实数据身份，按cid/turn归属缓存 | 不新增一套自制全局前端状态总线 |
| TanStack cancellation：https://tanstack.com/query/latest/docs/framework/react/guides/query-cancellation | 查询AbortSignal与客户端请求取消；与业务run停止分开 | 不把页面卸载等同后台任务取消 |
| Playwright webServer：https://playwright.dev/docs/test-webserver | 测试显式启动目标服务，readiness、CI实例隔离 | 不硬编码个人端口/目录，不绕过浏览器管理策略 |

上述参考没有直接提供我们全部业务答案。具体TurnCommand、预览+解释合并和工作区恢复是针对本次源码问题的设计，不冒称来自某项目原生实现；证据支持的答案生成也需要在实际模型上评估，不能仅凭引用结构保证正确。
