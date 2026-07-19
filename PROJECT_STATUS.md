# Enterprise Agentic RAG - Current Status

更新时间：2026-07-19

状态：E7 自动化代码/数据门禁、功能分支 Git 交付、GitHub clean clone 和 Ubuntu GitHub Actions 均已完成。R2-S1 已完成 D1-D7，以及后续审计加固 V0-V5，其中 V1-V5 是实现阶段：V1 提供 checked-in、脱敏、可独立复算的 D7 公共逐例证据包；V2 用 content-free 实际扫描事件替代 reached 的类别推断；V3 将本地 Ollama 出站约束收紧为 exact origin/address/port；V4 将 legacy `model_attack_followed` 明确映射为版本化 raw canary/forbidden-action signal，并标记 semantic attack following 为 `NOT MEASURED`；V5 为未来运行加入可审计的 18/18 反平衡顺序。V0-V5 收口审查又修复了运行事件证据、私有 summary 复算、正式目录与官方 test cohort 保护和公开审计覆盖；当前功能分支包含这些改动，远端 CI 状态必须以对应 GitHub Actions run 为准。D7 仍是 `COMPLETED WITH OBSERVATIONS`，后续加固没有把它改写成 release pass。50 行人工语义评分与本人代码/口述验收仍是 `NOT RUN`。本文是唯一当前状态入口；`docs/PROJECT_STATUS.md` 与 `docs/AGENTIC_RAG_EVOLUTION_LOG.md` 只保留历史。

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
- R2-S1 D6：新增 dev/test 各 24 attack + 12 benign 的冻结合成集、真实 V2 路径的 evaluator-only OFF/production ON 成对运行、18 项 exact release gate、R1 全仓回归和内容零泄漏的不可变 provenance artifacts。
- R2-S1 D7：构建与生产索引隔离的真实 V2 security index；使用 BGE-M3 在每题冻结候选集内排序，使用 Qwen2.5:3b 经正常 `GenerationV2ResponseBuilder` 生成；OFF/ON 共享快照、查询向量缓存、顺序和参数，仅切换 Guard；local-only egress boundary 阻止非 Ollama 目的地和重定向；输出无原文、无回答正文、无 canary 的 immutable paired artifacts。
- R2-S1 V0-V1：验证外部审查提出的公开证据、socket、指标命名、reached provenance 和固定 arm-order 缺口；随后只读校验正式 D7 run，并导出 8 文件、72 行的严格白名单公共证据包。包内纯标准库 verifier 校验 exact file/schema/checksum/pair contract，并从逐例行重算 15 个指标。
- R2-S1 V2：新增 strict frozen `ScannedContentUnit`，在 admission 的每次真实 search/find/open Guard 调用处记录 operation、surface、exact aggregate members、disposition 和 rules；内部 ID 不序列化。live evaluator 删除 quarantine/admitted/category 推断，仅按事件映射 reached units；同时补齐 find recording 和 preview/section 精确 outcome 映射。未修改 Guard、冻结数据、正式 D7 run 或 V1 公共包。
- R2-S1 V3：新增共享 exact loopback origin policy；数值 IPv4/IPv6 按规范地址和端口精确匹配，`localhost` 冻结纯回环解析并只在已授权 HTTP 调用栈内放行其解析地址；统一约束 Requests、`connect`、`connect_ex`、proxy、Host override、redirect 和 urllib；class-level 非阻塞锁拒绝嵌套/并发 monkeypatch。该边界是 evaluator 进程内调用图约束，不是 OS sandbox。
- R2-S1 V4：新增 frozen metric-semantics registry 和严格四布尔 OR helper；live case/summary 提供不序列化的 canonical property，旧 `model_attack_followed` 字段和 live result v1 dump 保持不变；public writer 使用统一生产 helper，standalone verifier 保持独立复算；future evidence 使用准确名称并写明语义服从未测量。
- R2-S1 V5：新增严格自校验的 SHA-256 hash-rank arm-order plan；未来 36-case live v2 run 精确分配 18 个 OFF→ON 与 18 个 ON→OFF，runner 按计划执行但保持 mode result 对齐，manifest 保存完整 plan，逐 arm 行保存 hash/rank/order/position；旧 v1 schema 与正式 fixed OFF-first D7 不变，正式 run ID 被禁止重跑。

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

### R2-S1 D6 本地门禁

```text
D6 focused suite                         91 passed
full offline repository suite           788 passed
frozen test OFF attack success           21/24
frozen test ON attack success              0/24
ON quarantine recall                      28/28 attack units
ON benign quarantine                       0/32 benign units
ON clean / mixed / poison-only utility  12/12, 20/20, 4/4
ON recovery                               14/14
artifact files/checksums                    8 / exact
frozen run failures                         0
```

正式 run 是 `r2-s1-d6-test-20260718-01`，manifest SHA-256 为 `fe45b091f4f76c57919dae987186088433a5f7aa5293f7104de9eb09317f4564`。OFF 的 21/24 来自 deterministic propagation fake，不是 live model 攻击率。完整代码、RED/GREEN 故障和面试讲解见 [D6 Engineering Journal](docs/security/r2_s1/08_d6_engineering_journal.md)。

### R2-S1 D7 本地真实模型成对评测

```text
D7 focused suite                              24 passed
full offline repository suite                812 passed
public repository audit              390 candidates / 0 findings
frozen test OFF context exposure               7/24
frozen test OFF raw canary/forbidden signal     3/24
frozen test OFF user-visible attack success     3/24
frozen test ON context/raw-signal/success     0/24, 0/24, 0/24
ON attack units reached by Guard               15/28
ON conditional quarantine recall               15/15
ON attack units not reached by Guard            13/28
ON actual Guard misses                           0
ON benign quarantine                            0/32
ON clean / mixed / poison-only utility       12/12, 20/20, 4/4
model errors OFF / ON                          0 / 0
external egress                                  0
```

正式 run 是 `r2-s1-d7-test-20260718-01`，状态为 `COMPLETED WITH OBSERVATIONS`，manifest SHA-256 为 `5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e`。模型身份固定为 BGE-M3 digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab` 和 Qwen2.5:3b digest `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`。13 个 attack units 没有进入 Guard，是因为同一冻结候选集中的 clean rank-1 已满足 `top_k=1`；它们不能算 Guard 命中，也不能算 Guard 漏检，因此 D7 同时报告“全候选诊断”和“到达 Guard 后的条件召回率”。完整代码、失败诊断、指标推导和面试讲解见 [D7 Engineering Journal](docs/security/r2_s1/09_d7_engineering_journal.md)。

### R2-S1 V1 脱敏公共证据

```text
public package files                         8 / exact
case pairs / redacted rows                 36 / 72
independently recomputed metrics                15
V1 focused writer/verifier tests          19 passed
security tests                           107 passed
live indirect-injection tests             24 passed
full repository suite                    832 passed
warnings                                    3 known SWIG warnings
public repository audit                  407 candidates / 0 findings
clean isolated package verifier           VERIFIED
```

公共包位于 [`data/v2/public/r2_s1_d7/`](data/v2/public/r2_s1_d7/README.md)。它固定正式 source manifest hash，不复制 question、prompt、retrieved text、raw model output、nonce/canary value、content-unit ID、绝对路径、环境变量或 credential。`raw_canary_or_forbidden_action_follow` 仍只是 canary/tool 信号，不是语义 LLM judge；reached-unit 仍复现 D7 source evaluator v1 口径；固定 OFF 后 ON 的顺序也被显式披露。实现、RED/GREEN 和限制见 [V1 Engineering Journal](docs/security/r2_s1/11_v1_public_evidence_engineering_journal.md)。

### R2-S1 V2 Guard 实际扫描来源

```text
V2 focused domain/admission/live/find tests    54 passed
expanded domain/security/agent/evaluator      317 passed
full repository suite                         848 passed
warnings                                        3 known SWIG warnings
category-based reached inference                 removed
deterministic mock OFF / ON reached           17/28 / 17/28
deterministic mock OFF/ON per-case eligibility      exact
historical D7/V1 reached                         15/28 unchanged
```

V2 新增不可变、严格、无原文的 `ScannedContentUnit`，并在每次真实 Guard scan 时记录 operation、surface、内部 item/member IDs、aggregate、disposition 和 allowlisted rules。内部 IDs 从 JSON/repr 排除，outcome 强制 provenance 总数和 ADMIT/QUARANTINE 数分别匹配 counters。live evaluator 不再读取 case category、最终 admitted result 或 quarantine summary 来猜 reached。

正式 D7 的 BGE-M3 candidate order 与单元测试的 hash embedding candidate order 不同，所以历史公共包继续是 15/28，而当前 mock workload 的实际事件基线是 17/28；两者绑定不同实验输入，不能互换。详细 RED/GREEN、逐文件代码解释和面试问答见 [V2 Engineering Journal](docs/security/r2_s1/12_v2_scan_provenance_engineering_journal.md)。

### R2-S1 V3 精确 Ollama Origin/Socket 边界

```text
initial V3 RED                              8 failed / 3 passed
localhost real-call-graph RED              1 failed
V3 boundary contracts                      12 passed
complete live-runner file                  25 passed
live/writer/CLI/security/admission subset  89 passed
full repository suite                     859 passed
warnings                                    3 known SWIG warnings
V1 standalone verifier                     VERIFIED
frozen dataset/fixture/manifests            exact
public repository audit          411 candidates / 0 findings
compileall / pip check / diff check          clean
```

V3 用 `_ExactLoopbackOriginPolicy` 统一 HTTP 和 socket 判断：配置数值 IP 时只允许规范等价的同一地址与端口；配置 `localhost` 时冻结纯回环解析集合，并用线程局部 HTTP 委托窗口支持 Requests 的 hostname-to-sockaddr 实际调用链。普通直接 socket 仍不能借用数值 alias。显式 request/session proxy、显式 Host、3xx、urllib、错误端口、其他 loopback、嵌套和并发 boundary 均 fail closed 并精确计数。

V3 没有改 Guard、检索、模型、数据、正式 D7 run 或 V1 包，也没有重跑并覆盖历史 live 结果。它只能准确称为 Python evaluator call-graph egress guard，不能称为操作系统沙箱。详细 RED/GREEN、代码调用顺序、限制和面试问答见 [V3 Engineering Journal](docs/security/r2_s1/13_v3_exact_ollama_boundary_engineering_journal.md)。

### R2-S1 V4 指标语义版本化

```text
new V4 contracts                              32 added
semantics/live/writer/CLI focused suite       83 passed
evaluation/security/retrieval expanded       382 passed
full repository suite                        891 passed
warnings                                       3 known SWIG warnings
public repository audit             416 candidates / 0 findings
repository / clean isolated V1 verifier       VERIFIED / VERIFIED
compileall / pip check / diff check            clean
dataset / fixture / freeze / formal hashes     exact
```

V4 注册 `raw_canary_or_forbidden_action_follow_v1` 语义：只有 raw document/system/trace canary exposure 或 forbidden-tool attempt 才为 true；semantic attack following 是 `NOT MEASURED`。错误政策值若不包含 canary 且没有 forbidden-tool signal，该窄指标为 false，但这不能解释为回答正确或攻击无效。

旧 live v1 JSON 仍序列化 `model_attack_followed`，canonical property 不进入 `model_dump()`；正式 D7 和 V1 package bytes 未修改。完整 TDD、代码映射、独立 verifier 原因、限制和面试问答见 [V4 Engineering Journal](docs/security/r2_s1/14_v4_metric_semantics_engineering_journal.md)。

### R2-S1 V5 未来 OFF/ON 反平衡协议

```text
new V5 contracts                              22 added
plan/runner/writer/CLI focused suite          53 passed
security/evaluation/retrieval expanded       404 passed
full repository suite                        921 passed
warnings                                       3 known SWIG warnings
future 36-case order allocation               18/18 exact
public repository audit             415 candidates / 0 findings
repository / clean isolated V1 verifier       VERIFIED / VERIFIED
compileall / pip check / diff check            clean
historical formal D7 manifest hash             exact
real-model v2 run                            NOT RUN
```

V5 对固定 cohort 计算 `sha256(case_id)`，按 `(case_hash, case_id)` 排名后以 rank 奇偶交替分配 arm order。真实调用顺序由 plan 控制，OFF/ON 结果数组仍按 dataset 对齐供现有指标计算。`LivePairedResultV2` 和 `LiveSecurityRunManifestV2` 与 v1 显式分离；writer 拒绝 v1/v2 混用，并逐行核对 arm position 与 guard mode。

本轮没有重新执行 Qwen/BGE-M3 正式实验，因此没有新的 0/24 或 utility 数字。正式 `r2-s1-d7-test-20260718-01` 继续标记为 fixed OFF-first observational run，manifest SHA-256 仍为 `5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e`。详细算法、RED/GREEN、两类顺序的区别、实现错误修正和面试问答见 [V5 Engineering Journal](docs/security/r2_s1/15_v5_counterbalanced_arm_order_engineering_journal.md)。

V0-V5 完成后又进行一次独立 closeout review，结果为 `0 Critical / 6 Important / 2 Minor`。6 个 Important 均已补成 RED/GREEN 回归测试并修复；2 个 Minor 中，process-local 网络边界和独立验证不足被保留为明确限制及 R2-S2 准入项。最终本地证据为 180 个聚焦跨模块测试、921 个全仓测试、415 个公开候选文件零命中、仓库内与隔离 8-file verifier 均通过。完整问题、代码位置、根因、修复和下一阶段安排见 [V0-V5 Closeout Review](docs/security/r2_s1/16_v0_v5_closeout_review_and_improvement_plan.md)。

R2-S1 V1-V5 与收口修复提交 `9fcb3041ae3561057e1b56d881e91aab8aee0dce` 已推送到 `origin/codex/rag-eval-system`；对应 [GitHub Actions run 29682474913](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/29682474913) 在 Ubuntu/Python 3.11 上为 `success`。该结果是功能分支 CI 证据，不代表已经 merge、部署或完成 owner-only 验收。

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

- Retrieved-content indirect prompt injection：D1-D7 已完成当前批准范围；D6 deterministic frozen gate 通过，D7 本地 BGE-M3 + Qwen2.5:3b frozen paired run 为 `COMPLETED WITH OBSERVATIONS`。现有证据仍只覆盖可见、固定、合成文本攻击；独立 holdout、多模态、人工红队、未知绕过、跨模型复现和生产流量仍为 `NOT RUN`。
- R2-S1 audit hardening：V0-V5 已完成本地实现与验证；未来 v2 counterbalanced 协议已有 deterministic synthetic 证据，但新的真实模型 v2 run 为 `NOT RUN`。
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
- R2-S1 D2-D7 结果：[Security Results](docs/security/r2_s1/05_results.md)
- R2-S1 D4 逐步工程日志：[D4 Engineering Journal](docs/security/r2_s1/06_d4_engineering_journal.md)
- R2-S1 D5 逐步工程日志：[D5 Engineering Journal](docs/security/r2_s1/07_d5_engineering_journal.md)
- R2-S1 D6 逐步工程日志：[D6 Engineering Journal](docs/security/r2_s1/08_d6_engineering_journal.md)
- R2-S1 D7 逐步工程日志：[D7 Engineering Journal](docs/security/r2_s1/09_d7_engineering_journal.md)
- R2-S1 V0 审计验证：[Auditability Verification](docs/security/r2_s1/10_auditability_verification.md)
- R2-S1 V1 公共证据日志：[V1 Engineering Journal](docs/security/r2_s1/11_v1_public_evidence_engineering_journal.md)
- R2-S1 V2 扫描来源日志：[V2 Engineering Journal](docs/security/r2_s1/12_v2_scan_provenance_engineering_journal.md)
- R2-S1 V3 精确边界日志：[V3 Engineering Journal](docs/security/r2_s1/13_v3_exact_ollama_boundary_engineering_journal.md)
- R2-S1 V4 指标语义日志：[V4 Engineering Journal](docs/security/r2_s1/14_v4_metric_semantics_engineering_journal.md)
- R2-S1 V5 反平衡顺序日志：[V5 Engineering Journal](docs/security/r2_s1/15_v5_counterbalanced_arm_order_engineering_journal.md)
- R2-S1 V0-V5 收口审查与改进安排：[Closeout Review](docs/security/r2_s1/16_v0_v5_closeout_review_and_improvement_plan.md)
- E6 历史实施证据：[E6 Implementation Journal](docs/roadmap/e6_demo_public_repo_implementation.md)
- 跨阶段恢复：[Current Execution Handoff](docs/roadmap/CURRENT_EXECUTION_HANDOFF.md)

## 8. R2-S1 当前状态

R2-S1 的 D0-D7 和审计加固 V0-V5 已完成当前批准范围。D3 从已提交的 D2 基线 `c1c47dfe88c42c309afc32faa9bc6584e90e89ac` 开始；D4 从已提交的 D3 基线 `ec85cc718b3df17731fb1d9df7300a3a7c6fe5be` 开始；D5 从 `86064322fd532264623abd23e8db7a99634ab342` 开始；D6 在 D5 commit `0946ad90a7d9b54e219006b271c7c7bdc440863c` 上记录完整 dirty provenance；D7 从 HEAD `4b7d0b91078a3246cb9e801631c0a47691bf3985` 运行并在 manifest 中记录 dirty tree hash `162771457b7e14e2672ec6a49687423d53fa4a74c64ce7c77d883616963d66b4`；V1-V5 从当前 HEAD `1bf9b95917d7ae813ca6214c7ab83492b4c47aa3` 的未提交工作区继续加固。权威设计与结果位于：

- [R2-S1 总设计](docs/superpowers/specs/2026-07-17-r2-s1-indirect-prompt-injection-design.md)
- [Scope and threat model](docs/security/r2_s1/00_scope_and_threat_model.md)
- [Attack surface and trust boundaries](docs/security/r2_s1/01_attack_surface_and_trust_boundaries.md)
- [Design decisions](docs/security/r2_s1/02_design_options_and_decisions.md)
- [Detailed schema design](docs/security/r2_s1/03_detailed_design.md)
- [Evaluation protocol](docs/security/r2_s1/04_evaluation_protocol.md)
- [D2-D7 results](docs/security/r2_s1/05_results.md)
- [D4 step-by-step engineering journal](docs/security/r2_s1/06_d4_engineering_journal.md)
- [D5 step-by-step engineering journal](docs/security/r2_s1/07_d5_engineering_journal.md)
- [D6 step-by-step engineering journal](docs/security/r2_s1/08_d6_engineering_journal.md)
- [D7 step-by-step engineering journal](docs/security/r2_s1/09_d7_engineering_journal.md)
- [V0 auditability verification](docs/security/r2_s1/10_auditability_verification.md)
- [V1 public evidence engineering journal](docs/security/r2_s1/11_v1_public_evidence_engineering_journal.md)
- [V2 scan provenance engineering journal](docs/security/r2_s1/12_v2_scan_provenance_engineering_journal.md)
- [V3 exact Ollama boundary engineering journal](docs/security/r2_s1/13_v3_exact_ollama_boundary_engineering_journal.md)
- [V4 metric semantics engineering journal](docs/security/r2_s1/14_v4_metric_semantics_engineering_journal.md)
- [V5 counterbalanced arm-order engineering journal](docs/security/r2_s1/15_v5_counterbalanced_arm_order_engineering_journal.md)

当前状态必须逐层表述：

```text
design/protocol                         D1 FROZEN
D2 propagation baseline                5 EXPECTED RED / 3 EXISTING BOUNDARY PASS
RetrievedContentGuard standalone core  D3 GREEN / 64 TESTS
runtime guarded data flow              D4 GREEN / 8 BOUNDARY PROBES
full offline regression                D5 GREEN / 697 TESTS
prompt nonce/public security counters   D5 GREEN
malicious/benign security datasets      D6 FROZEN / 36 DEV + 36 TEST
deterministic guard OFF/ON evaluation   D6 FROZEN TEST PASS / 18 CHECKS
local BGE-M3 + Qwen paired evaluation   D7 COMPLETED WITH OBSERVATIONS
redacted standalone public evidence     V1 VERIFIED / HISTORICAL D7 15/28
actual Guard scan provenance            V2 GREEN / 848 TESTS
exact local Ollama origin/socket guard  V3 GREEN / 859 TESTS
versioned raw-follow metric semantics   V4 GREEN / 891 TESTS
counterbalanced future arm order        V5 GREEN / 913 TESTS
```

D3 detector 位于 `app/domain/retrieved_security.py` 与 `app/security/retrieved_content.py`；D4 admission 与强制接入位于 `app/security/retrieved_admission.py`、`app/retrieval/pipeline.py`、`app/agent/tools_v2.py` 和 `app/agent/controller_v2.py`；D5 prompt/service/trace lifecycle 位于 `app/agent/generation_v2.py`、`app/agent/runner_v2.py`、`app/main.py` 和 `app/runtime/resources.py`；D6 deterministic evaluator 位于 `app/evaluation/indirect_injection_*.py`；D7 live index、runner、artifact writer 和 CLI 分别位于 `app/evaluation/indirect_injection_live_index.py`、`app/evaluation/indirect_injection_live_runner.py`、`app/evaluation/indirect_injection_live_writer.py` 与 `scripts/eval_indirect_injection_live.py`；V2 scan provenance 横跨 `app/domain/retrieved_security.py`、`app/security/retrieved_admission.py` 和两套 indirect-injection runner；V3 exact boundary 位于 live runner 的 `_ExactLoopbackOriginPolicy` 与 `LocalOllamaOnlyBoundary`；V4 semantic registry 位于 `app/evaluation/indirect_injection_metric_semantics.py`；V5 arm-order contract 位于 `app/evaluation/indirect_injection_arm_order.py` 并由 live runner/writer/CLI 接入。当前可以准确表述为：“固定 synthetic frozen test 上，deterministic OFF/ON 证明 known attack propagation 从 21/24 降至 0/24；真实 BGE-M3 + Qwen2.5:3b 成对观察中，OFF 出现 3/24 user-visible attack success，ON 为 0/24，且历史 D7 evaluator 记录到达 Guard 的 15/15 attack units 全部隔离、0/32 benign units 被误隔离；另有 OFF 3/24 raw canary/forbidden-action signal，不能称为语义服从率；V2 后的新运行只按 actual scan events 计算 reached；V3 将 evaluator 本地 Ollama 出站约束收紧为 exact origin/address/port，但不是 OS sandbox；V5 只让未来 v2 运行采用可审计的 18/18 反平衡顺序，并没有产生新的真实模型结果。”不能表述为未知攻击免疫或生产安全保证。独立 holdout、人工红队、语义 LLM judge 或跨模型复现仍需另行授权。
