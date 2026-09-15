# 当前模型：Qwen3.5

2026-09-12 按用户要求，将后续本地工作默认文本模型统一为已安装的 **qwen3.5:4b**。

- Ollama digest：`2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd`。
- 本机 tag 为 4b；Ollama 返回 parameter_size 4.7B、Q4_K_M 量化。无需重新下载。
- 回答生成、缺项恢复建议使用 CHAT_MODEL；证据模型使用 EVIDENCE_MODEL。两者现在都默认 qwen3.5:4b。
- Embedding 仍是 bge-m3，reranker、索引、Top-K 和权限逻辑不变。
- 不采用自动选择名字含 latest 的模型或按大小选模型；后续更新需确认实际已安装 tag。

## 修改入口

主目录 `app/config.py`、`.env`、`.env.example`、`deploy/compose.yaml`、`deploy/runtime.env.example` 已统一。候选树 `.private/release_candidate_20260910` 的相应配置及 `scripts/local_candidate.ps1` 同步，避免启动脚本覆盖成旧模型。

两处 PROJECT_STATUS.md 记录了这项持续使用偏好。主目录其余旧业务代码没有被替换成候选版；本次没有 commit、push 或部署。检查时旧候选 API/UI 都已停止，不需要强行中断用户进程。

## 验证

- 候选版：455 passed，包含当前模型配置、serving transport、readiness、容器约束及 tests/agent_v2。
- 主目录：26 passed，覆盖配置、serving transport、readiness 和容器约束。
- 本地真实调用：通过现有 serving_chat 向 qwen3.5:4b 发送 JSON schema 请求，think=false、seed=42，返回 `{"ready":true}`。这是一次兼容性 smoke，不是质量评测。
- 候选修改文件 Ruff 通过；主目录 app/config.py 有既有 I001 import 排序问题，本轮未顺带改写其旧代码。新增测试通过 Ruff。
- 初次扩大测试的运行包装器缺少 Windows multiprocessing main guard，导致子进程递归启动测试与超时。保留 candidate_checks 的 447 passed / 1 failed 及子进程输出，修复的是新包装器，不是原测试；最终 455 项完整通过。原始包装器另存 run_checks_initial.py，仅供诊断，不应执行。

原始执行证据：`D:\文档\agent\RAG_try\.private\model_default_qwen35_20260912`。包含新测试各轮日志、原始 JUnit、实际导入和源码指纹，以及 SMOKE.json。

## 不改变历史成绩

上一轮恢复实验的 29/40 -> 34/40 是 qwen2.5:3b 的开发诊断，不能改写为 Qwen3.5 结果。旧协议、旧报告及其审核 ZIP 保持不变。后续新质量评测默认使用 Qwen3.5，写入新目录并记录实际模型摘要；固定旧模型的复现实验必须明确标记历史复现。

此时只确认默认切换和接口兼容，尚未测量 Qwen3.5 对这批问题的质量差值，也未重跑 WixQA/FinanceBench 或修改简历指标。
