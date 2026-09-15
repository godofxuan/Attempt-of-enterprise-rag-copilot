# 当前模型：Qwen3.5

2026-09-12 按用户要求，后续本地回答、缺项恢复和证据模型默认使用已安装的 **qwen3.5:4b**。

Ollama digest：`2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd`。无需下载。Embedding 仍为 bge-m3；reranker、索引和检索参数不变。

## 修改与检查

本候选树的 app/config.py、.env.example、deploy/compose.yaml、deploy/runtime.env.example 与 scripts/local_candidate.ps1 已统一模型配置。主目录对应配置和实际 .env 同步更新，两处 PROJECT_STATUS.md 留下长期使用偏好。

- 候选相关回归：455 passed。
- 主目录相关检查：26 passed。
- 真实 serving_chat JSON schema 调用：Qwen3.5 返回 `{"ready":true}`，think=false、seed=42。
- 候选文件 Ruff 通过。主目录有既有 config import 排序告警，未混入无关改动。
- 初次测试包装器的 Windows spawn 入口错误及其 1 failed 保留；修复包装器后完整重跑通过。未改原测试或业务逻辑来消除失败。

原始日志、JUnit、IMPORTS、源码指纹、SMOKE.json 在 `LOCAL_PATH_REDACTED`。完整说明另在主目录同名文档。

旧候选 API/UI 检查时均未运行。本轮没有启动服务、提交或推送 GitHub。

## 后续使用规则

新实验使用 qwen3.5:4b，不再默默使用 Qwen2.5。明确复现旧实验时仍可显式指定旧模型。

上一轮 29/40 -> 34/40 来自 qwen2.5:3b，不是 Qwen3.5 的效果；保持旧报告和审核 ZIP 不变，不能重命名冒充新成绩。后续 Qwen3.5 质量测试应新建协议/输出目录。本轮没有新质量分数、WixQA/FinanceBench 重测或简历指标修改。
