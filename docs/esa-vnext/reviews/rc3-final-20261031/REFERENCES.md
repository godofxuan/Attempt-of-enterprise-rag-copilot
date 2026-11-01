# 参考实现（2026-10-31实际打开）

不重新报告star数或声称固定排名。参考主分支可能继续变化；学习机制而非复制部署平台。

## R01 Open WebUI：前端随后端发行
https://raw.githubusercontent.com/open-webui/open-webui/main/pyproject.toml

保留已有React构建随Python发行的路线，不新增运行时前端服务，不搬完整平台。

## R02 Onyx：上下文与来源表示
https://raw.githubusercontent.com/onyx-dot-app/onyx/main/backend/onyx/chat/README.md

模型看简洁相关内容，UI保留丰富来源；学习职责，不复制大系统。

## R03 Dify：工作流到应用事件
https://raw.githubusercontent.com/langgenius/dify/main/api/core/app/apps/workflow_app_runner.py

区分等待输入、部分结果、失败、成功的应用呈现；不引入Dify引擎。

## R04 React：状态结构
https://react.dev/learn/choosing-the-state-structure

不重复持久化可由服务器事实计算的界面状态。

## R05 TanStack Query：mutation后刷新
https://tanstack.com/query/latest/docs/framework/react/guides/invalidations-from-mutations

当前组件使用既有定向缓存更新，保留已成功保存。

## R06 Playwright：用户行为测试
https://playwright.dev/docs/best-practices

按按钮/输入/用户结果测试，不通过CSS内部结构证明业务。

## R07 SQLite：WAL
https://www.sqlite.org/wal.html

读写并发不等于多写者；保持短事务，不为此迁移数据库。

## R08 FastAPI：lifespan
https://fastapi.tiangolo.com/advanced/events/

当前应用工厂管理资源启动/关闭，不在每次请求创建重型依赖。

用户上传源码是本轮本地实现依据。引用锚点见teaching/SOURCE_MAP.json；公开资料不替代私有项目的代码判断。
