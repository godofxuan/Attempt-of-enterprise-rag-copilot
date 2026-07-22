# Known Limitations

最后更新：2026-07-22

本文使用三个状态：`FAILED` 表示已运行且未通过；`NOT RUN` 表示没有满足协议的 fixture/依赖或实验；“未实现”表示代码能力不存在。`NOT RUN` 不能写成通过。

## 1. 当前限制表

| Area | Current state | Consequence | Admission condition |
|---|---|---|---|
| Identity | `UserContext` 由浏览器/调用方声明，只做 schema 和 policy 验证 | 本地演示可以验证 ACL 逻辑，但不能证明真实用户身份 | 由可信 OIDC/IAM gateway 签发身份，并加入 token/tenant/group integration tests |
| Data realism | 72/600 文档和 52 个 eval cases 全部 synthetic | 指标证明工程 contract，不代表真实企业分布或生产泛化 | 法务批准的去标识 pilot corpus、数据治理记录和独立 held-out evaluation |
| Live quality | 当前 canonical live dev 为 23/24 | 一个 system-runtime failure 被保留；不能报告 100% | 先定位/复现失败，再在新冻结 split 上验证，而不是改写旧 artifact |
| Indirect document injection | D1-D7、V1-V5、S2-1、R2-S3 已完成；R2-S4 Task 1-5 已实现 canonical cross-model plan、V3 component、restart admission、六文件 private matrix 和八文件 public verifier，但真实 `-01` 双模型运行仍为 `NOT RUN` | 已证明固定规则集的软件传播边界、单模型可见 dev 观察与跨模型评测基础设施的离线 contract；尚无 Qwen2.5/Qwen3 正式 matrix 结果，不能声称跨模型泛化、未知攻击免疫或 production safety | 先按冻结协议完成 exact-HEAD gates 和一次性 R2-S4 run；独立 holdout、semantic judge calibration、human double review 仍需独立执行，且任何结果都不得命名为 release PASS |
| Reranker | `NOT RUN` (`no_admitted_reranker`) | 不能声称 cross-encoder/reranker 改善过排序 | 固定候选模型、license/资源预算与 latency gate；在 frozen test 上做隔离消融 |
| Human review | `NOT RUN`；50 行、8 个人工判断列保持空白 | 自动 claim/citation/required-fact checks 不能替代语义和可用性评分 | 本人按冻结 rubric 完成 review；若用于正式质量结论，再增加第二 reviewer、分歧仲裁和 agreement 记录 |
| Authentication/authorization | 只有本地 ACL policy，没有 SSO、token verification、policy admin 或 audit identity | 不能公网暴露为企业服务 | IAM、server-derived claims、deny-by-default policy store、admin/change audit |
| Index updates | immutable rebuild + activate；没有 incremental upsert/delete | 文档变化需要新 run，不能承诺低延迟同步 | 定义 document tombstone/version contract、idempotency、rollback 和 consistency tests |
| Observability | bounded in-memory traces/metrics | 重启丢失，不能跨进程关联或长期查询 | OpenTelemetry SDK/collector、durable backend、retention/redaction/access policy |
| Deployment | 本地 Windows + Ollama，未提供 production container/orchestrator | 没有证明 Linux image、network policy、resource limits 或 rolling deploy | Reproducible image/SBOM、health probes、secret injection、staging load and rollback |
| Remote CI | 历史 feature-branch commits `9607e55` 的 [Ubuntu run](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/29553278709) 与 `9fcb304` 的 [Ubuntu run](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/29682474913) 已通过 | 各自只证明对应 commit 的 deterministic CI，均不覆盖当前 R2-S4 candidate exact HEAD；没有证明 branch protection、merge、deployment 或 production runtime | 为当前精确 SHA 取得新的 remote CI，再把 workflow 设为受保护分支 required check，并增加可复现 image、SBOM 与 staging gates |
| Scale | demo index 64 chunks；benchmark 不是生产 load | FAISS/in-memory BM25 结论不能外推到 5,000+ 活跃文档与并发租户 | 规模/并发/更新率达到预设阈值后重新 profile，再决定 vector DB/caching |
| Model robustness | direct unsafe rule-first probe 只有 4 条 | 编码、多语言、间接和新型绕过仍可能通过 | 扩展 adversarial taxonomy、人工红队、版本化 model/prompt regression |
| Feedback | 仅保存 question/response SHA-256、helpful、request ID 和时间 | 无法直接读取正文调试；也没有用户级去重或分析平台 | 在隐私评审后建立受控 failure sampling，而不是默认保存全文 |
| Availability | 单进程、单 active index、单本地 Ollama | 没有 HA、队列、backpressure 或多副本一致性 | 明确 SLO/RTO/RPO 后再设计 replicas、queue 和 failover |
| Agent scope | 单 controller、固定工具 allowlist、无长期记忆/checkpoint | 不能称通用 autonomous/multi-Agent platform | 只有出现跨会话恢复或独立角色协作的真实需求与 eval 时才准入 |

## 2. 指标解释限制

- `28/28` deterministic 表示当前合成 test 上的系统 contract 全部通过；它不调用真实 chat/embedding 模型。
- `23/24` live 是一个开发 split 和一次指定本机环境运行；不能当作 production accuracy。
- retrieval 的 `precision@5` 分母固定为 5。单一 gold 文档题即使首位正确，后续位置会自然降低 precision；需要同时看 recall、MRR、NDCG、authority 和 invalid extras。
- workflow ablation 的 outcome accuracy 不逐句评价生成文本；response layer 另测 required facts、citation 和 unsupported claims。
- load p95 来自 31 次本地请求，样本小且硬件/模型常驻状态敏感；它是演示 profile，不是 SLO。
- public snapshot 是原始 artifacts 的脱敏摘要。它带 hash provenance，但不替代 ignored source run 的逐题复核。
- R2-S3 的 `28/28` depth-2/4 total reach 是 deterministic counterfactual coverage，不是 live production reach；额外 `29/33` scans 与 `3845/4200` input characters 也不是 wall-clock latency。

## 3. 安全声明限制

已经验证的是：固定 direct unsafe prompts 在 query analysis 后、retrieval 前 source-free 拒绝；ACL 测试不暴露 forbidden docs；错误/trace 不回显已知敏感字段；默认 V2 `search/find/open` 在 Controller 前执行确定性 admission，raw execution 被拒绝，已隔离内容不进入 generation/source/context budget。

尚未证明的是：任意 prompt injection 都会失败、真实 Qwen 在未知攻击或其他模型上的成功率、system prompt 永不泄露、显式 compatibility app 中的 legacy `/chat`/`/agent/chat` 受到 V2 Guard 保护、浏览器声明身份可信、或该服务适合公网/多租户生产。D6 fake generator 只证明确定性传播；D7 与 S2-1 都只观察到固定本地 BGE-M3/Qwen 配置下的可见 synthetic 数据。S2-1 的 `15/15` 是“已到达 Guard 后”的条件 detector 指标，不覆盖 13 个 unreached attack units；R2-S3 虽观察到相关 case downstream exposure `0/13`，但不能把 diagnostic depth-2 total coverage 改写成 live end-to-end `28/28`，也不能把 `NO_CURRENT_BYPASS_OBSERVED` 写成 release pass。

完整威胁与控制映射见 [Security Threat Model](security_threat_model.md)。

## 4. 公开展示边界

- README 与 UI 必须显示 live `23/24`，不能四舍五入为 100%。
- indirect document injection 必须分层显示：D4 guarded V2 data flow、D5 prompt/public observability、D6 deterministic frozen OFF/ON gate 已完成；D7 fixed-order 与 S2-1 counterbalanced local BGE-M3/Qwen paired runs 均为 `COMPLETED WITH OBSERVATIONS`；R2-S3 measurement-only ablation 为 `COMPLETE`，但 source live run 和 production Guard/retrieval/Agent 未改，counterfactual coverage 仅诊断。S2-2 只完成 holdout freeze/verify 基础设施；独立 package、holdout 结果、semantic judge、cross-model replication、人工红队和 optional reranker 仍是 `NOT RUN`。
- `526 passed` 是 E5 入口、`569 passed` 是 E6 收口、`574 passed` 是 E7 自动化本地门禁；它们是不同 commit 候选的历史计数，不能相加。
- 远端 CI 声明必须同时给出 run URL 和 commit；当前可核验的 `9607e55` 与 `9fcb304` 均为历史 feature-branch 证据，不覆盖当前 R2-S4 candidate exact HEAD。
- E7 已逐条处理 claims matrix；只能使用 `approved` 原句或 `narrowed` 后的措辞，不能删掉 synthetic、deterministic/local、样本数和 `NOT RUN` 边界。

下一阶段准入项与优先级见 [Industrialization Backlog](industrialization_backlog.md)。

## 5. R2-S1 current boundary

D1 froze the design; D3 built the model-free detector; D4 connected it to the default V2 path; D5 added prompt/trace/service defense in depth; D6 added the immutable deterministic paired gate. The D6 frozen synthetic result is OFF attack success `21/24` versus ON `0/24`, ON benign quarantine `0/32`, with `788 passed` full regression. D7 then observed one fixed-order local BGE-M3/Qwen pair. R2-S2 S2-1 repeated the visible dev experiment with a new run ID and exact 18/18 counterbalancing: OFF user-boundary signal `3/24` versus ON `0/24`, conditional quarantine `15/15`, all-labeled quarantine `15/28`, clean utility `12/12`, benign quarantine `0/32`, and zero model/system errors or blocked egress. S2-2 implements holdout admission and sealing, but no independent raw package or holdout score exists. None of these results establishes unseen-attack prevalence, immunity, cross-model generalization or production safety.

## 6. R2-S3 current boundary

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

The decision `NO_CURRENT_BYPASS_OBSERVED` means no current dev evidence
justifies a broader runtime prefilter. It is not a universal safety result,
release pass, or production deployment gate. Independent holdout evaluation,
semantic judge calibration, and cross-model replication remain `NOT RUN`.

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

## 8. R2-S4 pre-run boundary

R2-S4 Task 1-5 industrializes evaluation operations: a canonical plan with
SHA-256 `85175b88742d28b09431e1b1df35a27db5cd65fbd96fc33db0bcfd899efd4152`,
exact model digests, one clean Git/runtime snapshot, bounded restart admission,
immutable six-file private evidence, allowlisted eight-file public evidence,
and independent standard-library recomputation. This is infrastructure, not a
real cross-model result. The three planned immutable `-01` run targets have not
been executed at protocol-freeze time.

`CONSISTENT_OBSERVATION` means complete equal selected security/utility
observations even when both are equally bad. `DIVERGENT_OBSERVATION` means a
valid selected observation differs. Incomplete/error/blocked/non-chat mismatch
evidence is `INCONCLUSIVE`. The separate
`task4_non_release_safety_threshold_v2` requires exact `0/24`, `15/15`, `0/32`,
zero model/system errors, and zero blocked egress; `release_pass` remains false.

```text
independent holdout         NOT RUN
semantic judge calibration NOT RUN
human double review        NOT RUN
production traffic         NOT RUN
```

R2-S4 is evaluation-operation industrialization, not production-service
readiness. The only admitted next stage after R2-S4 closeout is R2-S5 Trusted
Identity Boundary because the secure API still trusts body-supplied
`UserContext`. Reproducible deployment and durable privacy-bounded telemetry
rank after identity. No framework, vector database, Kubernetes, multi-Agent, or
memory stack is admitted by this evidence.

The R2-S4 controller lock is limited to cooperating evaluator processes sharing
the same normalized local Ollama origin. It prevents overlapping R2-S4/live
evaluators inside this codebase, but it does not stop non-cooperating external
Ollama clients, provide production scheduling, or make model aliases immutable.
The manual no-other-Ollama-client check remains required before real execution.
Operators must not delete, rotate, replace, redirect, or clean
`R2_S4_EVALUATION_LOCK_DIR` during a run. Non-cooperating post-yield lock
pathname replacement is outside this local rendezvous lock's threat model.
