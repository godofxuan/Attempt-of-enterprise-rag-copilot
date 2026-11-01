# 本轮使用的外部资料

核查日期2026-11-01。仅用于状态与UI实现建议，不用于证明私有候选已经通过；不重新宣称项目Star数。

- React官方：Choosing the State Structure。https://react.dev/learn/choosing-the-state-structure
  采用：避免矛盾、冗余和重复保存的状态；保留当前React而非切换框架。
- TanStack Query官方：Invalidations from Mutations。https://tanstack.com/query/latest/docs/framework/react/guides/invalidations-from-mutations
  采用：显式选库或写入成功后刷新当前关联查询；不全局重建所有前端状态。
- TanStack Query官方：Query Keys。https://tanstack.com/query/latest/docs/framework/react/guides/query-keys
  采用：知识范围、会话和事项按正确身份参与数据查询；没有新增状态库的必要。

这些机制已是现有架构的一部分，本轮只完成恢复与接线，不因此扩张项目。
