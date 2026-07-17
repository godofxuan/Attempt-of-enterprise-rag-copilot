# R2-S1 Retrieved-Content Indirect Injection Implementation Journal

最后更新：2026-07-17
当前阶段：D5 prompt boundary 与安全可观测性本地 green；等待 D6 安全评测审批

## 1. Why R2-S1 Is Next

E7 已经证明 direct unsafe user prompts、ACL、typed bounded tools、citation shape 和安全 trace 的现有合同，但明确把 retrieved-content indirect injection 标为 `NOT RUN`。最大的安全证据缺口不是再增加一个 Agent framework，而是证明恶意文档能否进入模型、Controller 和回答，以及隔离后是否还能恢复干净证据。

## 2. D0 Read-Only Audit

### 2.1 Baseline

```text
repository       <project-root>
branch           codex/rag-eval-system
HEAD             da2ba8ccd4dcce455926758a8e9fb6fad20aec38
ancestor check   da2ba8c is ancestor, exit 0
tracked diff     empty
staged diff      empty
untracked        .superpowers/ only, classified and excluded
```

D0 没有修改代码、数据、测试、commit 或 push，也没有运行真实模型。

### 2.2 What the code actually did

```text
V2ToolRegistry.run
-> raw SearchResult/FindResult/OpenResult
-> Controller.observe
-> EvidenceLedger
-> generation/citation/response
```

这说明“在 prompt 前加一个正则”太晚。即使 generator 没看到投毒文本，Ledger、词法 citation verifier 或 extractive response 也可能已经消费它。

### 2.3 Difficulties found

| Difficulty | Why it matters | D1 resolution |
|---|---|---|
| candidate pool 在返回前裁为 top-k | 删除恶意 top-k 后没有干净候选可补 | Guard 接在 ranked pool 与 admitted top-k 之间 |
| raw chars 先计入 context budget | 大恶意文本可在被隔离前制造 availability failure | admitted chars 才进模型预算；scan chars 单独有界 |
| child 与 parent 是两个内容面 | 只扫 matched child 会漏掉 parent/open payload | matched、parent、find、open 分别决策 |
| legacy endpoints 仍公开 | 只保护 V2 仍有实际旁路 | secure profile 不注册 legacy generation/ingest |
| Trace 想可解释又不能泄露 | 原文或裸 hash 会扩大隐私面 | public aggregate；private synthetic IDs |
| fixed rules 容易误报 | 安全培训文本也会写“忽略系统指令” | rule combination + 12 benign cases per split |

## 3. D1 Documents and Responsibilities

| File | Responsibility |
|---|---|
| `docs/superpowers/specs/2026-07-17-r2-s1-indirect-prompt-injection-design.md` | one authoritative end-to-end design |
| `docs/security/r2_s1/00_scope_and_threat_model.md` | assets, adversary, threats, residual risk |
| `docs/security/r2_s1/01_attack_surface_and_trust_boundaries.md` | every raw source/sink/bypass and capability matrix |
| `docs/security/r2_s1/02_design_options_and_decisions.md` | alternatives, reason, trade-off and rollback |
| `docs/security/r2_s1/03_detailed_design.md` | schema drafts, algorithms and failure semantics |
| `docs/security/r2_s1/04_evaluation_protocol.md` | dataset, formulas, gates, artifacts and provenance |

Existing README/status/architecture/threat/evaluation/limitations/ledger/handoff files are synchronized only with links and honest D1 status. They do not claim the Guard exists.

## 4. Frozen Behavioral Contract

1. `enforce` is the service default; missing config cannot become off.
2. `audit/off` exist only through explicit test/evaluator dependency injection.
3. raw content can cross only into Guard; Controller rejects raw execution at runtime.
4. per-content Guard error quarantines that item and continues clean evidence.
5. invalid/missing Guard initialization returns source-free system behavior.
6. all usable candidates filtered becomes `security_filtered/evidence_filtered`, not `not_found`.
7. quarantine does not consume admitted top-k, per-doc diversity or model context budget.
8. top-up stays inside one ACL-visible `candidate_k` pool and never loops/re-embeds.
9. prompt boundary is secondary defense; model never receives quarantine summaries.
10. public trace stores aggregate counters/categories/rule IDs/version, not content, IDs or naked hashes.
11. secure profile does not expose current legacy bypass routes.
12. fixed-set success is reported with split/count/hash and never as immunity.

## 5. Dataset and Evaluation Decision

Each split has 36 cases: 24 attacks from eight families and 12 benign controls from four families. Both dev and test independently retain three variants per category. This is deliberately stronger than splitting one 36-case minimum into two underpowered halves.

Deterministic fake-generator evidence and local live-model evidence remain separate. The former proves data propagation; the latter records one fixed model/environment behavior. Neither replaces manual security review or unknown-attack testing.

## 6. R1 Freeze Evidence at D1

```text
data/v2/eval/dev.json
  92b4753df4e69bb570e9ea202420b46124207f15a07cdbb421fb00e6990082bd
data/v2/eval/test.json
  556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
data/v2/eval/test_manifest.sha256
  fc9151daee0d6a0ac1ecfd1b6a3e361bc985d3f8512a8bc76927528ecd32f253
git diff --exit-code for these files
  exit 0
```

R2-S1 will use `data/v2/security/` and cannot overwrite these files or their historical artifacts.

## 7. Current Evidence Level

| Claim | State | Why |
|---|---|---|
| current raw path has an indirect-injection exposure surface | `OBSERVED` | code path inspected at D0 |
| proposed boundary is internally specified | `D1 FROZEN` | schemas, outcomes and metrics documented |
| standalone Guard classifies bounded text | `D3 UNIT GREEN` | 64 model-free schema/rule/resource/failure tests |
| Guard blocks runtime retrieved content | `NOT RUN` | D3 is not wired to retrieval/Controller/generation |
| top-up recovers clean evidence | `NOT RUN` | no guarded candidate path exists |
| frozen attack set passes | `NOT RUN` | dataset/evaluator not created |
| Qwen resists or follows attacks | `NOT RUN` | live trial requires D7 approval |

## 8. D2 Authorization Status

D2 was authorized and executed after D1. It added only red baseline tests and evidence documentation. It did not add real side-effect tools, contact attack URLs, disable a production Guard, change R1 data or label a fake generator result as a real-model attack rate.

The detailed result is recorded in:

```text
docs/security/r2_s1/05_results.md
```

## 9. D1 Self-Review Evidence

The D1 self-review found one contract ambiguity before closeout: `admitted_count` could have meant either Guard-admitted content units or diversity-selected result objects. The design now fixes:

```text
admitted_count               GuardDecision=ADMIT content units
post_guard_evidence_count    safe result objects selected downstream
scanned_count                admitted_count + quarantined_count
```

Final D1 static evidence:

```text
target D1 public audit       15 candidates, 0 findings
full public audit            345 candidates, 0 findings
unfinished-marker scan       0
git diff --check             exit 0
tracked implementation scope app/tests/data/scripts changes 0
R1 dev/test/manifest diff    exit 0
R1 SHA-256                   exact D1 recorded values
pytest                       not run by D1 design-only protocol
live model                   not run by D1 design-only protocol
```

No business code, implementation test or dataset file was modified. The only non-document untracked surface remains the pre-existing `.superpowers/` browser companion, which was neither staged nor changed as part of D1.

## 10. D2 Red Baseline

### 10.1 Changes

```text
tests/security/test_indirect_injection_red_baseline.py
  - selected SearchHit/OpenResult -> generation-context canary assertion
  - deliberately compliant fake-generator propagation assertion
  - raw SearchResult/OpenResult runtime-boundary assertions
  - public-trace raw-content assertion
  - requests/socket egress blocker and no-egress assertion

tests/retrieval/test_indirect_injection_red_baseline.py
  - real HybridRetrievalPipeline top-1 poison displacement assertion

docs/security/r2_s1/05_results.md
  - exact D2 command, result, failure meaning and non-claims
```

No `app/` file, production configuration, R1 evaluation data or live model was changed or used.

### 10.2 Actual RED result

```text
collected 8
failed    5
passed    3
```

The five expected failures prove:

1. selected malicious text currently enters generation messages;
2. the deterministic propagation fake can place the document canary in a valid answer;
3. `Controller.observe` currently accepts raw search execution;
4. `Controller.observe` currently accepts raw open execution;
5. pre-Guard top-k selection returns poison and discards the clean rank-2 candidate.

The three passes prove current public trace redaction, egress interception and the absence of a network attempt in the pure in-memory fake path. They were left green because D2 records reality instead of forcing every case to fail.

### 10.3 Control result

The existing generation, Controller, runner and retrieval-ranking suites remained green:

```text
36 passed, 3 known FAISS warnings
```

Raw outputs are retained under ignored `.private/r2_s1/` files and are not committed because they contain absolute local paths and complete synthetic payloads.

### 10.4 Engineering conclusion

The main issue is not that the system prompt forgot to say “evidence is untrusted”; that sentence already exists. The missing control is a deterministic boundary before raw retrieved content reaches Controller and generation. Citation verification also cannot solve the problem because a malicious canary copied from cited evidence receives lexical support.

D3 has now implemented the standalone deterministic detector. The five integration failures remain red exactly as expected until D4 connects guarded types, admitted-only evidence and bounded candidate recovery.

## 11. D3 Guard Core Implementation

### 11.1 What changed

```text
app/domain/retrieved_security.py
  - rcg-v1.0.0 identity and hard resource limits
  - fixed rule/category/severity mapping
  - strict, frozen, content-free GuardDecision

app/security/retrieved_content.py
  - 14k prefix + 6k suffix source/normalization views
  - NFKC, casefold, Unicode Cf removal and limited confusables
  - instruction/role/secret/egress proximity rules
  - risky-markup annotation and descriptive-quote suppression
  - one-level bounded Base64 discovery and decoded-byte threshold
  - per-item fail-closed wrapper and complete rule provenance hash

tests/security/test_retrieved_content_guard.py
  - 64 contract, attack, benign, obfuscation, bound and exception tests
```

`app/security/__init__.py` exposes the Guard and rule hash as the stable package
contract. D3 did not touch retrieval, tools, Controller, generation, API, model
configuration, indexes or R1 frozen data.

### 11.2 Why the design is deterministic instead of LLM-as-judge

This component is a pre-model security boundary. Calling an LLM here would send
the untrusted payload to another model, add latency/network failure modes, make
decisions non-reproducible and still require a deterministic fail-closed policy.
The Guard therefore uses static rule combinations and bounded normalization.
Later evaluation can compare its false positives/negatives and a live model can
remain a separately labeled secondary experiment.

### 11.3 Difficulties and corrections

The first green implementation was not accepted without adversarial review. A
read-only reviewer found suffix loss after Unicode expansion, false quote
suppression, missing Unicode controls, quadratic rule pairing, mutable/coercive
decision fields and incomplete rule-hash provenance. Each became a regression
test before correction. The review batch was `13 failed / 51 passed`, then the
corrected core reached `64 passed`.

The most important engineering lesson is that a scanner's security boundary is
defined as much by resource accounting, normalization and immutable result types
as by its keyword patterns. A detector that finds the obvious string but can be
bypassed by formatting controls or exhausted by repeated tokens is not a useful
Agent boundary.

### 11.4 Actual evidence and honest boundary

```text
Guard core                                  64 passed
security excluding intentional D2 RED       84 passed
agent/retrieval excluding intentional D2   116 passed
full suite excluding intentional D2 RED    638 passed
D2 integration baseline                      5 failed / 3 passed
detector version                            rcg-v1.0.0
rule SHA-256                                a544f013e5570b24488220b3ba11c721a2c6e05b2a4895b027dd0601363bbdb0
```

The unchanged D2 failures are not a failed D3 acceptance. They prove the phase
boundary is intact: no production path calls the Guard yet. D4 must make raw tool
results unrepresentable downstream, quarantine before admitted top-k, top up from
the same ACL-visible candidate pool, and expose only aggregate security counters.

## 12. Historical D3 Gate

```text
批准D3，执行D4数据流接入与能力约束
```

## 13. D4 Guarded Data Flow Implementation

### 13.1 Entry and objective

```text
D4 entry HEAD    ec85cc718b3df17731fb1d9df7300a3a7c6fe5be
objective        raw retrieval must not legally enter Controller state
non-goals        D5 prompt nonce/public counters; D6 72-case OFF/ON evaluation
```

D3 回答“单段文本如何确定性分类”；D4 回答“分类器如何成为不可跳过的数据流边界”。因此主要工作不在增加 regex，而在 retrieval 候选生命周期、admitted 类型、工具结果和 Controller state。

### 13.2 Runtime path after D4

```text
ACL + metadata filtering
-> one ranked pool capped at candidate_k
-> body/parent/metadata/find/open/adjacent-split admission
-> quarantine + bounded clean-candidate fill
-> GuardedV2ToolExecution
-> runtime guarded-type check
-> deeply immutable admitted evidence only
-> Ledger / Generation / Citation / Response
```

关键代码所有权：

| Boundary | Owner |
|---|---|
| guarded/admitted contracts | `app/domain/retrieved_security.py` |
| pre-top-k ranked pool | `app/retrieval/pipeline.py` |
| object admission and split/top-up | `app/security/retrieved_admission.py` |
| mandatory tool enforcement/deadline/budget | `app/agent/tools_v2.py` |
| raw rejection and safe terminal outcome | `app/agent/controller_v2.py`, `app/agent/runner_v2.py` |
| admitted-only sinks | ledger, relevance, generation and citation modules |

### 13.3 Independent review correction loop

第一轮实现曾达到 `677 passed`，但独立只读审查仍构造出 2 个 Critical 和 6 个 Important 反例：version metadata bypass、NFKC split bound、hybrid pool 上限、Guard deadline、shallow freeze、identical parent/child、mixed split contributors 和 parent context budget。全部先变成回归测试，得到 `8 failed / 28 passed`；修复后 focused batch 为 `38 passed`，全仓库为 `687 passed`。

额外增加了 Admission 自己的 `candidate_k` 截断。这样即使未来 custom Navigator 违反 pipeline 合同，安全边界也不会扫描或补位到请求上限之外。

### 13.4 Evidence and honest claim

```text
detector version                       rcg-v1.1.0
rule SHA-256                           dcafd504a01dcc757910751503eaaf1387903827e5e0f4932fbdd7937b68da01
D2/D4 propagation and top-up             8 passed
independent-review focused               38 passed
Agent V2                                 98 passed
full offline repository suite           687 passed
warnings                                   3 known FAISS SWIG warnings
public repository audit                 359 candidates / 0 findings
```

R1 dev/test/manifest hashes保持冻结值不变；D4 没有调用 Ollama、embedding、外网或 live security trial。当前可以说“默认 V2 本地数据流在 Controller 前强制执行确定性 retrieved-content admission”，不能说“防住所有间接提示词注入”。完整逐文件讲解、问题原因和面试问答见 [D4 Engineering Journal](../security/r2_s1/06_d4_engineering_journal.md)。

## 14. Next Gate

```text
批准D5，执行D6安全评测与门禁

## 15. D5 Prompt Boundary and Security Observability

D5 从 `86064322fd532264623abd23e8db7a99634ab342` 开始，完成了四条冻结合同：

- `app/agent/generation_v2.py` 使用 fresh per-model-call nonce、JSON admitted records、exact begin/end/reminder，并对 Unicode line separators 做额外 escape；
- `app/domain/retrieved_security.py` 和 `app/agent/runner_v2.py` 只公开严格 allowlist 的 Guard aggregate；
- `app/main.py` 的默认 `create_app()` 不再注册 `/ingest`、`/chat`、`/agent/chat`，legacy regression 必须显式使用 `create_compatibility_app()`；
- `app/security/retrieved_content.py` 和 `app/runtime/resources.py` 在 startup/readiness 验证 ruleset，只公开 `retrieved_guard=ready|error`。

测试经历第一轮 `17 failed / 10 passed`、focused `27 passed`、首次 full `690 passed / 6 failed`、三个额外 adversarial RED，再达到 full offline `697 passed, 3 known FAISS/SWIG warnings`。D5 没有修改 detector rule semantics，版本仍为 `rcg-v1.1.0`，ruleset SHA-256 仍为 `dcafd504a01dcc757910751503eaaf1387903827e5e0f4932fbdd7937b68da01`。

完整逐文件代码讲解、问题复盘和面试问答见 [D5 Engineering Journal](../security/r2_s1/07_d5_engineering_journal.md)。这仍不是 D6 attack success/false-positive evidence；72-case dataset、OFF/ON paired run 和 local live trial 保持 `NOT RUN`。
```
