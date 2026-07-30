# Known Limitations

## Gate E2 typed planning remains calibration-only

The best Gate E2 iteration (`v2.2`) improved typed-plan coverage to 81.67%
and strict execution accuracy to 26.67% on the disclosed 60-case calibration
cohort, but the frozen B0 baseline reached 51.67% strict accuracy on the same
cohort. The typed path also converted 20 B0-correct cases to wrong outcomes
and had an 18.33% protocol-error rate. It therefore failed the frozen adoption
contract and remains disabled as a replacement for B0.

Internal validation, the frozen test split, and the B2 multi-program comparison
were deliberately not run after calibration rejection. Gate E2 is evidence
about a failed development calibration, not a held-out improvement,
production-readiness claim, or permission to quote v2.2 as the deployed
answering path. The next measured bottleneck is retrieval-side numeric
candidate completeness, table scale/unit propagation, percentage
normalization, and tightly controlled host constants.

## R2-S5 identity status correction

Rows below that describe caller-supplied `UserContext` or absent token
verification are historical and superseded. The repository now verifies
short-lived RS256 JWTs against a pinned local JWKS snapshot, derives Agent
identity server-side, separates user/operator credentials, and protects
observability with `rag.operator`.

The remaining limitation is narrower but important: this is a local,
reproducible identity simulator, not enterprise IAM. It has no SSO, federation,
remote JWKS refresh, revocation service, MFA, SCIM, HR lifecycle, policy-admin
workflow, durable authorization audit, HSM/KMS custody, or production incident
response. The API loads key material at process construction, so rotation is an
explicit stage/restart/activate/overlap/retire/restart operation. Production admission requires a real
issuer and independent integration, tenant-isolation, revocation, operations,
and penetration evidence.

The local activation probe is plain HTTP to an exact numeric loopback origin.
It proves that the responding local API snapshot accepts the pending key under
the trusted-host demo assumption; it does not authenticate the server against
another malicious process on the same host. Manifest and journal SHA-256
bindings detect non-coordinated corruption, not a process that already has the
same account's identity-directory write authority.

最后更新：2026-07-29

本文使用三个状态：`FAILED` 表示已运行且未通过；`NOT RUN` 表示没有满足协议的 fixture/依赖或实验；“未实现”表示代码能力不存在。`NOT RUN` 不能写成通过。

## 1. 当前限制表

| Area | Current state | Consequence | Admission condition |
|---|---|---|---|
| Identity legacy baseline | R2-S5 之前由调用方声明 `UserContext`；当前已由本地 JWT/JWKS 边界取代 | 仅用于解释为什么 R2-S5 必须先修 authority source，不能描述当前路由 | 当前限制见下方 Authentication/authorization 行 |
| Data realism | 历史 72/600 和当前 240/2,000 文档 profiles 全部 synthetic；当前事实宽度为 20 policies / 104 facts | 指标证明工程 contract，不代表真实企业分布或生产泛化 | 法务批准的去标识 pilot corpus、数据治理记录和独立 held-out evaluation |
| Live quality | 历史 full Agent canonical live dev 为 23/24；新增 expanded retrieval-only dev/test 为 48/48、56/56 | retrieval success 不等于回答语义、人类可用性或生产端到端 100% | 保留历史 artifact；对 expanded 执行独立 answer/Agent/human review，不根据 frozen test 反复调参 |
| Citation grounding | Host 只输出通过 visible-source、最低词汇支持、阿拉伯数字、日期/状态和常见否定一致性检查的 claim；全部失败时回退到可见证据抽取式 partial | 这是确定性 fail-closed gate，可能拒绝正确同义改写，也不能证明完整 semantic entailment、事实正确性或 hallucination immunity | 用真实双人评审测量误拒绝与漏检；在独立数据上校准后才考虑更强语义判定 |
| Indirect document injection | D1-D7, V1-V5, S2-1, R2-S3, and R2-S4 Task 8 are complete with observations; R2-S4 public package `data/v2/public/r2_s4_cross_model` is `VERIFIED / 8 FILES`; decision `CONSISTENT_OBSERVATION` on the same visible synthetic dev cohort; `release_pass=false` | The result supports only this narrow comparison: 12 decision safety/utility observations matched for frozen Qwen2.5/Qwen3 on visible synthetic dev data; 3 operational counts matched; 2 latency metrics differed. It is not production safety evidence and not cross-model generalization. Public proof scope intentionally omits private input/nonce/candidate-order hashes and aligns only by ordinal/public-safe fields | Independent holdout, semantic judge calibration, human double review, production traffic, real IdP, and deployment remain `NOT RUN`; any broader claim requires those gates |
| Reranker | FinanceBench dev 已运行 guarded qwen3/qwen2.5 listwise reranker；dev-selected qwen3 cascade 为 Page Hit@5 `53.06%`、Macro Page Recall@5 `46.94%`、`13/49` reranks、mean/p95 `2.46s/5.95s` | 这是页面定位 dev 结果，不是答案准确率；阈值在同一 dev 上选择，旧 test 已被分析，不能用于 v2 泛化声明；qwen3 全量 p95 `45.12s`，qwen2.5 质量低于 dense baseline | 冻结当前配置、模型 digest 和门禁，在新的独立 holdout 上同时验证 page、answer、citation、调用率和 latency，再决定是否接入默认在线路由 |
| FinQA numerical quality | 固定 100 题 test 样本上，oracle strict `52%` / grounded strict `45%`；hybrid K=10 strict `44%` / grounded strict `40%` / evidence recall `93.5%`；v1 schema incident 在抽样和模型调用前发生并已公开 | 结果证明 Calculator 协议比 dev direct/typed-step 基线稳定，但也显示 20 题 dev pilot 明显乐观；这不是完整 FinQA test、SOTA、跨模型或生产财务可靠性 | 保留 v2 frozen protocol 和内容无关证据；后续只能建立新的独立协议，扩展模型/域/样本并增加双人语义审核，不能重调本次 test |
| FinQA failure attribution | 新 100 题 dev 诊断将失败分成 retrieval、protocol、unsupported operation、operand、operation-plan 与 composition/scale signal；Oracle/Hybrid strict 为 `63%/59%` | operand/operation 依赖 gold program 的机械比较，等价改写可能产生假阳性；dev `answer` 与 `exe_ans` 也有可测量的不一致；它不是人工语义根因判断，也不是新 holdout | 保留逐题私有 artifact 与公开聚合 hash；下一步在 dev 上成对评估有界 plan-review，并同时量化退化、成本与延迟 |
| FinQA selective review | 旧 100 题 tuning 与 50 题 validation 证明方向后，项目在新的零重叠 100 题 dev cohort 上真实执行 selective pipeline：strict `53% -> 55%`、grounded `38% -> 40%`，3 修正 / 1 退化，触发率 `63%`，增量 generation/Calculator 调用减少 `32.00%/30.52%`；observed selective 总时间比同批隔离 shadow-full arm 低 `23.83%` | exact McNemar `p=0.625` 未达 `0.05`，1 个 correct-to-wrong 违反零退化门槛，只捕获 full strategy 4 个修正中的 3 个；30B 仅为 `num_gpu=5` 的部分 CUDA offload，观测为 `89% CPU / 11% GPU`，不能外推 full-GPU 或生产延迟 | 默认路径保持关闭；只能在既有已揭示开发 cohort 上研发 trigger-v2/temporal consistency，再冻结新的独立 cohort 或另一公开金融 QA 数据集确认；不得回到已揭示 test 调参 |
| Human review | `NOT RUN`；50 行、8 个人工判断列保持空白 | 自动 claim/citation/required-fact checks 不能替代语义和可用性评分 | 本人按冻结 rubric 完成 review；若用于正式质量结论，再增加第二 reviewer、分歧仲裁和 agreement 记录 |
| Authentication/authorization | 本地 RS256 JWT/JWKS、server-derived Principal、operator route role 和文档 ACL 已实现；身份源仍是本地模拟，不是真实 IdP | Streamlit/API 只允许本机演示；不能声称已接 SSO、revocation、SCIM 或企业 policy admin | 接真实 OIDC discovery/JWKS cache、HTTPS、secret manager、tenant-scoped operator policy 和 change audit |
| Index updates | immutable rebuild + activate；没有 incremental upsert/delete | 文档变化需要新 run，不能承诺低延迟同步 | 定义 document tombstone/version contract、idempotency、rollback 和 consistency tests |
| Observability | bounded in-memory traces/metrics | 重启丢失，不能跨进程关联或长期查询 | OpenTelemetry SDK/collector、durable backend、retention/redaction/access policy |
| Deployment | R2-S9 已完成可复现的单主机 Linux image/readiness/rollback/SBOM contract；真实 staging 和 production 仍为 `NOT RUN` | 没有证明生产流量、高可用、外部 registry signing、完整 network policy 或 rolling deploy | 在隔离 staging 上执行真实镜像、secret、负载、故障与回滚验收，再由人工 owner 批准 |
| Supply chain | direct requirements、Python/pip 和 Actions revision 已固定；transitive wheel hashes 与 SBOM 未固定 | 同版本解析器减少漂移，但不能证明安装闭包逐字节相同或依赖来源完整 | 生成带 hash 的跨平台 lock、保存 SBOM/provenance，并在隔离构建器验证 |
| Remote CI | 历史 feature-branch commits `9607e55` 的 [Ubuntu run](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/29553278709) 与 `9fcb304` 的 [Ubuntu run](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/29682474913) 已通过；当前 workflow 已准备 Ubuntu/Windows matrix，但精确 R2-S5 SHA 尚未运行 | 历史结果不覆盖当前 candidate；workflow 配置本身也不等于远端两个 job 已通过，更不证明 branch protection、merge、deployment 或 production runtime | 推送当前精确 SHA，取得两个 matrix job 的成功 URL，再设置 required checks 并补镜像/SBOM/staging gates |
| Scale | demo index 64 chunks；benchmark 不是生产 load | FAISS/in-memory BM25 结论不能外推到 5,000+ 活跃文档与并发租户 | 规模/并发/更新率达到预设阈值后重新 profile，再决定 vector DB/caching |
| Model robustness | direct unsafe rule-first probe 只有 4 条 | 编码、多语言、间接和新型绕过仍可能通过 | 扩展 adversarial taxonomy、人工红队、版本化 model/prompt regression |
| Feedback | 保存 actor/question/answer 的 deterministic keyed HMAC、request IDs、helpful 和 binding version；服务端回执绑定原回答；同 actor/target/content 幂等更新 | 无法从数据库恢复正文，但持有数据库的人仍能观察同一 key 下 digest 相等关系与重复模式；尚无分析平台、保留期策略或受控 failure sampling | 若 equality linkability 不可接受，改用受约束的随机化记录标识/独立分析域；经隐私评审后再增加采样、retention/access policy，不默认保存全文 |
| Availability | 单进程、单 active index、单本地 Ollama | 没有 HA、队列、backpressure 或多副本一致性 | 明确 SLO/RTO/RPO 后再设计 replicas、queue 和 failover |
| Agent scope | 单 controller、固定工具 allowlist、无长期记忆/checkpoint；默认逐 aspect 选择 `search`，completeness 可 `open`，不会主动 `find`，无自动 query rewrite/retry | 不能称通用 autonomous/multi-Agent platform，也不能声称当前三个工具均由策略自主规划 | 只有真实失败案例和冻结评测证明需要新动作时才扩展策略 |

## 2. 指标解释限制

- `28/28` deterministic 表示当前合成 test 上的系统 contract 全部通过；它不调用真实 chat/embedding 模型。
- `23/24` live 是一个开发 split 和一次指定本机环境运行；不能当作 production accuracy。
- retrieval 的 `precision@5` 分母固定为 5。单一 gold 文档题即使首位正确，后续位置会自然降低 precision；需要同时看 recall、MRR、NDCG、authority 和 invalid extras。
- workflow ablation 的 outcome accuracy 不逐句评价生成文本；response layer 另测 required facts、citation 和 unsupported claims。
- FinQA 的 `52%` oracle strict 与 `44%` hybrid strict 只适用于固定 100 题样本和冻结本地模型；oracle 是 gold evidence 下的数值计划观察值，hybrid 才包含检索损失，两者都没有人工语义审核。
- load p95 来自 31 次本地请求，样本小且硬件/模型常驻状态敏感；它是演示 profile，不是 SLO。
- public snapshot 是原始 artifacts 的脱敏摘要。它带 hash provenance，但不替代 ignored source run 的逐题复核。
- R2-S3 的 `28/28` depth-2/4 total reach 是 deterministic counterfactual coverage，不是 live production reach；额外 `29/33` scans 与 `3845/4200` input characters 也不是 wall-clock latency。

## 3. 安全声明限制

已经验证的是：固定 direct unsafe prompts 在 query analysis 后、retrieval 前 source-free 拒绝；ACL 测试不暴露 forbidden docs；错误/trace 不回显已知敏感字段；默认 V2 `search/find/open` 在 Controller 前执行确定性 admission，raw execution 被拒绝，已隔离内容不进入 generation/source/context budget。

尚未证明的是：任意 prompt injection 都会失败、真实 Qwen 在未知攻击或其他模型上的成功率、system prompt 永不泄露、浏览器声明身份可信、或该服务适合公网/多租户生产。legacy `/chat`、`/agent/chat` 和 `/ingest` 已从可部署 app 与生产 factory 移除，不属于当前 HTTP 攻击面。D6 fake generator 只证明确定性传播；D7 与 S2-1 都只观察到固定本地 BGE-M3/Qwen 配置下的可见 synthetic 数据。S2-1 的 `15/15` 是“已到达 Guard 后”的条件 detector 指标，不覆盖 13 个 unreached attack units；R2-S3 虽观察到相关 case downstream exposure `0/13`，但不能把 diagnostic depth-2 total coverage 改写成 live end-to-end `28/28`，也不能把 `NO_CURRENT_BYPASS_OBSERVED` 写成 release pass。

完整威胁与控制映射见 [Security Threat Model](security_threat_model.md)。

## 4. 公开展示边界

- README 与 UI 必须显示 live `23/24`，不能四舍五入为 100%。
- indirect document injection 必须分层显示：D4 guarded V2 data flow、D5 prompt/public observability、D6 deterministic frozen OFF/ON gate 已完成；D7 fixed-order 与 S2-1 counterbalanced local BGE-M3/Qwen paired runs 均为 `COMPLETED WITH OBSERVATIONS`；R2-S3 measurement-only ablation 为 `COMPLETE`，但 source live run 和 production Guard/retrieval/Agent 未改，counterfactual coverage 仅诊断。R2-S4 cross-model dev observation is COMPLETE WITH OBSERVATIONS, but independent package, independent holdout, semantic judge calibration, human double review, production traffic, real IdP, deployment, human red team, and optional reranker remain `NOT RUN`。
- `526 passed` 是 E5 入口、`569 passed` 是 E6 收口、`574 passed` 是 E7 自动化本地门禁；它们是不同 commit 候选的历史计数，不能相加。
- 远端 CI 声明必须同时给出 run URL 和 commit；当前可核验的 `9607e55` 与 `9fcb304` 均为历史 feature-branch 证据，不覆盖当前 R2-S5 candidate exact HEAD。
- E7 已逐条处理 claims matrix；只能使用 `approved` 原句或 `narrowed` 后的措辞，不能删掉 synthetic、deterministic/local、样本数和 `NOT RUN` 边界。

下一阶段准入项与优先级见 [Industrialization Backlog](industrialization_backlog.md)。

## 5. R2-S1 current boundary

D1 froze the design; D3 built the model-free detector; D4 connected it to the default V2 path; D5 added prompt/trace/service defense in depth; D6 added the immutable deterministic paired gate. The D6 frozen synthetic result is OFF attack success `21/24` versus ON `0/24`, ON benign quarantine `0/32`, with `788 passed` full regression. D7 then observed one fixed-order local BGE-M3/Qwen pair. R2-S2 S2-1 repeated the visible dev experiment with a new run ID and exact 18/18 counterbalancing: OFF user-boundary signal `3/24` versus ON `0/24`, conditional quarantine `15/15`, all-labeled quarantine `15/28`, clean utility `12/12`, benign quarantine `0/32`, and zero model/system errors or blocked egress. S2-2 implements holdout admission and sealing, but no independent raw package or holdout score exists. None of these results establishes unseen-attack prevalence, immunity, cross-model generalization or production safety.

## 6. historical R2-S3 boundary at R2-S3 cutoff

R2-S3 deterministically replayed the unchanged S2-1 source admission path and
published content-free evidence from accepted v2 run
`r2-s3-dev-exposure-20260721-04`. The private and public manifests use explicit
v2 schemas and bind the replay implementation dependencies. Actual and replay
Guard reach agree at `15/28`;
conditional quarantine is `15/15`; all 13 unreached units are runtime rank 2;
and affected-case downstream exposure is observed `0/13`. Search coverage at
depths `1/2/4` is `6/26`, `22/26`, and `26/26`, but only as a measurement-only
counterfactual. No production Guard, retrieval, Agent, prompt, ranking, `top_k`,
or `candidate_k` change was made or admitted.

The decision `NO_CURRENT_BYPASS_OBSERVED` meant no R2-S3 cutoff dev evidence
justified a broader runtime prefilter. It was not a universal safety result,
release pass, or production deployment gate. Independent holdout evaluation and
semantic judge calibration remain `NOT RUN`; current R2-S4 Task 8 below
supersedes only the old cross-model-replication NOT RUN line.

## 7. R2-S3 frozen local trust boundary

R2-S3 verification and publication assume a trusted local operator, a clean
reviewed checkout, a stable filesystem during one verification/publication
call, and a trusted Python interpreter, import cache, dependencies, and runtime
memory. Hashes identify selected canonical source files on disk. They identify
source text, not loaded bytecode, a complete transitive implementation closure,
behavior, or producer identity.

Concurrent ABA replacement by a local writer and compromised runtime/import
state are outside the frozen threat model. Stronger guarantees require an
external immutable execution/attestation boundary.

## 8. R2-S4 current boundary

R2-S4 Task 8 published a real two-model local observation for the same visible
synthetic dev cohort. The run used code HEAD
`109e8b52d8d31ae3562420351451a69915652be3`, tree
`6b54e1f3c94b031a9438d21fd6e88a8c6d78faa8`, and plan SHA-256
`85175b88742d28b09431e1b1df35a27db5cd65fbd96fc33db0bcfd899efd4152`.
The matrix manifest is
`ec7b2fb6b8802b32d50933fc34b574d55c370dd88dbee4a88239d37ac51ff0b5`;
the eight-file public package manifest is
`0978131eaf1c0059a598648f3f67ea07b5144a110467728ada852bdbbfe61813`.

The decision is `CONSISTENT_OBSERVATION`: baseline Qwen2.5 and replication
Qwen3 produced 12 decision safety/utility observations matched on this visible
synthetic dev cohort; 3 operational counts matched; 2 latency metrics differed.
Both models' cross-model non-release diagnostics have `passed=true` and
`release_pass=false`. The older component deterministic threshold diagnostic
remains false because all-labeled quarantine is `15/28`, not `28/28`. Neither
field is a release pass, production safety evidence, or cross-model
generalization.

Key current numerators are OFF attack `3/24`, ON attack `0/24`, OFF context
exposure `7/24`, ON context exposure `0/24`, ON conditional quarantine `15/15`,
all-labeled quarantine `15/28`, ON benign quarantine `0/32`, clean `12/12`,
mixed `20/20`, and poison-only `4/4`. Thirteen labeled attack units did not
reach Guard, so the `15/28` all-labeled denominator remains a retrieval/tool
coverage limitation. Baseline p50/p95 latency was `1208.1238/1379.7665ms`;
replication p50/p95 latency was `1838.3202/2025.2085ms`.

These remain `NOT RUN`:

```text
independent holdout         NOT RUN
semantic judge calibration NOT RUN
human double review        NOT RUN
production traffic         NOT RUN
real IdP                   NOT RUN
deployment                 NOT RUN
```

R2-S4 is evaluation-operation industrialization, not production-service
readiness. Only admitted next implementation: R2-S5 Trusted Identity Boundary.
Rank 2: reproducible minimal Linux deploy/rollback. Rank 3: durable
privacy-bounded telemetry. These are not parallel approvals. No framework,
vector DB, Kubernetes, multi-Agent, or memory stack is admitted by this
evidence.

The R2-S4 controller lock is limited to cooperating evaluator processes sharing
the same normalized local Ollama origin. It prevents overlapping R2-S4/live
evaluators inside this codebase, but it does not stop non-cooperating external
Ollama clients, provide production scheduling, or make model aliases immutable.
The manual no-other-Ollama-client check remains required before any future run.
Operators must not delete, rotate, replace, redirect, or clean
`R2_S4_EVALUATION_LOCK_DIR` during a run. Non-cooperating post-yield lock pathname replacement remains outside the standard-library threat model.

## 9. R2-S8 quality-evidence boundary

R2-S8 G0-G4 tooling is implemented: immutable model/verdict-blinded,
reference-guided packets, strict
pseudonymous double review, disagreement/adjudication, human relevance and
answer metrics, recomputable evidence, and version-pinned LLM-judge
calibration. The tracked 12-case packet is a public-synthetic dev calibration
packet with blank labels.

The following remain `NOT RUN`:

```text
real two-person dev pilot       NOT RUN
independent 60-case holdout     NOT RUN
semantic judge calibration     NOT RUN
human double review            NOT RUN
production traffic             NOT RUN
```

Therefore the project still cannot claim human-verified factual accuracy,
independent retrieval relevance, calibrated LLM judging, or production quality.
The tooling is evidence infrastructure, not the missing evidence itself.
The current protocol exposes frozen expected response mode and reference
material to reviewers. It supports consistent criterion-based grading but is
not a verdict-blind study and may anchor refusal judgements. Reviewer HMACs use
one coordinator-held campaign pepper to detect duplicate normalized IDs, but
the operator must still verify that two actual people participated.

## 10. FinQA typed-program and layout boundary

Gate B implements deterministic FinQA numeric-candidate extraction from
structured JSON text and table cells. It preserves explicit row/column headers,
normalizes financial formats with `Decimal`, assigns non-operand roles to
period labels/page numbers/ordinals, and publishes a synthetic aggregate-only
manifest. This is mechanism evidence, not answer-quality evidence.

The current PDF parser preserves per-page text locators but does not perform
OCR, table detection, merged-cell reconstruction, multi-column reading-order
recovery, repeated-header removal, or cross-page table stitching. Therefore
the project cannot claim robust raw annual-report table extraction or
cross-page financial-table reasoning.

Gate C now implements a separate reference-only typed planner, deterministic
compatibility validator, and Decimal compiler. The old literal-expression
answerer remains the historical baseline. Gate C is deterministic mechanism
evidence only: no real model or new cohort was run, so it does not establish an
accuracy improvement.

The current intent extractor recognizes only explicit operation and year
patterns. Unknown text metric/entity metadata may cause fail-closed rejection.
The V1 unit system supports base units and ratios but not general compound-unit
algebra, and it cannot independently prove semantic `part_over_total` roles.
Gate D now implements exact-count 2-4 program generation contracts,
independent Gate C validation/execution, duplicate and provenance-padding
controls, deterministic support/complexity ranking, and fail-closed ambiguous
or no-valid states. It has only deterministic and fake-model evidence. No real
model run proves that the model produces genuinely diverse programs, and the
runtime selector has not been calibrated against answer correctness.

The support heuristic treats distinct minimal candidate/evidence closures as
independent runtime support. This is auditable but not a statistical proof of
independence or correctness. Semantically different minimal closures can still
agree by coincidence. Resumable live planner runs, retrospective diagnostics,
confirmatory evaluation, and raw PDF layout recovery remain later work.
