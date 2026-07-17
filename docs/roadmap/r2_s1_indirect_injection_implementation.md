# R2-S1 Retrieved-Content Indirect Injection Implementation Journal

最后更新：2026-07-17
当前阶段：D2 red baseline recorded；Guard implementation `NOT RUN`

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
| Guard blocks malicious retrieved content | `NOT RUN` | no implementation or red/green test exists |
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

D3 will implement the standalone deterministic detector. The five integration failures are expected to remain red until D4 connects guarded types, admitted-only evidence and bounded candidate recovery.

## 11. Next Gate

```text
批准D2，执行D3 Guard核心实现
```
