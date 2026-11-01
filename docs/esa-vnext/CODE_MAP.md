# 当前产品代码入口

| 职责 | 位置 |
|---|---|
| 命令与 Windows 实例启动 | `app/cli.py`、`app/launcher/core.py`、`packaging/windows/Launcher.cs` |
| 唯一产品 factory / 生命周期 | `app/workbench_app.py`、`app/bootstrap.py` |
| 工作区配置与固定目录 | `app/persistence/workspaces.py` |
| HTTP DTO 和适配 | `app/api/workbench_contracts.py`、`workbench_routes.py`、`conversation_routes.py`、`product_routes.py` |
| 会话、原消息与多次尝试 | `app/conversations.py`、`app/runtime/turn_coordinator.py` |
| 持久运行与统一结束 | `app/runtime/workbench_runs.py`、`run_lifecycle.py` |
| 模型根据观察选择工具 | `app/agent_runtime/workbench_agent.py`、`workbench_context.py`、`workbench_tools.py` |
| 工具观察协议 | `app/agent_runtime/results.py` |
| 业务用例、参数与当前视图 | `app/workbench_service.py`、`app/service_desk/views.py`、`app/domain/product_views.py` |
| 领域规则、SQL事务、确认、幂等与排期 | `app/service_desk/store.py`、`catalog.py`、`lifecycle.py`、`scheduling.py` |
| 资料目录、原件版本、增量同步 | `app/knowledge/catalog.py` |
| 唯一持久导入/索引任务队列 | `app/knowledge/jobs.py` |
| 同一知识服务的 Fast / Deep / 来源读取 | `app/knowledge/query.py`、`app/knowledge/service.py` |
| 检索、证据映射与唯一发布 | `app/retrieval/`、`app/agent/generation_v2.py`、`answer_publication.py` |
| 本机模型与实际发送记录 | `app/runtime/workbench_models.py` |
| React 三主入口 | `frontend/src/app/App.tsx`、`frontend/src/features/` |
| 自动生成前端 API 类型 | `python -m scripts.export_product_openapi` 后 `openapi-typescript frontend/openapi.json -o frontend/src/api/generated.ts` |
| 当前产品回归与可复现失败 | `tests/product/`、`tests/vnext/`、`tests/agent_v2/test_a1_draft_delivery.py` |

`workspace.py` 和 `workbench_knowledge.py` 是兼容导入位置，不是第二套实现。旧 `app.main`、Streamlit 和历史语义审查操作不是默认产品装配；按显式调用保留兼容，不回写历史实验结果。

当前产品模型只生产 source-unit 选择与 need 覆盖；旧 answer/claims 协议只在显式 legacy builder 中接受。正文、引用和最终覆盖由同一组映射和发布得到，不直接发布模型自由正文。合法来源仍不等于语义完整，真实质量单独记录。

模型工具循环不提交业务单。用户明确范围、选择或修改参数，并对当前精确预览确认；普通领域代码重新检查规则、版本和库存，再原子提交、幂等读回。运行失败不删除原消息、已应用事实或已产生的回执。

修改后先运行对应组件/产品 API 测试，必要时跑一条相关浏览器旅程。不要每次跑整个历史研究套件。真实模型、程序替身、浏览器与 Windows 产物结果分开登记。

运行记录的用户视图位于 app/runtime/run_views.py；只投影现有事件，模型工具名与工具实际结果分别显示。原件仍在既有 run_events 与 model_calls，不另建监控平台。产品迁移、失败以及未验证条件参见 RELEASE 与 CONTRACT_MIGRATIONS。
