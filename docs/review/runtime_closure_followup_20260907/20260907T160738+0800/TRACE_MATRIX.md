# 固定版本真实链路核验

## 身份与阅读范围

基线：`c9984e92a10a6f417e2c1d8082af7e8f1e11aee1`。
修改后身份：同一 HEAD + 未提交补丁；最终源码指纹见 `SOURCE_FINGERPRINT.json`。
本文引用函数在未修改文件中均对应基线，在三个修改文件中对应该最终指纹；不混用行号。

完整阅读 README、旧 RESULTS、EXECUTION、原交付计划；按真实 schema 解析全部 800 检索行、775 服务行、87 CSV 分组、manifest 和冻结协议。
重点逐函数追踪服务构造、V2 runner/controller/registry、检索/导航/准入、交付 packet、生成/引用、索引版本治理、模型传输与 readiness。
读取相应测试、pytest/conftest、依赖约束及 CI 配置。历史 CI 的任务和步骤状态已通过只读 API 核对；原始 job 日志请求返回 403。
这不是全仓库逐文件安全审计：旧 FinQA 全部实验实现、全部 durable/MCP 后端和所有 UI 页面没有逐行复审。它们存在或通过全套测试，不能替代默认 HTTP 接入证明。

## 可达性与断言矩阵

| 声明/范围 | 实际入口、调用者与关键分支 | 测试/证据 | 状态与限制 |
|---|---|---|---|
| 默认 HTTP 问答 | `app.main.create_app` 注册 `/agent/v2/chat`；路由调用容器的 `run_agent_v2_chat`，进入 `runner_v2._get_default_v2_runner` / `V2AgentRunner.run` | `tests/api_v2/test_runtime_closure_flow.py` 实际应用、JWT、路由、默认 factory、索引参与 | 确定性服务路径 VERIFIED；模型/embedding/readiness 使用明确 stub |
| GPU 服务入口 | `app.serving.create_app` 保留原应用/lifespan；仅显式 `safe_dense_raw*` profile 执行本地 scorer warmup；`ServingRetrievalSettings` 读取服务端环境 | `tests/runtime` serving 测试、新 HTTP Top20 测试 | 可选路径；不是默认 Hybrid，不接受客户端任意模型路径 |
| 默认 Agent 决策 | `V2AgentRunner._run` 调用 `controller.initialize/next_decision/observe`，直接执行 `registry.run` | `tests/agent_v2` controller/runner 测试；新增 HTTP 测试 | 每个 required aspect 有界 search；completeness 可 open；默认不选择 find，不自动 rewrite/retry |
| ToolGateway/LangGraph/MCP | `app.agent_runtime.orchestrator._ContractToolSession` 经 `ToolGateway` 执行适配器；harness/替代后端入口 | 原有 `tests/agent_runtime`；README 架构图对照 | 非上述默认 HTTP 直达调用链；不得将 README 的统一框架图当作默认 HTTP 实测轨迹 |
| 权限先于模型候选 | `SearchPipeline._resolve_visible_scope` -> `AccessPolicy.visible_indices` -> `_matches_filters`；Dense 内部全索引打分后只返回可见集合，BM25 对可见集合评分 | `test_pipeline_acl.py`, `test_pipeline_ranking.py`；新增 `test_excluded_content_reaches_neither_scorer_nor_llm` | tenant、groups、supporting、Guard 四个排除对照已测；合法内容仍进入模型输入，非全拒绝假通过 |
| 重排前完整准入 | `tools_v2.V2ToolRegistry` -> `reranking_admission`，原始池截 Top20 -> 正文/metadata/相关 parent/split 扫描 -> scorer -> 去重 TopK；错误不补入未扫描候选 | `test_admitted_reranking.py`（含 poisoned metadata scorer spy）、`test_retrieved_admission.py`；新 HTTP scorer/LLM spy | 已测范围 VERIFIED；新 HTTP marker 测试重点是正文排除，标题/parent/split 还依赖既有组件回归；不称任意未知攻击已证明安全 |
| 请求身份与缓存 | runner 缓存 key 含 root/run/manifest/config，至多 2 项；用户、Ledger、预算按请求创建；`search_many` 的共享向量/分数缓存不会替代每次 visible scope 过滤 | `test_pipeline_ranking.py`, `test_runtime_delivery_index_binding.py`, 身份/API 套件 | 非跨用户答案缓存；没有新建 ACL 架构；不承诺任意外部 IdP 即时撤销 |
| 导航不可相信客户端 ID | `DocumentNavigator.open/find` 检查可见性；`navigation_binding` 将结果与同 snapshot、文档/target、文本绑定 | `test_navigation_binding.py`, `test_navigation_zero_leak.py` | 旧引用/跨 tenant 反例已有；find 存在不等于默认 controller 会调用它 |
| 请求级快照 | factory 每次解析 active pointer；`V2AgentRunner.run` 工具前/发布前校验绑定，激活时间戳变化也会失败关闭 | `test_runtime_delivery_index_binding.py` 激活/删除/回滚、并发/多进程；新 HTTP 删除制度回归 | 在途变更返回无来源 system；不撤回已经发往客户端的字节，不宣称分布式线性一致性 |
| relevance 不等于回答充分 | `evidence_relevance.has_query_anchor_support`、`answer_contract.answer_sufficiency` -> `GenerationV2ResponseBuilder.build` 最终映射 | 新增两份回归；`logs/baseline_new_regressions.log.txt` 和 `logs/final_targeted.log.txt` | 两个明确缺陷修复；任意自然语言 entailment 仍 NOT_VERIFIED |
| 最终证据视图 | `domain.evidence_packet` 生成预算后 DeliveredEvidence；`generation_v2` 用同一 view 组装 prompt/验证/fallback；`citation_verifier.verify_claims` 绑定 field/offset/index/version | 原 packet、generation、navigation、critical span 测试；新数值条件正反例 | 精确来源一致不等于事实真实或答案完整；历史个案完整原始 prompt/LLM 输出未保存，不能重建其全部中间内容 |
| 数值/条件边界 | `citation_verifier` 关键句完整 span；`complete_evidence_prefix` 不保留半个句子；只能做现有空白/大小写等明确等价 | 新 units/subject/upper-limit/approval 7 组对照；既有 negation/critical span/packet suite | 未放宽支持规则；一般表格跨页推理、任意合法改写仍可能保守 partial |
| 冲突真实限制 | `ingestion.versions._validate_version_graph` 限定每 policy 一个 active authoritative 版本；`EvidenceLedger._numeric_conflicts` 只同 policy/version/scope 的单值模板比较 | 新非法双权威夹具拒绝测试、合法单文档冲突 HTTP 测试 | B1 两独立权威文档 NOT_REACHABLE_CURRENT_CONTRACT；单文档 host excerpts VERIFIED，不走 LLM 选边 |
| 最终 trace | runner 在 builder 返回后写 `controller_stop_reason`、最终 `stop_reason/final_mode` | 新审批关系缺失 HTTP 测试；既有 runtime delivery trace 测试 | 不能把 controller 曾经决定 answer 解读为最终回答成功 |
| 预算/模型身份 | `serving_chat` 每次 num_ctx=8192 / num_predict=1024；model transport 有限重试和 request deadline；packet 使用 UTF-8 byte 保守估计，不是精确 tokenizer | `tests/runtime`, `tests/agent_v2`；冻结协议与本地 tags/六文件 BGE hash | 没有换模型/调参；query embedding、离线 corpus embedding、候选准入是三个不同边界 |
| 容量/ready | `LocalCrossEncoder.__call__` 锁等待 250ms、finally 释放；`ServingRuntimeResources.refresh_if_stale` 半 TTL 唤醒原 worker；模型身份周期检查，启动做真实探针 | 原 serving/runtime capacity/deadline/readiness 测试 | 拒绝/OOM/超时不能伪装 ready；超时丢弃结果不等于中止 GPU kernel；没有长期 SLA |
| 证据三层核验 | 旧 exporters 原样重放；新 `scripts.verify_runtime_closure.verify` 独立读公共目录与显式 gold 目录 | `BYTE_EXPORT_REPLAY.json`, `VERIFICATION_REPORT.json`, verifier 17 项测试 | Hash/aggregate/gold 三层分开；不重跑历史模型，不回填真人评分 |

## 当前缺失材料

- 历史个案的完整生成原始响应和预算后 packet 原文：原行只含最终答案、引用 span、packet hash/计数，不能用 hash 反推原文。
- 检索 dirty 源码总摘要对应的完整字节归档没有恢复；服务源文件比对范围见 `HISTORICAL_SOURCE_CHECK.json`。
- 本轮 GPU Python 环境缺 `docx`，一次确认在索引准备阶段停止，推理/主请求均为 0；没有用 stub 填补。
- 人类独立问题和预期签核缺失；新的非 Windows/PostgreSQL/container 执行未运行。
