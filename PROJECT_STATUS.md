# Enterprise Agentic RAG - Current Status

更新时间：2026-07-17

状态：E7 自动化代码/数据门禁、功能分支 Git 交付、GitHub clean clone 和 Ubuntu GitHub Actions 均已完成。R2-S1 已完成 D1 协议冻结、D2 红色数据流基线、D3 独立 Guard 核心、D4 数据流接入和 D5 prompt/trace/secure-profile lifecycle 本地实现；D6 安全评测尚未授权。D5 当前只在本地分支，尚无对应远端 CI 证据。50 行人工语义评分与本人代码/口述验收仍是 `NOT RUN`，不计入通过项。本文是唯一当前状态入口；`docs/PROJECT_STATUS.md` 与 `docs/AGENTIC_RAG_EVOLUTION_LOG.md` 只保留历史。

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
- E7：重新生成 deterministic test/ablation rc02 与 final-code load artifacts；核对 raw artifact hashes、public snapshot、active index、真实 API/browser；修复 trace 查询自覆盖和 EvidenceLedger 冲突优先级方向；强化所有 Markdown 的机器路径审计；逐条收窄 claims；完成 feature-branch push、四轮 clean-clone 故障闭环与 Ubuntu CI。
- R2-S1 D3：新增严格冻结的 `GuardDecision` 和 model-free `RetrievedContentGuard`；对原文建立 20,000 字符有界视图，执行 NFKC/casefold、Unicode `Cf` 控制符处理、有限同形字、结构化规则组合和单层有界 Base64 检查；单项异常与规则预算耗尽均 fail closed。
- R2-S1 D4：在 ACL 过滤后的单次 `candidate_k` 排名池与 Controller 之间加入 mandatory admission；扫描正文、parent、metadata、find/open 和有界相邻 split，隔离后从同一池最多补位一次；工具只返回 guarded execution，Controller、ledger、generation 和 citation 路径只接受 admitted 类型，raw bypass fail closed。
- R2-S1 D5：生成器使用 fresh per-model-call nonce、JSON admitted records 和 trusted reminder；tool step 只公开 allowlisted Guard aggregate；默认 App 移除 `/ingest`、`/chat`、`/agent/chat`，legacy 仅由显式 compatibility factory 注册；startup/readiness 验证 detector policy 且只公开 `retrieved_guard=ready|error`。

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

### R2-S1 D3 本地门禁

```text
Guard core unit tests                         64 passed
security regression excluding D2 RED          84 passed
agent/retrieval regression excluding D2 RED  116 passed
full regression excluding D2 RED             638 passed
D2 data-flow probes unchanged                  5 failed / 3 passed
public repository audit                      352 candidates / 0 findings
```

`rcg-v1.0.0` 的规则集 SHA-256 是 `a544f013e5570b24488220b3ba11c721a2c6e05b2a4895b027dd0601363bbdb0`。这组结果只证明独立核心及其回归，不表示运行时已经拦截检索投毒。

### R2-S1 D4 本地门禁

```text
guarded tool/no-egress focused             6 passed
Agent V2                                  98 passed
D2/D4 propagation and top-up               8 passed
full offline repository suite             687 passed
warnings                                    3 known FAISS SWIG warnings
public repository audit                   359 candidates / 0 findings
```

当前 detector policy 为 `rcg-v1.1.0`，规则集 SHA-256 是 `dcafd504a01dcc757910751503eaaf1387903827e5e0f4932fbdd7937b68da01`。D4 证明默认 V2 本地运行路径在 Controller 前执行 Guard，并不等于未知攻击免疫，也不替代 D6 的 72-case OFF/ON 评估。

### R2-S1 D5 本地门禁

```text
initial D5 RED                          17 failed / 10 passed
focused D5 GREEN                       27 passed
expanded Agent/security/API/runtime   229 passed
final offline repository suite        697 passed
warnings                                3 known FAISS/SWIG warnings
public repository audit               362 candidates / 0 findings
```

D5 没有改变 detector rules，所以 version/hash 保持不变。新增 adversarial tests 覆盖普通和 Unicode delimiter escape、每个模型调用 fresh nonce、active ruleset/provenance drift、aggregate-only trace、secure route exclusion 和 low-sensitivity readiness。完整说明见 [D5 Engineering Journal](docs/security/r2_s1/07_d5_engineering_journal.md)。这些是 implementation contracts，不是攻击成功率。

### GitHub 交付与远端复现

代码候选 `9607e55ec0fc12e98d1f61e199bfbf6ac12a0eee` 已推送到 `origin/codex/rag-eval-system`。第四个全新 GitHub clone 得到 frozen hash exact、compile exit 0、public audit 331/0、full pytest 574 passed。Ubuntu/Python 3.11 的 [GitHub Actions run 29553278709](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/29553278709) 为 `success`。这些证据覆盖当前功能分支候选，不代表已 merge、部署或达到生产 SLO。

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

首次远端 CI 还暴露了 Windows 未复现的 Linux `exit 139`。诊断工作流用 `faulthandler` 和失败上下文注释定位到 UI 测试读取 `DataframeElement.value` 时，Streamlit 测试框架在 PyArrow-to-Pandas 反向转换中段错误。产品页面生成 Arrow 数据本身已成功，真实浏览器也不执行该反向路径；因此修复测试边界，改为验证 6 个 dataframe 元素及相邻可见 provenance/status，而不是调用测试专用 `.value`。目标测试、本地 574、clean clone 574 和远端 run 均通过。

## 5. 当前公开演示

- Ask：真实 `/agent/v2/chat`，显示 UserContext、mode、stop、claim verification、authorized sources 和 feedback。
- Trace：显示 evidence coverage、action sequence、budget、request spans、model calls/retries；不展示问题、身份或 source preview。
- Evaluation：严格读取 public snapshot，展示 quality、ablation、runtime、security 与 source hashes。
- Browser：桌面三页均为 1440/1440；移动端三页均为 390/390；图表非空、无页面级横向溢出，浏览器 error 为 0。

启动与停止步骤见 [Demo Runbook](docs/demo_runbook.md)。

## 6. 明确 NOT RUN 或不能外推

- Retrieved-content indirect prompt injection：D1 design/protocol 已冻结；D2 的历史红色基线是 `5 failed / 3 passed`；D3 standalone Guard core、D4 guarded data flow 和 D5 prompt/public observability 已完成本地确定性验证。完整 72-case fixture 和 deterministic/live OFF/ON evaluation 仍为 `NOT RUN`。
- Optional reranker：`NOT RUN`，没有 admitted reranker。
- Human semantic review：`NOT RUN`；50 行表仍为空，等待本人判断。
- Owner code experiments and oral defense：`NOT RUN`；Codex 不能代替本人完成。
- GitHub remote CI：当前 `9607e55` 对应 run 已通过；只证明该 feature-branch commit 的 Ubuntu CI，不外推为 branch protection、部署或生产验收。
- 当前 ACL 使用调用方自报 `UserContext`，不是 IAM；数据全部 synthetic；本地 load 不是生产吞吐/SLO。
- 本次只推送功能分支，不自动 merge、tag、修改默认分支或仓库可见性。

## 7. 权威文档

- 项目入口：[README](README.md)
- E7 验收：[E7 Final Acceptance Journal](docs/roadmap/e7_final_acceptance_implementation.md)
- 系统边界：[Architecture](docs/architecture.md)
- 安全边界：[Threat Model](docs/security_threat_model.md)
- 评估定义：[Evaluation Protocol](docs/evaluation.md)
- 已知限制：[Known Limitations](docs/known_limitations.md)
- R2-S1 D2-D5 结果：[Security Results](docs/security/r2_s1/05_results.md)
- R2-S1 D4 逐步工程日志：[D4 Engineering Journal](docs/security/r2_s1/06_d4_engineering_journal.md)
- R2-S1 D5 逐步工程日志：[D5 Engineering Journal](docs/security/r2_s1/07_d5_engineering_journal.md)
- E6 历史实施证据：[E6 Implementation Journal](docs/roadmap/e6_demo_public_repo_implementation.md)
- 跨阶段恢复：[Current Execution Handoff](docs/roadmap/CURRENT_EXECUTION_HANDOFF.md)

## 8. R2-S1 当前状态

R2-S1 的 D0 只读审计、D1 威胁模型/评测协议冻结、D2 红色基线、D3 独立 Guard 核心、D4 guarded data flow 和 D5 prompt/security observability 已完成。D3 从已提交的 D2 基线 `c1c47dfe88c42c309afc32faa9bc6584e90e89ac` 开始；D4 从已提交的 D3 基线 `ec85cc718b3df17731fb1d9df7300a3a7c6fe5be` 开始；D5 从 `86064322fd532264623abd23e8db7a99634ab342` 开始。权威设计与结果位于：

- [R2-S1 总设计](docs/superpowers/specs/2026-07-17-r2-s1-indirect-prompt-injection-design.md)
- [Scope and threat model](docs/security/r2_s1/00_scope_and_threat_model.md)
- [Attack surface and trust boundaries](docs/security/r2_s1/01_attack_surface_and_trust_boundaries.md)
- [Design decisions](docs/security/r2_s1/02_design_options_and_decisions.md)
- [Detailed schema design](docs/security/r2_s1/03_detailed_design.md)
- [Evaluation protocol](docs/security/r2_s1/04_evaluation_protocol.md)
- [D2-D5 results](docs/security/r2_s1/05_results.md)
- [D4 step-by-step engineering journal](docs/security/r2_s1/06_d4_engineering_journal.md)
- [D5 step-by-step engineering journal](docs/security/r2_s1/07_d5_engineering_journal.md)

当前状态必须逐层表述：

```text
design/protocol                         D1 FROZEN
D2 propagation baseline                5 EXPECTED RED / 3 EXISTING BOUNDARY PASS
RetrievedContentGuard standalone core  D3 GREEN / 64 TESTS
runtime guarded data flow              D4 GREEN / 8 BOUNDARY PROBES
full offline regression                D5 GREEN / 697 TESTS
prompt nonce/public security counters   D5 GREEN
malicious/benign security datasets      NOT RUN
deterministic guard OFF/ON evaluation   NOT RUN
local live guard OFF/ON evaluation      NOT RUN
```

D3 detector 位于 `app/domain/retrieved_security.py` 与 `app/security/retrieved_content.py`；D4 admission 与强制接入位于 `app/security/retrieved_admission.py`、`app/retrieval/pipeline.py`、`app/agent/tools_v2.py` 和 `app/agent/controller_v2.py`；D5 prompt/service/trace lifecycle 位于 `app/agent/generation_v2.py`、`app/agent/runner_v2.py`、`app/main.py` 和 `app/runtime/resources.py`。当前可以准确表述为“默认 V2 数据流已有确定性 admission，并在模型输入、public trace 和 secure service composition 建立 defense in depth”；仍不能表述为“防住所有间接注入”，因为 D6 恶意/良性 OFF/ON 评估尚未运行。下一授权门是 `批准D5，执行D6安全评测与门禁`。
