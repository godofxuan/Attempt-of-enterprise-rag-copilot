# Enterprise Agentic RAG - Current Status

更新时间：2026-07-17

状态：E7 本地自动化代码/数据门禁完成；功能分支 Git 交付与 clean-clone 结果由该分支实际 commit/remote 状态作为 authority。E0-E6 的代码、数据契约、评测、API、可观测性和演示已完成；E7 重新核对静态仓库、冻结数据、索引生命周期、deterministic 评测、真实模型/API、负载和真实浏览器。50 行人工语义评分与本人代码/口述验收仍是 `NOT RUN`，不计入通过项；没有 remote run URL 时 GitHub Actions 也是 `NOT RUN`。本文是唯一当前状态入口；`docs/PROJECT_STATUS.md` 与 `docs/AGENTIC_RAG_EVOLUTION_LOG.md` 只保留历史。

## 1. 当前定位

项目是一个本地、可评测、受控的 Enterprise Agentic RAG 工作流：

```text
synthetic corpus
-> normalized documents/chunks
-> immutable BM25 + FAISS index
-> ACL-aware search/find/open
-> bounded controller + evidence ledger
-> grounded generation + citation verification
-> safe API/trace/metrics
-> Ask/Trace/Evaluation demo
```

它不是生产 Agent 平台：没有真实 IAM、分布式持久 trace、增量索引、远程部署、多 Agent 委派或长期记忆。

## 2. 已实现能力

- E1：事实骨架、72/600 文档 synthetic profiles、dev/test 评估集与冻结 hash。
- E2：多格式 parser、DocumentRecord、fixed/heading/parent-child chunks、manifest 校验、不可变 index version 与 active pointer。
- E3：tenant/region/group ACL、BM25+dense+RRF、authority/temporal/diversity、search/find/open、EvidenceLedger、有界 controller、claim citations。
- E4：retrieval/response/agent/security 四层 evaluator、deterministic/live 隔离、失败 taxonomy、bootstrap CI、ablation 与 immutable run artifacts。
- E5：统一 safe error、request ID/deadline、liveness/readiness、模型 timeout/retry、trace/metrics、hash-only feedback、CI 配置与本地 load evidence。
- E6：最小披露 evidence trace、带 source hash 的 public snapshot、类型化 UI client、7 个 canonical demo cases、Ask/Trace/Evaluation 三页、真实 desktop/mobile 验收和公开仓库审计。
- E7：重新生成 deterministic test/ablation rc02 与 final-code load artifacts；核对 raw artifact hashes、public snapshot、active index、真实 API/browser；修复 trace 查询自覆盖和 EvidenceLedger 冲突优先级方向；强化所有 Markdown 的机器路径审计；逐条收窄 claims。

## 3. 当前证据

### 历史阶段基线

```text
E5 stage entry    526 passed, 3 warnings
E6 final          569 passed, 3 warnings
```

这些数字只说明测试随阶段增长的历史，不是可以相加的指标。

### E7 最终本地门禁

```text
574 passed, 3 warnings
```

`pip check` 无依赖冲突，`compileall` 覆盖 `app/scripts/streamlit_app/tests`，frozen test hash 完全一致，最终 staged public repository audit 为 331 candidates / 0 findings，`git diff --cached --check` 退出 0。3 条 warning 仍只来自 FAISS SWIG 类型弃用提示。

### 评估与负载

| 证据 | 结果 | 说明 |
|---|---:|---|
| E7 deterministic frozen test rc02 | 28/28 | test SHA-256 `556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338`；stable hash/extractive runtime |
| retrieval | recall@5 1.0000；precision@5 0.2381 | 找到 gold 不等于 top-5 全部相关，不能简写为“检索准确率 100%” |
| agent trajectory | exact 24/28；outcome 28/28 | 多条合法轨迹可到达同一安全终态 |
| canonical live dev | 23/24 | 一次本地 BGE-M3 + Qwen run；保留 1 个 system-runtime failure |
| direct injection | 4/4 | unsafe、检索前、零工具、零 source；只覆盖 direct user prompts |
| E7 final-code load rc02 | 31/31 | 本机 warm concurrency 1/5/10 p95 为 1.115/4.244/8.218 s；不是 SLO |
| workflow ablation | fixed RAG 0.8571 vs bounded Agentic 1.0000 | 28 个 synthetic cases；工具调用从 28 增至 47 |

[`data/v2/public/demo_snapshot.json`](data/v2/public/demo_snapshot.json) 是单独标注的 E4/E5 历史离线演示批次，仍显示较早的 load r2 数值；它不冒充 E7 rc02。E7 新 run 位于被 Git 忽略的 `eval_runs/` 与 `load_runs/`，其 manifest 和 artifact hashes 记录在 [E7 Final Acceptance Journal](docs/roadmap/e7_final_acceptance_implementation.md)。

## 4. E7 新发现和修复

真实 API 复验发现：如果 Trace GET 故意复用目标业务请求的 `X-Request-ID`，旧 middleware 会把“读取 trace 的请求”也以相同 ID 写入 trace buffer，第二次查询可能取到观测请求而不是原业务请求。

修复位于 `app/api/middleware.py`：trace 查询仍记录 metrics、仍回显 `X-Request-ID`，但不再写回 `TraceSink`。回归测试位于 `tests/api_v2/test_observability_api.py`，同时锁定两次查询都返回原 `/agent/v2/chat`、header 一致，以及 trace 路由 metrics 计数为 2。

独立最终审查还发现 `app/agent/evidence_ledger.py` 原来用 `support_priority != conflict_priority` 判断冲突是否解决，导致低 authority/retired 支持证据也可能压过高 authority/active 冲突。修复为严格 `support_priority > conflict_priority`，并增加两种反向 RED/GREEN 回归。公开审计也从少量 allowlist 文档扩大到所有 Markdown，清除了 13 个本机绝对路径暴露点。

## 5. 当前公开演示

- Ask：真实 `/agent/v2/chat`，显示 UserContext、mode、stop、claim verification、authorized sources 和 feedback。
- Trace：显示 evidence coverage、action sequence、budget、request spans、model calls/retries；不展示问题、身份或 source preview。
- Evaluation：严格读取 public snapshot，展示 quality、ablation、runtime、security 与 source hashes。
- Browser：桌面三页均为 1440/1440；移动端三页均为 390/390；图表非空、无页面级横向溢出，浏览器 error 为 0。

启动与停止步骤见 [Demo Runbook](docs/demo_runbook.md)。

## 6. 明确 NOT RUN 或不能外推

- Retrieved-content indirect prompt injection：`NOT RUN`，当前 corpus 没有专门 fixture。
- Optional reranker：`NOT RUN`，没有 admitted reranker。
- Human semantic review：`NOT RUN`；50 行表仍为空，等待本人判断。
- Owner code experiments and oral defense：`NOT RUN`；Codex 不能代替本人完成。
- GitHub remote CI：没有可核验 run URL 时保持 `NOT RUN`，本地通过不能替代远端 runner。
- 当前 ACL 使用调用方自报 `UserContext`，不是 IAM；数据全部 synthetic；本地 load 不是生产吞吐/SLO。
- 本次只推送功能分支，不自动 merge、tag、修改默认分支或仓库可见性。

## 7. 权威文档

- 项目入口：[README](README.md)
- E7 验收：[E7 Final Acceptance Journal](docs/roadmap/e7_final_acceptance_implementation.md)
- 系统边界：[Architecture](docs/architecture.md)
- 安全边界：[Threat Model](docs/security_threat_model.md)
- 评估定义：[Evaluation Protocol](docs/evaluation.md)
- 已知限制：[Known Limitations](docs/known_limitations.md)
- E6 历史实施证据：[E6 Implementation Journal](docs/roadmap/e6_demo_public_repo_implementation.md)
- 跨阶段恢复：[Current Execution Handoff](docs/roadmap/CURRENT_EXECUTION_HANDOFF.md)
