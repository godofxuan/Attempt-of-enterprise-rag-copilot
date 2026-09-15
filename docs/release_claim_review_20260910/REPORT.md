# 2026-09-10：上线判断与简历指标复核

## 结论先说

这个项目已有可展示、可写进简历的实际工程成果，不需要等到所有问答都正确。
建议进入**低风险、只读、带原文引用、有人复核的受控内部试用准备**。
这不等于当前候选已经部署生产，也不适合直接代替财务审批、授权决策等高影响操作。

本轮只做只读核验、离线复算和简历更新协调，没有修改业务源码、提交、推送、部署或切换索引。
不存在一个适用于所有 RAG 应用的“80% 就能上线”阈值。关键是错误的后果、试用范围、人工接管和可回退性。

## 实际核验对象

- 主目录：`D:\文档\agent\RAG_try`，`main@c9984e92a10a6f417e2c1d8082af7e8f1e11aee1`。
- 实际候选：`D:\文档\agent\RAG_try\.private\runtime_closure_20260907T160738`。
- 候选分支：`fix/runtime-closure-20260907T160738`。
- 候选已提交 HEAD：`b07c03d0256c393db5dfbb969e5d20abd70155b0`，另有真实未提交修改。
- 当前 950 个 Python 源文件指纹：`677f35a979c2ac41e5d6b3b8f2f1cee02a2bfb21d43d0a8e742e52fbccad1f8c`。

HEAD 不能单独代表本次通过复核的源码，必须同时保留快照与上述指纹。
不能把本地修复说成已经合入 GitHub main。

## 本轮实际做了哪些检查

1. 检查交付 ZIP 的 SHA-256、CRC、5758 个清单文件的摘要。
2. 比对当前候选全部 950 个 Python 文件与 ZIP `source_after/`，一致。
3. 从旧、新两轮原始响应中分别选取 240 次主请求，检查 40 个唯一用例、配置和重复编号配对。
4. 绑定原协议、原索引 manifest，调用未修改的 `scripts.eval_runtime_service.score_response` 重算全部 480 条，结果与保存的逐条评分完全相同。
5. 检查实际 `app.*` / `scripts.*` 导入均来自候选工作树；核验前后源码不变。
6. 读取原始 JUnit，核实软件回归计数；没有把旧日志当作本轮新跑的 pytest。
7. 沿实际 FastAPI 入口、V2 Controller、LangGraph 适配器、serving 配置、Docker 和 Compose 检查发布接线。

本轮真实模型调用数为 0，没有再次运行 800 条检索或历史大型实验。
本轮新增核验材料在 `.private/release_claim_review_20260910/confirmed/`。
初次核验辅助脚本的文件计数元数据误用了变量，已在新目录修正为 5758；原结果保留，见同目录上级 `ERRATUM.md`。480 条评分未受影响。

## 可以说的效果

| 指标 | 修复前 | 修复后 | 解释 |
|---|---:|---:|---|
| 本地 API 自动回归用例通过 | 170/240，70.83% | 193/240，80.42% | +9.58 个百分点 |
| hybrid 配置通过 | 86/120 | 97/120 | 同一固定协议 |
| safe raw20 BGE 配置通过 | 84/120 | 96/120 | 同一固定协议 |
| 标记 answered 但未通过既定合同 | 5 | 0 | 只覆盖该有限检查，不是所有语义错误 |
| HTTP 503 主请求 | 6 | 0 | 本地该轮观察，不是线上可用率 |

这是 40 个固定合成用例、2 种配置、3 轮运行的 240 次主请求。请求走认证 FastAPI 与本地真实模型，评分为既有状态、短语、来源、引用、权限等有限自动合同检查。
因此可以写“本地 API 自动回归通过率”，不能写“240 道独立真实业务问题的答案准确率”。

配对细看是 39 次由失败变通过、16 次由通过变失败，净增加 23 次；仍有 47/240 次未通过。
退化包括交接和供应商多诉求问题各 6 次、接待多诉求 2 次、报销事实及权限撤销流程各 1 次。
不能只展示净提升就断言每种问题都变好了，也不能把波动全归因于单个代码改动。

按原协议已有 category 对全部请求分组，结果如下。没有重新筛选测试数据：

| 原协议类别 | 唯一题数 | 前轮通过 | 后轮通过 |
|---|---:|---:|---:|
| fact：单项事实 | 10 | 54/60 | 59/60 |
| procedure：流程 | 6 | 27/36 | 29/36 |
| multi_table：表格与多项要求 | 6 | 19/36 | 9/36 |
| acl：权限场景 | 6 | 29/36 | 36/36 |
| lifecycle：版本生命周期 | 6 | 14/36 | 30/36 |
| boundary：边界与拒答 | 6 | 27/36 | 30/36 |

这张表不用于把事实子集的 59/60 包装成整个系统的 98.3% 准确率。
`multi_supplier` 的原始正文包含营业执照、银行账户证明两项，但有限条款检查计为 1 项并标记 partial；`multi_handover` 也有同时匹配两项短语和来源却未满足状态要求的响应。
这是保守发布造成的可用性损失，不是可以改判通过的理由。`table_meal`、`table_freight` 各 6 次 not_found，属于另一个实际缺口，不能都归为状态过严。
因此初次试用不能承诺完整材料清单、复杂表格或多条件问题可靠答全；必须展示原文并由用户复核。进一步改善应针对这些已定位的问题，不需要笼统增加模型。

| WixQA ExpertWritten 200 题固定回顾性检索 | Macro Article Recall@5 | nDCG@5 |
|---|---:|---:|
| Dense reference | 65.92% | 52.08% |
| Safe raw20 BGE | 72.25% | 59.20% |
| Safe raw50 BGE | 74.25% | 59.93% |

上一轮最终源码已完成 200×4 配置的 800 次检索复测，排名和指标没有相对前轮改变。
简历原有 Dense 到 raw50 的成果仍成立，但不是本轮又提高了检索质量。
raw50 是最佳实验档位；raw20 是已有 FastAPI 可选服务档位。默认配置仍是 hybrid，而不是 raw50。
这些是检索指标，不是回答准确率，也不是新的人类独立测试集结论。

## 实现及默认接线核对

- `app/main.py:120` 的 `/agent/v2/chat` 调用 `run_agent_v2_chat`。
- `app/agent/runner_v2.py:214` 使用 `V2AgentController`；其运行循环经工具注册表执行受限 search/find/open 等动作。
- `app/agent_runtime/orchestrator.py:524` 存在真实 StateGraph 编排；`durable_orchestrator.py:750` 存在持久化审批恢复图。
- 因此 LangGraph 可以列为项目实现，但不能把本轮默认 API 测试说成 StateGraph 链路评测；也不能把直接 Python 补读调用说成 MCP 调用。
- 本轮前序修复涉及证据相关性、引用完整单元前缀校验、重复上下文处理、有限诉求缺项发布和 readiness 刷新。这次没有新增 LLM，也没有训练模型。

## 上线前真正缺的内容

### 1. 固定可部署产物

候选仍有未提交修改；需要在得到发布授权后固化精确源版本、依赖、模型和索引绑定，构建不可变产物。
不是直接把历史 main 当作最新源码部署。

### 2. 让部署配置与验证配置一致

`app/serving.py` 推荐 `uvicorn app.serving:create_app --factory --workers 1`，包含启动重排 warmup 和 serving 资源探测。
当前 `Dockerfile:37` 启动的是 `app.main:app`；`deploy/compose.yaml` 没有固定 `V2_RETRIEVAL_PROFILE`、reranker 路径/设备及相应模型挂载。
这不证明容器必然无法启动，但证明不能将已有 Docker 配置当作本轮 raw20/GPU 结果的等价部署。
需要在实际目标机完成身份、索引、模型启动、就绪、请求、重启与回退烟测。
Compose 当前健康检查只查 liveness；上线接流量时还必须核对 readiness。

### 3. 处理尚未通过的发布证据绑定

前轮完整软件回归为 **3921 passed、2 failed、32 skipped**，不是全绿。
两个失败是历史证据与当前 `resources.py` 源码摘要绑定：

- `test_e16_public_evidence_binds_protocol_sources_and_implementation`
- `test_public_trusted_identity_result_recomputes_exactly`

另有本轮对应机制的定向证据，不会自动把这两个旧失败变为通过。
应保留历史证据，建立明确的新版本证据绑定并验证发布门禁；不能删断言或修改旧报告消除失败。
现有 CI 的容器任务依赖软件测试，因此不能宣称当前候选已经通过发布 CI。
32 项跳过包含平台能力与未配置 PostgreSQL 等范围，不能计入通过。

### 4. 用业务风险限定试用

建议初次试用限定少量授权用户、只读制度查阅、可点击原文、明确部分回答/拒答，不能自动审批或授权。
目标环境还需访问入口保护、必要 TLS/反向代理、限流和并发预算、监控负责人及回滚操作。
抽取代表性真实问题做人审，记录误答后果、缺项、可用率与用户反馈，再决定扩大范围。
当前没有真实企业流量验收、人工语义正确率和生产容量/SLO 证据。

这是发布工作，不是必须再叠加数据库、更多 Agent 或模型。
FastAPI 官方部署说明将 HTTPS、重启、进程与内存等作为独立部署事项；OWASP 对高影响 Agent 行为建议最小权限、下游授权和人工批准。
参考：[FastAPI Deployment Concepts](https://fastapi.tiangolo.com/deployment/concepts/)、[OWASP Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)。

## 简历的适合表达

1. 在 WixQA ExpertWritten 200 题固定回顾性检索评测中，以 BGE-M3 召回、Guard 前置与 BGE 重排，将 Recall@5 从 65.92% 提升至 74.25%，nDCG@5 从 52.08% 提升至 59.93%。说明 Top50 实验与 Top20 服务接线的区别。
2. 在固定 40 题、双配置三轮本地 API 自动回归中，将用例通过率从 70.8% 提升至 80.4%；完善证据相关性、引用校验与缺项处理，保留有据内容并明确部分回答。
3. 实现服务端权限与证据准入、受限检索补读和答案核验，并为访问审批草稿实现持久化恢复与幂等控制。LangGraph 放在真实实现的编排/恢复范围，不冒充默认接线。

正式一页简历应采用成果前置的短句，不应塞入整个审核报告。上述说明与完整失败记录留在面试证据材料。
禁止表述：已生产上线、线上准确率 80.4%、240 个独立业务问题、零幻觉、所有场景解决、稳定显著提升、生产 p95/SLO 已验证。

## 文件入口

- 本报告：`D:\文档\agent\RAG_try\docs\release_claim_review_20260910\REPORT.md`
- 重算结果：`D:\文档\agent\RAG_try\.private\release_claim_review_20260910\confirmed\RESULTS.json`
- 原始评分重算：同目录 `RECOMPUTED_SCORES.json`
- 导入与输入摘要：同目录 `IMPORTS.json`、`INPUT_HASHES.json`
- 原完整交付 ZIP：`D:\文档\agent\RAG_try\.private\broad_validation_fixes_20260910\RAG_VALIDATION_FIXES_20260910.zip`
- ZIP SHA-256：`beb14ac5e2306648bb5e99c858d76f406dd144619713482f003a5e91c20a5df5`
- 正式简历入口由维护任务更新：`D:\文档\工具\CURRENT_RESUME_POINTER.md`

最终判断：**证据足以支持上述简历成果；值得进入受控试用发布准备；尚不能声称已经完成生产发布。**
