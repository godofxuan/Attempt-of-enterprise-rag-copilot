# Industrialization Backlog

最后更新：2026-07-21

本文不是承诺清单。每个 R2 项必须由真实失败、规模或合规需求触发，并在进入实现前定义可复现基线、验收指标、回滚和成本边界。当前 R1 状态见 [Project Status](../PROJECT_STATUS.md)。

## 1. Admission rules

一个 backlog item 只有同时满足以下条件才进入设计：

1. 有具体用户/业务风险，不是“先进 Agent 都有”；
2. 当前实现有可复现 failure 或规模证据；
3. 能写出独立变量实验或 contract test；
4. 定义性能、安全、成本和运营门槛；
5. 定义失败时的 rollback；
6. 不用 test/held-out 数据反复调参后继续声称 unseen。

## 2. Priority admission table

| Priority | Capability | Trigger evidence | Required gate | Why not in R1 |
|---|---|---|---|---|
| P0 | Trusted IAM identity | 需要多人/多 tenant 访问，浏览器自报 context 不可接受 | OIDC/JWT verification、server-derived tenant/group、deny-by-default、cross-tenant integration and revocation tests | 没有可信身份就不能公网部署；本地 ACL 只验证 policy data flow |
| P0 | Independent indirect-injection validation | S2-1 已完成 counterbalanced real-model dev replication；R2-S3 已解释 13 个 rank-2 unreached units 并观察到 downstream exposure 0/13，但两者仍是可见 synthetic cohort 和单一 BGE-M3/Qwen 配置；S2-2 没有独立原始包或结果 | 独立 reviewer package、pre-run freeze、one-shot holdout、blind double review、agreement/adjudication、semantic judge calibration、跨模型矩阵和 zero unauthorized action gate | Guard、可审计协议和 measurement-only exposure attribution 已实现；现在缺的是独立分布和语义层外部有效性，不能把 `NO_CURRENT_BYPASS_OBSERVED` 当 release pass 或继续靠同一可见集合调规则 |
| P0 | Human semantic review | 需要对外报告 response quality 或用于业务 pilot | Frozen rubric、blind double review、adjudication、agreement、claim/citation/omission severity | 自动 required-fact 与 lexical checks 不能替代语义可用性判断 |
| P1 | Incremental upsert/delete | 文档更新频率使全量 rebuild 超过 agreed freshness window | Idempotent event contract、version/tombstone、partial failure recovery、active snapshot consistency、rollback | R1 immutable rebuild 更易审计，当前 72-doc demo 没有增量压力 |
| P1 | Durable OpenTelemetry | 需要跨进程追踪、历史检索、告警或多副本 | OTel semantic conventions、collector/backend、sampling、redaction、retention、access control、trace-to-eval correlation | 当前 bounded memory 足以本地调试，直接加平台会先增加运维面 |
| P1 | Reproducible deployment | 需要 staging/pilot 或非 Windows 环境 | Minimal image、non-root user、SBOM、pinned image/model versions、health probes、resource limits、secret injection、rollback drill | 本阶段只验证本机，不冒充 production deploy |
| P1 | Remote CI evidence for the current R2-S3 exact HEAD | fixed exact HEAD whole-branch synthesis approval and repository-owner push/PR authorization | Actual run URL for the exact SHA、deterministic suite、pip/compile/public audit、artifact retention、branch protection | Historical `9607e55` success does not establish remote-CI evidence for the current R2-S3 exact HEAD |
| P2 | Vector service | Active corpus >=5,000 docs、multi-tenant QPS 或 update SLA 使 local FAISS lifecycle 不达标 | Same frozen retrieval/security suite、namespace isolation、backup/restore、p95/cost comparison、migration rollback | 先 profile；不能用“生产都用向量库”替代证据 |
| P2 | Admitted reranker | Retrieval failure analysis 显示 candidate set 有 gold、排序错误占主导 | Fixed candidate model/license、frozen ablation、quality delta、p95/memory/model-call budget、fallback | Current optional row is `NOT RUN`; metadata/temporal pipeline already fixes known synthetic misses |
| P2 | Query/result cache | Embed/generation cost或 latency profile 显示重复请求显著 | ACL/user/model/index version in key、TTL/invalidation、no cross-user reuse、hit/miss metrics | 错误 cache key 会造成比延迟更严重的数据泄漏 |
| P2 | Backpressure and queue | Concurrency load shows deadline collapse or resource exhaustion | Bounded queue、admission control、429 contract、cancellation、load/soak tests | 31-request demo profile 不足以设计生产容量 |
| P3 | Failure corpus workflow | 人工 review/feedback 量达到可治理规模 | Privacy approval、sampling、dedup、labels、retention、offline replay without raw identity | 当前 feedback 故意 hash-only，不能静默开始保存正文 |
| P3 | Model/prompt registry | 多模型/多 prompt 版本需要并行试验或回滚 | Immutable config ID、artifact provenance、evaluation diff、rollback and compatibility matrix | 当前一个 local profile 可由 run manifest 追踪 |
| P3 | Checkpoint/resume | 长任务超过 HTTP deadline且重试成本显著 | Durable state schema、idempotent tools、resume semantics、stale authorization recheck、failure injection | 当前 Agent 12-step/15s bounded flow 不需要恢复框架 |
| P4 | Multi-Agent delegation | 单 controller 因独立专业角色/并行任务出现可量化瓶颈 | Role-specific eval、delegation budget、shared-state isolation、conflict resolution、trace cost | 增加 Agent 数不会修复身份、证据、索引或观测问题 |
| P4 | Long-term memory | 有明确跨会话 personalization 需求和 consent/forget policy | Consent、tenant isolation、retention/delete、poisoning tests、retrieval provenance | 企业知识 QA 默认不应悄悄记住用户正文 |

## 3. Suggested R2 sequence

### R2-A: Trust before scale

1. Trusted IAM identity injection.
2. R2-S1 current-candidate review, Git delivery, and remote CI evidence.
3. Counterbalanced real-model development replication with a new run ID. `COMPLETE WITH OBSERVATIONS`
4. Independent indirect-injection holdout freeze/verify infrastructure. `IMPLEMENTED`; reviewer package and run `NOT RUN`
5. Measurement-only exposure ablation for the `13/28` observation. `COMPLETE`; accepted v2 run `r2-s3-dev-exposure-20260721-02`, no production change admitted
6. Independent package authoring, one-shot holdout execution, blind human review, semantic judge calibration, and cross-model replication. `NOT RUN`

没有完成独立验证、可信身份和部署门禁，不应把本地 demo 包装成多租户服务。

S2-1 暴露的 `13/28 unreached` 已由 R2-S3 在固定 Guard ruleset 下做 measurement-only ablation，不与 detector recall 混合。结果显示 13 个 units 全部在 runtime rank 2，observed downstream exposure `0/13`；depth 2/4 的 `28/28` total coverage 是 diagnostic replay，并分别增加 29/33 scans 和 3845/4200 input characters。该证据没有准入 retrieval exposure 改动。未来若出现 measured bypass 或 reachable unguarded path，必须新建设计并同时冻结 latency、clean utility、false-positive、model-call、security regression 和 rollback gates；不能为了让 test/holdout 分数变好而扩大上下文或扫描所有文档。

### R2-B: Lifecycle and operations

1. Incremental index events and tombstones.
2. Durable trace/metrics pipeline.
3. Reproducible Linux/container staging.
4. Load/soak profile and backpressure.

### R2-C: Evidence-driven optimization

1. Analyze frozen retrieval failures.
2. Admit reranker/cache/vector service only when their target failure dominates.
3. Repeat deterministic, live, security, latency, memory, and cost gates.

## 4. Required experiment template

每项优化记录：

```text
hypothesis
baseline run ID + hashes
single changed variable
frozen dataset/split
quality metrics + confidence interval
latency/model calls/RSS/cost
security regressions
failure rows
decision: admit / reject / inconclusive
rollback
```

“指标提高”不自动等于 admitted。必须同时满足安全和资源门槛；如果 improvement 只出现在 dev，test 只运行一次并保留原始 artifact。

## 5. Explicitly deferred claims

在对应 gate 完成前，不使用以下表述：

- production-ready / enterprise-ready deployment；
- secure against prompt injection；
- production SLO；
- real enterprise data accuracy；
- current R2-S3 exact HEAD remote CI passed;
- reranker/vector database improved quality；
- autonomous multi-Agent platform。

限制的当前证据见 [Known Limitations](known_limitations.md)，实现与信任边界见 [Architecture](architecture.md)。

Historical `9607e55` evidence applies only to that commit.
