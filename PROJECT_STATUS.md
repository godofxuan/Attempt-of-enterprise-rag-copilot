# Enterprise Agentic RAG - Current Status

## 2026-08-21 Durable runtime candidate overlay

```text
working branch                     codex/durable-agent-runtime-and-policy-v1
base                               909a9710932c6c4744c462db0e33ed0d222ecb1a
default runtime                    BOUNDED CONTROLLER / UNCHANGED
partial-answer HITL                SAME-PROCESS / EXISTING PATH
draft approval HITL                FILE-BACKED SQLITE RESTART TESTED
tool policy                        DENY > ASK > ALLOW / TYPED HOOKS
side effect                        ACCESS-REQUEST DRAFT ONLY / IDEMPOTENT SQLITE
OpenTelemetry                      W3C TRACE CONTEXT / CONTENT CAPTURE OFF
PostgreSQL checkpointer            TEST IMPLEMENTED / LOCAL DSN NOT CONFIGURED
production readiness               NOT ESTABLISHED / NOT CLAIMED
```

This overlay is a feature-branch candidate on top of the closed vNext baseline.
It does not rewrite the frozen retrieval, answer, security, or latency results.
The durable path is limited to one approved access-request draft operation; the
existing partial-answer HITL remains same-process. Local Agent Runtime evidence
is `81 passed, 1 skipped`, where the skip is the real PostgreSQL checkpointer
test awaiting its configured CI service. The canonical mechanism documents are
under `docs/production_runtime/`. Exactly-once, production IAM, arbitrary-action
HITL, high availability, and production readiness remain forbidden claims.

## 2026-08-20 Canonical vNext base state

```text
review date                        2026-08-20
target branch                      codex/agent-runtime-vnext
sync input PRE_SYNC_HEAD           ef9d0a919d3c002b7d868035c90b9f9624202513
canonical state                    RAG_VNEXT_CLOSED
portfolio / resume / interview     USABLE WITH EVIDENCE BOUNDARIES
production readiness               NOT ESTABLISHED / NOT CLAIMED
merge to main                      USER DECISION / NOT PERFORMED
default runtime                    BOUNDED CONTROLLER
LangGraph                          REAL ALTERNATIVE / NO QUALITY UPLIFT CLAIM
MCP                                OFFICIAL SDK / LOCAL IN-PROCESS ADAPTER
trajectory                         APPEND-ONLY SHA-256 CHAIN / TAMPER-EVIDENT
replay                             DETERMINISTIC / NO MODEL OR TOOL REEXECUTION
HITL                               SAME-PROCESS RESUME / NOT CRASH-DURABLE
EvalOps artifact                   enterprise.agent-run/1.0
```

This is the only canonical current state on the vNext branch. The Python host,
not a prompt or orchestration framework, owns identity, ACL narrowing, tool
allow-lists, budget, deadline, retrieved-content Guard, Evidence Ledger,
citation filtering, and final publication. `BoundedControllerAdapter` remains
the default. `LangGraphOrchestratorAdapter` is a real `StateGraph` behind the
same `AgentOrchestrator` and ToolGateway contracts; the five-case diagnostic
showed parity, not an answer-quality improvement, and is not a production
latency benchmark.

The official MCP Python SDK is used only as an in-process adapter for
`search/find/open`. Its opaque server-issued context handle resolves back to
ToolGateway; no network transport, OAuth deployment, or remote production MCP
claim is established. Trajectories are ordered, append-only at the application
boundary, linked by SHA-256, replayable without model/network/tool calls, and
exportable as `enterprise.agent-run/1.0`. Local SQLite is tamper-evident rather
than WORM or externally signed. HITL supports tenant/role-bound, one-time,
retry-safe same-process resume; pending state is not durable across restart.

### Strongest measured evidence

- WixQA ExpertWritten, 200 fixed public-label retrieval questions: BGE-M3 Dense
  Recall@5 `42.75% -> 66.42%`, nDCG@5 `32.15% -> 52.16%`. These are retrieval
  metrics, not answer accuracy.
- EnterpriseRAG-Bench public synthetic corpus: one-host SQLite FTS5 build over
  `511,962` records / 9 source types, `1.37 GiB`, `231.35 s`, approximately
  `1.83 GiB` peak RSS. This is not production capacity or real private data.
- Pinned garak subset: observed ASR `4/12 -> 0/12` and context exposure
  `12/12 -> 0/12`. This narrow subset does not establish universal safety.

### Claims that remain forbidden

Do not claim production readiness, production traffic/SLO/QPS/HA, answer
accuracy of `66.42%`, LangGraph quality improvement, production network
MCP/OAuth, durable crash-safe HITL, WORM audit storage, universal injection
defense, SOTA, independent third-party reproduction, or a deployed
multi-document quality improvement.

### Authoritative reading order

1. `docs/handoffs/PROJECT_EVIDENCE_MAP.md`
2. `docs/handoffs/RESUME_METRIC_LEDGER.md`
3. `docs/agent_runtime/10_FINAL_ARCHITECTURE.md`
4. `docs/agent_runtime/09_SECURITY_REVIEW.md`
5. `docs/learning/AGENT_RUNTIME_TUTORIAL.md`
6. `docs/handoffs/TEACHING_CODEX_HANDOFF.md`
7. `docs/handoffs/INTERVIEW_STORY_BANK.md`
8. `docs/handoffs/FINAL_PORTFOLIO_SYNC_REPORT_20260820.md`

Portfolio-ready means that implementation, tests, evidence, and claim
boundaries are inspectable. It does not mean production-ready. Merge remains a
repository-owner decision.

## Historical stages

Every dated section below records the state and decision at that historical
cutoff. It remains evidence, but it must not override the 2026-08-20 canonical
vNext state above. In particular, `current Agent candidate REJECTED` referred
to the bounded multi-document quality candidate evaluated on consumed cases.
It did not mean that the later Agent Runtime abstraction, LangGraph alternative,
MCP adapter, trajectory, replay, HITL, or EvalOps artifact did not exist. The
negative quality result remains valid and the vNext mechanism work does not
retroactively turn it into a positive quality result.

## 2026-08-11 Portfolio archive state (HISTORICAL)

```text
canonical state                    PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW
portfolio / interview usable       YES
engineering evidence credible      YES, WITH FROZEN SCOPE BOUNDARIES
current Agent candidate            REJECTED
blind answer correctness           NOT ESTABLISHED
retrieved-content security         VERIFIED ON ONE NARROW EXTERNAL SUBSET
production readiness               NOT CLAIMED
feature development                STOPPED
archive local suite                3232 PASSED / 30 SKIPPED / 3 KNOWN WARNINGS
archive public audit               1603 CANDIDATES / 0 FINDINGS
```

At that cutoff this was the repository's portfolio enum. Earlier
`PORTFOLIO_READY_*` strings in dated closeout reports are historical stage
decisions, not competing current states. Current resume, teaching, and recruiter
tasks must start from [Project Evidence Map](docs/handoffs/PROJECT_EVIDENCE_MAP.md).
The historical resume package remains under `docs/handoffs/resume_package/`.
The complete closure decision is in
[Portfolio Archive Report](docs/handoffs/PORTFOLIO_ARCHIVE_REPORT.md).

## 2026-08-11 Bounded multi-document candidate decision

```text
scope                              RETROSPECTIVE DEVELOPMENT / 20 CONSUMED CASES
design                             2x2 acquisition x evidence-selection ablation
implementation SHA                 d29639c8b3f037560385d5c7ad1b847dae4fc4ab
current -> combined completeness   0.00% -> 0.00%
current -> combined recall         21.67% -> 24.17%
current -> combined precision      45.00% -> 39.17%
current -> combined p95            600.09 -> 1115.59 ms
paired complete-case fixes         0
decision                           DEVELOPMENT_CANDIDATE_REJECTED
production default                 UNCHANGED
```

The frozen bounded clause-decomposition and admitted-only selective-evidence
candidate failed its pre-registered quality gate. Eight questions decomposed
and seven changed Top-5 order, but no case gained retrieval recall. Seventeen
of twenty remained acquisition-incomplete; all gold was admitted in the other
three, yet selection still failed to cite the complete set. The candidate is
not eligible for fixed validation, serving integration, or resume uplift.

Authoritative records: [results](docs/multidoc_candidate/02_RESULTS_AND_DECISION.md),
[failure analysis](docs/multidoc_candidate/03_FAILURE_ANALYSIS_AND_ROADMAP.md),
and [learning guide](docs/multidoc_candidate/04_LEARNING_AND_INTERVIEW_GUIDE.md).

## 2026-08-10 Portfolio verification hardening

```text
scope                              EVIDENCE DELIVERY / NO NEW MODEL OR AGENT
entry point                        python -m scripts.verify_portfolio_release
clean-worktree policy              FAIL CLOSED
offline subgates                   dependency / compile / evidence / Agent-ACL-Guard / public audit
output                             portfolio_release_verification_v1 JSON
production release authority       FALSE
README stale CI state              FIXED AND REGRESSION TESTED
CI enforcement                     UBUNTU + WINDOWS
focused contract tests             8 passed
full local regression              3188 passed / 29 skipped / 3 known warnings
public repository audit            1544 candidates / 0 findings
dirty development rehearsal        5/5 subgates / DEVELOPMENT_VERIFIED
```

The final closeout exposed one delivery defect rather than a model defect:
README still said the exact-SHA gate was pending after it had passed. The new
regression assertion prevents that stale phrase from returning. A single
cross-platform verifier now owns the public-clone acceptance path; CI calls the
same command that an interviewer or reviewer runs locally. A dirty repository
fails by default because uncommitted code cannot be tied to a Git SHA. The
explicit `--allow-dirty` mode is development-only and reports
`DEVELOPMENT_VERIFIED`, never `VERIFIED`.

This gate does not change or rerun WixQA, EnterpriseRAG-Bench, FinQA, or garak
metrics. It verifies that the existing evidence, prose, deterministic behavior,
and disclosure audit still agree. See
[implementation record](docs/final_closeout/05_PORTFOLIO_RELEASE_GATE.md).

## 2026-08-10 Final evidence closure

```text
2026-08-10 stage decision           PORTFOLIO_READY_STOP_DEVELOPMENT (HISTORICAL)
WixQA clean replay                 VERIFIED / 63 quality comparisons / tolerance 0.0
fresh WixQA index                  6,221 articles / 11,975 chunks / BGE-M3 1024d
historical private inputs          NOT USED
ExpertWritten Dense                Recall@5 66.42% / nDCG@5 52.16%
reproduction gap                  NONE IN QUALITY / latency machine-specific
Enterprise reused IDs             4 groups / 8 physical rows / 1 affected question
record-aware sensitivity          Recall@5 60.3741% -> 60.2677% (-0.1064pp)
FTS lifecycle                     SINGLE_WRITER_OFFLINE_BUILDER / ATOMIC_ACTIVATION
Agent effect                      REJECTED / no new Agent experiment run
Full Enterprise Dense             NO-GO / quality NOT_RUN
production                        NOT_CLAIMED
focused closeout tests            26 passed
full local pre-repair gate        3182 passed / 29 skipped / 2 doc-contract failures
public repository audit           1539 candidates / 0 findings
release payload / Actions          dad6336a / Run 31325310671 / SUCCESS
```

The clean replay downloaded official LF source into a new root, rebuilt every
embedding and the index in new roots, and evaluated Synthetic 6,221, Simulated
200, and ExpertWritten 200. An independent verifier found no quality difference
from historical public v2 evidence. Attempt 1 remains recorded: it stopped on
the historical CRLF versus official LF byte mismatch; canonical JSON and derived
question IDs were proved equal before transport-corrected protocol v2 was frozen.

The 511,962-row EnterpriseRAG-Bench audit found four reused source IDs. Only
`qst_0413` is affected; strict physical-record scoring changes overall Macro
Recall@5 by 0.1064 percentage points. The official ID-aware metric remains the
benchmark result and the record-aware value is explicitly a sensitivity.

No new Agent, framework, model, or Dense experiment was added. The existing
Agent route and equal RRF remain rejected; full Dense remains NO-GO. Release
work is limited to evidence, demo, resume, teaching, interview, audit, local
gate, and exact-SHA CI synchronization. See
[clean evidence](docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json),
[identity sensitivity](docs/final_closeout/02_REUSED_SOURCE_ID_SENSITIVITY.md),
and [demo](docs/demo/INTERVIEW_DEMO_RUNBOOK.md).

## 2026-08-09 Rapid quality and resume release closeout

```text
CORE_RAG             VERIFIED
ENTERPRISE_SCALE     VERIFIED
SECURITY             VERIFIED_LIMITED
AGENT_MECHANISM      VERIFIED
AGENT_EFFECT         REJECTED
FULL_DENSE           REJECTED_FOR_THIS_SPRINT / QUALITY_NOT_RUN
PRODUCTION           NOT_CLAIMED
HIDDEN_HOLDOUT       NOT_CLAIMED
clean detached reproduction   214 PASSED / 1 SKIPPED / public audit 1517/0
final full local suite         3174 PASSED / 29 SKIPPED / 3 WARNINGS
```

The rapid sprint fixed asymmetric-negation citation contradictions, completed
the public WixQA three-arm evidence, and enforced a single-writer atomic FTS5
activation contract. A 27-case retrospective multi-document Agent ablation
raised evidence/citation completeness `0% -> 22.22%`, but citation precision
fell `44.44% -> 18.52%`; the candidate remains held and is not a resume result.
A real BGE-M3 1k/10k/50k capacity qualification sustained
`35.74/35.93/36.76 chunks/s`, projecting a full Dense build at `12.87 h`.
Full Dense is a no-go because runtime, resumable-shard, and unconsumed-quality-
protocol gates are not all satisfied.

The first sandboxed full-suite attempt reached `3171 passed` and hit one
Windows `PermissionError` in a four-process computation-cache lock test. The
isolated test then passed once in the default environment and `10/10` outside
the sandbox; the complete non-sandboxed suite passed `3172/3172`. No code change
was made for an unconfirmed root cause.

The final CI-hardening pass made `pyarrow` lazy for the optional Dense capacity
runner and split the WixQA cohort test into an always-public evidence contract
plus a source-present reconstruction check. With the official source available
locally, the final suite passed `3174 passed / 29 skipped / 3 warnings` in
191.90 s.

The detached public-clone gate at `a3ef9c8` generated 240 source documents,
previewed 216 canonical documents/chunks, passed `214` focused tests, and
skipped only official-source reconstruction because external WixQA raw data is
not committed. Public audit remained `1517 candidates / 0 findings`.

GitHub Actions Run `31316231539` verified pushed payload `68523e8` with
successful Ubuntu, Windows, and Linux container-contract jobs. This is a
repository/deployment gate, not promotion evidence for the held Agent or Dense
experiments. See [remote verification](docs/rapid_upgrade/REMOTE_VERIFICATION.md).

Current decision: `STOP FEATURE DEVELOPMENT`. Retain the verified RAG, scale,
and limited security evidence; move to demonstration, code study, interview
practice, and job-specific adaptation. See the
[rapid report](docs/rapid_upgrade/FINAL_REPORT.md),
[Agent decision](docs/rapid_upgrade/03_AGENT_FAST_TRACK.md), and
[Dense capacity decision](docs/rapid_upgrade/04_DENSE_CAPACITY_RESULT.md).

## 2026-08-09 Enterprise-aligned external evaluation closeout

```text
primary enterprise benchmark             WixQA ExpertWritten
WixQA Dense Recall@5 / nDCG@5            66.42% / 52.16%
WixQA BM25 Recall@5 / nDCG@5             42.75% / 32.15%
WixQA equal-RRF decision                  REJECTED
EnterpriseRAG full corpus                 511,962 rows / 9 source types
Enterprise FTS5 build                     1.37 GiB / 231.35 s / ~1.83 GiB peak
Enterprise B0 Recall@5 / nDCG@5           60.37% / 55.89%
Enterprise multi-doc complete@5           28.26% (92 cases)
largest failure                           RETRIEVAL_MISS 153/470
current WixQA Agent                       AGENTIC_ROUTE_REJECTED
Enterprise Dense / RRF / Agent            NOT_RUN
source-aware chunking / external refusal  NOT_RUN
enterprise focused tests                  8 passed
full repository                           3147 passed / 30 skipped / 3 warnings
public repository audit                   1489 candidates / 0 findings
```

WixQA now supplies the primary real-support retrieval evidence. BGE-M3 Dense
beats BM25 and equal RRF on the fixed public-label ExpertWritten cohort. The
full EnterpriseRAG-Bench corpus was verified and indexed with a disk-backed,
resumable FTS5 control after capacity analysis showed the old Python BM25 design
would exceed host memory. The full B0 result exposes semantic retrieval and
multi-document completeness as the dominant gaps.

The production V2 Agent path was also evaluated with the same B2 retriever. It
made one search and zero `find/open` calls per question, did not improve recall,
collapsed multi-article citation completeness to zero, and added latency. It is
therefore explicitly rejected as a quality route rather than promoted because
the mechanism exists.

Authoritative closeout: [final report](docs/enterprise_eval/FINAL_REPORT.md),
[resume-safe metrics](docs/enterprise_eval/RESUME_SAFE_METRICS.md), and
[teaching handoff](docs/learning/RAG_PROJECT_TEACHING_HANDOFF.md).

## 2026-08-07 FinQA Gate E19 versioned service wiring

```text
decision                               E19_VERSIONED_SERVICE_WIRING_PASSED_DEFAULT_OFF_NOT_PROMOTED
versioned entrypoint                   app.main_v2:app
production default                     app.main:app / OFF / 0 basis points
paired OFF/LOCAL_TEST_ONLY requests    8
primary response / receipt mismatches  0 / 0
OFF worker starts / calls              0 / 0
enabled starts / offers / completions  1 / 8 / 8
provider failure primary HTTP status   200
backpressure rejects                   1 (bounded test)
residual contexts after shutdown       0
legacy generic offers                  0
secondary retrieval / model calls      0 / 0
public content findings                0
protocol SHA-256                       ec21d0a894e2a00d37a2c4aae8a48cd8cd1b8c0c19c4672503643bc3a924d67f
public evidence SHA-256                1616e1f509e61c8e65c90dba076d11ae40e20f96448be757774c4a28ed31de39
focused E16-E19 tests                  16 passed
full repository                        3035 passed / 29 skipped / 3 warnings
public repository audit                1362 candidates / 0 findings
```

E19 adds a versioned FastAPI assembly that connects E18 admitted-evidence
typed-context preparation to the real Agent route after primary response
construction. It preserves exact primary response bytes and feedback receipts,
starts no worker in the default OFF mode, fails local-test startup closed,
isolates provider errors, bounds queue admission, and publishes allowlisted
aggregate metrics only. The Docker default remains the frozen E16 entrypoint;
this is service-wiring evidence, not serving promotion or answer-quality proof.

Detailed state: [engineering record](docs/external_datasets/finqa_service_wiring_gate_e19.md),
[learning chapter](docs/learning/40_FINQA_GATE_E19_VERSIONED_SERVICE_WIRING.md),
[handoff](docs/roadmap/finqa_gate_e19_current_handoff.md), and
[public evidence](docs/external_datasets/evidence/finqa_service_wiring_public_v2.json).

## 2026-08-03 FinQA Gate E18 admitted evidence to typed context

```text
decision                               E18_ADMITTED_CONTEXT_MECHANISM_PASSED_ROUTE_REMAINS_DISABLED
protocol SHA-256                       e1dabbd79901280e6d666a479d9cac15fda4c408ec2dc1412f148a6541491035
public evidence SHA-256                82595dc7f0f2c119737a0e620bd1c1b8ce12a9c67d8b8a91335c3b0c1eac2747
online rule families                   7 / 7
repeated eligible typed builds         112 / 112
preparation p50 / p95 / max            0.623 / 0.921 / 1.523 ms
secondary retrieval / model calls      0 / 0
enabled admissions / completions       8 / 8
default-off worker calls               0
primary response mismatches            0
duplicate overwrite/delete             0 / 0
residual workers / contexts            0 / 0
frozen gates                           22 / 22
focused E18 tests                      25 passed
related E16-E18 regression             61 passed
full repository                        3025 passed / 29 skipped / 3 warnings
public repository audit                1350 candidates / 0 findings
public content findings                0
standard FastAPI route                 DISABLED_PENDING_VERSIONED_WIRING
E11 service status                     SHADOW_DEFAULT_OFF
internal cohort                        CONSUMED_NOT_ACCESSED
frozen test                            UNTOUCHED
implementation commit                 ecdc3b7a3391d96c5c1587f57def33ae3f1e113a
remote cache repair commit            2a73cbb6ce06d2c872fbfcd5d5cd847121a1a6e6
first remote acceptance               30774647704 / WINDOWS RACE FOUND
GitHub Actions                         30775290120 / SUCCESS / 9m36s
Ubuntu / Windows / container           PASS / PASS / PASS
runtime SBOM SHA-256                    0f93fcc2d3d7cef9dc0470b901ae663de1a0a273cd6b04a939db70a9d79d9b9a
```

E18 closes the next service data-flow gap without re-retrieval. It projects
only `AdmittedEvidenceChunk` objects from the Agent state, rescans their text
with the current Guard, extracts bounded operand candidates, creates a
value-free seven-family online rule skeleton and safe descriptor catalog, then
registers the exact typed resolution before E16 admission. Every non-admitted
outcome discards its context, duplicate registration never overwrites or
deletes the original, and the post-primary wrapper returns the exact same
`AnswerResponse` object.

The standard FastAPI assembly remains unchanged because E16 binds its service
files to historical exact hashes. E19 must perform versioned route/container
wiring and new paired API evidence. E18 does not establish answer quality,
production traffic, arbitrary financial coverage, a latency SLO, or E11
promotion.

Detailed state: [E18 engineering record](docs/external_datasets/finqa_admitted_context_gate_e18.md),
[learning chapter](docs/learning/39_FINQA_GATE_E18_ADMITTED_CONTEXT.md),
[handoff](docs/roadmap/finqa_gate_e18_current_handoff.md), and
[public evidence](docs/external_datasets/evidence/finqa_admitted_context_public_v1.json).
The first remote run retained a Windows cache-race failure as evidence. Repair
commit `2a73cbb6ce06d2c872fbfcd5d5cd847121a1a6e6` then passed
[GitHub Actions run 30775290120](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30775290120)
across Ubuntu, Windows and the Linux container contract. The dependent
readiness/rollback drill passed and the workflow published one bound runtime
SBOM artifact.

## 2026-08-03 FinQA Gate E17 typed eligibility and adapter

```text
decision                               E17_TYPED_ADAPTER_MECHANISM_PASSED_NOT_SERVICE_ENABLED
protocol SHA-256                       d8e3433a2449ff7649b535eba416ced3a2a378b1871a640b2ad0a71508c0ea4d
public evidence SHA-256                3ad830e8ad4bad7b14e6979906e20f06f1e1487defdb48f979edee009915b4af
eligibility reasons                    6 / 6 covered
ineligible worker calls                0 / 5
synthetic outcome mapping              2 / 2 exact
real isolated E11 observations         2 / 2 terminal / both MATCH
first / warm observation               approximately 732.317 / 3.581 ms
E16 background composition             ADMITTED -> MATCH
residual service workers/contexts       0 / 0
adapter model calls                    0
frozen gates                           24 / 24
focused tests                          23 passed
related E12-E16 regression              52 passed
full repository                        3000 passed / 29 skipped / 3 warnings
public audit                           1339 candidates / 0 findings
enterprise primary                     unchanged
E11 service status                     SHADOW_DEFAULT_OFF
internal cohort                        CONSUMED_NOT_ACCESSED
frozen test                            UNTOUCHED
GitHub implementation commit           2e6a882a79e16b740c893eab792035e13d4d67f4
GitHub Actions                         30759155310 / SUCCESS / 9m59s
Ubuntu / Windows / container           PASS / PASS / PASS
runtime SBOM SHA-256                    ddaa5e0cbe3ac7d398561a4c76e14ebea01dd2ffb58054791892daab03937bab
```

E17 implements the missing typed adapter mechanism between the generic E16
owner and E8/E11. It accepts only online-origin value-free skeletons and safe
catalogs from Guard-admitted evidence, rejects gold/oracle fields, binds the
exact question/skeleton/catalog, computes E8 primary inside the adapter, and
uses a bounded TTL consume-once resolver for cross-thread handoff. The normal
service remains OFF because the enterprise Agent still does not produce and
register this typed context. This is not online planner quality, answer
accuracy, production traffic, a latency SLO or serving authorization.

Detailed state: [E17 engineering record](docs/external_datasets/finqa_typed_service_adapter_gate_e17.md),
[learning chapter](docs/learning/38_FINQA_GATE_E17_TYPED_ELIGIBILITY_ADAPTER.md),
[handoff](docs/roadmap/finqa_gate_e17_current_handoff.md), and
[public evidence](docs/external_datasets/evidence/finqa_service_adapter_public_v1.json).
Exact implementation commit `2e6a882a79e16b740c893eab792035e13d4d67f4`
passed [GitHub Actions run 30759155310](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30759155310)
across Ubuntu, Windows and the Linux container contract. The container job
also passed readiness/rollback drills and published one Python runtime SBOM.

## 2026-08-02 FinQA Gate E16 service dark integration

```text
decision                               E16_MECHANISM_GATE_PASSED_DARK_OBSERVATION_REMAINS_DEFAULT_OFF
serving route                          POST /agent/v2/chat
production default                     OFF / 0 basis points
paired local route observations        24 / 24
default-off provider calls             0
primary response/receipt mismatches    0
offer latency p50/p95/max              0.017 / 0.024 / 0.033 ms
controlled residual workers            0
frozen mechanism gates                 17 / 17
focused tests                          28 passed
API/runtime regression                 177 passed
security regression                    245 passed / 6 skipped
external-dataset regression            446 passed
full repository                        2977 passed / 29 skipped / 3 warnings
public audit                           1328 candidates / 0 findings
model calls                            0
FinQA service adapter                  NOT IMPLEMENTED / CONTRACT GAP RECORDED
trusted identity current contract      v3 / 20 of 20 / e21503b0947a5608
implementation commit                  2143ba7f9d0c868926192b064b6a72e95839b3ca
GitHub Actions                         30751922977 / SUCCESS / 10m06s
Ubuntu / Windows / container           PASS / PASS / PASS
```

E16 adds a lifecycle-owned, default-off service dark-observation path with
keyed request sampling, nonblocking bounded admission, independent deadlines,
aggregate-only telemetry and failure-isolated shutdown. It compares actual
FastAPI response bytes and feedback receipts under OFF and controlled local
observation. This is synthetic mechanism evidence, not production traffic,
answer quality, an SLO or E11 serving authorization. The enterprise chat API
does not yet provide E11's typed skeleton, safe descriptor catalog and bound
E8 primary selection. At E16 closeout, E17 still had to freeze and validate
that adapter; the completed E17 mechanism and its remaining service-data-flow
gap are recorded in the current section above.

Public protocol/evidence SHA-256:

```text
56ea7b40e7ec045e30fdedc30d3188475bd181e9321bacbc4e357fe0202037c0
1c997f2431f64b4d3fd158eb7bdf3e90ee4865c920f301612b6b8b1ec9f579f0
```

The first full run exposed one provenance failure in the historical trusted-
identity public result because E16 changed two hash-bound service files. No
identity behavior case differed. The old v2 result remains immutable and
parseable; a new v3 result binds config, dark observation and the current
service sources. It passed 20/20 cases, including 14 denied cases with zero side
effects and zero credential leaks. The second full run passed 2977 tests.
Exact implementation commit `2143ba7f9d0c868926192b064b6a72e95839b3ca`
then passed [GitHub Actions run 30751922977](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30751922977)
across Ubuntu, Windows and the Linux container contract. The container job also
passed rollback/readiness drills and published one Python runtime SBOM.

## 2026-07-30 FinQA Gate E2 typed-contract calibration

```text
claim label                              DISCLOSED_DEVELOPMENT_CALIBRATION
frozen split                             60 calibration / 40 internal validation
internal validation                      NOT RUN
B2-v2                                    NOT RUN
best iteration                           v2.2 host-compiled sketch
B0 / v2.2 strict accuracy                51.67% / 26.67%
B0 / v2.2 grounded accuracy              43.33% / 25.00%
v2.2 coverage                            81.67%
v2.2 mean / p95 latency                  2.19s / 3.38s
v2.2 correct-to-wrong / wrong-to-correct 20 / 5
prevented operand-selection failures     3
decision                                 CALIBRATION_REJECTED
public evidence                          VERIFIED / 12 historical source files
raw public fields                        0
```

Gate E2 improved the typed architecture but did not pass adoption gates. The
frozen test remains untouched. The next bottleneck is retrieval/candidate
availability, table-level scale propagation, percentage normalization, and a
bounded policy for host-controlled constants.

更新时间：2026-07-28（引用链 fail-closed 收尾已实现；R2-S8 真实双人审核仍 NOT RUN）

当前最新阶段是 R2-S8 independent quality evidence。项目新增不可覆盖的
模型/机器结论盲化且参考答案引导的 packet、匿名且严格的双人 submission、
分歧/第三人裁决、人工检索
`0/1/2/uncertain` 相关性、agreement/kappa、人工
precision@5/recall@5/nDCG@5、
答案接受率，以及从原始标签重算 summary 的 evidence verifier。可选 LLM
judge 只能在固定模型/prompt/config 下进行至少 3 次 trial，并对照人类共识
校准；其 `security_gate_authority=none`、`release_authority=false`。
tracked 12 题 dev packet 位于
`data/v2/quality_review/r2-s8-calibration-v4/`，明确是
`public_synthetic / not_independent / NOT_RUN`。G5 需要两名真实独立人员，
Codex 没有填充标签。R2-S8 G0-G4 当时的 exact working tree 通过
`2381 passed / 29 skipped / 3 warnings`，公开审计为 `892/0`。这是进入本次
引用收尾前的 R2-S8 历史基线，不是当前候选结果。

## 面试前引用链 fail-closed 收尾

Generation V2 现在只把模型结果视为 candidate claims，不再直接返回
`generated.answer`。宿主程序先执行 visible citation、最低词汇支持、阿拉伯
数字、金额/百分比、日期/状态和常见否定方向检查，然后只用 supported claims
重建 `answer/claims/citations/sources`。任何 unsupported claim 都会被过滤，
不论模型把它标成 critical 还是 non-critical；部分失败返回 `partial /
partial_evidence`，全部失败则仅用 Guard 已准入的可见证据构造 extractive
partial fallback。

这是一道确定性 grounding gate，不是 semantic entailment certification，
不能声称彻底防止 hallucination。默认 V2 controller 当前逐 required aspect
选择 `search`，completeness 可以选择 `open`；`find` 有工具和安全边界但默认
策略不会主动选择，也没有自动 query rewrite/retry。R2-S8 真人双评仍为
`NOT RUN`。R2-S9 单主机 Linux deployment contract 已完成，但真实 staging
和 production 仍为 `NOT RUN`。

本次候选的当前本地证据是：citation/generation 目标测试 `31 passed`，
Agent 与 evaluation 相关回归 `1113 passed / 16 skipped`，frozen
deterministic test `28/28`，全量 `2428 passed / 30 skipped / 3 warnings`，
`pip check` 无冲突，`compileall` 通过，公开审计
`918 candidates / 0 findings`。这些是本地自动化合同，不是人工质量认证、
生产准确率或无安全漏洞证明；当前精确提交的远端 CI 尚未运行。

Historical accepted baseline marker: R2-S6 versioned corpus expansion.

当前状态：知识库默认 profile 已从 72-document `demo` 切换为
240-document `expanded`。事实宽度从 8 policies / 16 versions / 32 facts
扩展到 20 / 40 / 104，其中 52 条为 active facts，覆盖 12 个部门。真实
BGE-M3 fixed index 已构建并激活为
`20260724T024653Z_expanded_bge_m3_fixed`：240 source / 216 canonical /
216 chunks。live dev 48/48、冻结 test 56/56 通过，ACL leakage 为 0，
hit@1 和 document-recall@3 均为 1.0。2,000-document
`expanded_benchmark` 已完成生成和 parser/dedup/chunk dry run，得到 1,225
canonical chunks，但未嵌入或激活。公共证据位于
`data/v2/public/corpus_expansion_v2/`。

前一阶段 R2-S5 已把 `/agent/v2/chat` 的调用方自报身份替换为服务端
RS256/JWKS 验签身份；chat、feedback、metrics、trace 均进入可信身份与角色边界。
feedback 由服务端 receipt 绑定 actor、目标回答和精确内容，SQLite 仅保存 keyed
digests，并对同 actor/target/content 原子保留最新 rating。本地身份工具具备
manifest commit point、journal recovery、stage/restart/activate、持久化强制
overlap/retire、break-glass 审计和跨平台私有文件约束。

第三轮独立复审的 `0 Critical / 10 Important / 4 Minor` 是历史 `HOLD` 输入。
随后两名最终候选 reviewer 又发现 `0 Critical / 7 Important`：请求流资源上限、
journal 完成态语义、API mode 文档、证据一致性、benchmark 门禁、credential
审计盲区和身份披露合同。七项修复后的安全复核达到 `0/0`，工程复核仍发现
`0 Critical / 2 Important`：credential safe-marker 碰撞，以及 malformed body
公开合同/零副作用测试不完整。二者连同三个文档 Minor 和超长数字
`Content-Length` 的未捕获异常均已修复。工程复核随后达到 `0/0`；安全复核又
发现占位词虽有边界、却仍可出现在凭据中间的 `1 Important`。该问题已按整值
占位符语法修复。最终安全与工程 reviewer 均返回
`0 Critical / 0 Important / RELEASE`，因此实现曾进入本地发布候选；这不代表
生产部署。精确提交 `d753df3` 的 GitHub Actions #17 随后按预期阻止发布：
Ubuntu 为 `1 failed / 1910 passed / 15 skipped`，Windows 为
`5 failed / 1918 passed / 3 skipped`。根因是错误消息断言与真实祖先路径错误
不一致、Windows `RUNNER~1` 与长路径的同目录字符串误判，以及 CI 没有仓库内
`.venv`。三项均已修复并补回归。新聚焦 RED/GREEN 为 `14 passed`，更宽的
身份边界、公共审计与脱敏回归历史候选为 `127 passed`；本次受影响合同组为
`151 passed / 4 skipped`。随后复审发现并阻断了目录 TOCTOU、错误对象权限
副作用、POSIX FIFO 阻塞、Windows owner 策略和 token handle 清理问题；修复后
限定复审为 `0 Critical / 0 Important / 0 Minor / RELEASE`。
benchmark `4 passed`、公共审计基线 `515/0`，
source-bound p95 `0.0904 ms`。Source-bound matrix v2 再次通过 `20/20`，
候选/公开 SHA 为 `0258f8c2...0829`，合同 ID 为
`trusted-identity-contract-7c183871488a6519`，并显式绑定
`app/security/private_fs.py` 在内的 11 个 source。最新完整工作树通过
`1918 passed / 22 skipped / 3 warnings`。修复提交
`11892531451750609f44138b7348f16b9b1316ff` 的 GitHub Actions #18 已通过：
Ubuntu 为 `1918 passed / 22 skipped / 4 warnings`，Windows 为
`1935 passed / 5 skipped / 4 warnings`，两边公开审计均为 `515/0`。

边界：这是本地可复现的资源服务器信任合同，不是真实 IdP、SSO、OIDC
discovery、revocation、HSM/KMS 或生产 IAM。验签微基准不是 HTTP/RAG/LLM
端到端延迟。S2-2 independent holdout、semantic judge calibration、human
double review、production traffic 和 deployment 仍为 `NOT RUN`。

历史 R2-S4 结果继续有效：同一可见 synthetic dev cohort 上 Qwen2.5/Qwen3 的
12 个决策安全/效用观察一致，`release_pass=false`，不代表跨模型泛化。R2-S1
V0-V5、R2-S3 和 E1-E7 证据均保留为历史基线，不与当前 R2-S5 数字相加。
本文是唯一当前状态入口；`docs/PROJECT_STATUS.md` 与
`docs/AGENTIC_RAG_EVOLUTION_LOG.md` 只保留历史。

Historical compatibility markers: R2-S1 V0-V5 and V1-V5 remain preserved.
Historical R2-S4 evidence retains `component deterministic threshold diagnostic=false`, `cross-model non-release diagnostic passed=true / release_pass=false`, and exact-run pre-gate audit 473/0.
Task8 docs wave audit 483/0; final delivery evidence is established by exact-HEAD gates, Git, and GitHub Actions.
Historical R2-S3 closeout evidence remains focused `457 passed / 10 skipped / 3 known warnings`, full `1395 passed / 13 skipped / 3 known warnings`, and public audit `454 candidates / 0 findings`; none is a current R2-S5 gate.

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
- R2-S5：新增严格 RS256/JWKS verifier、服务端 Principal 到 Agent `UserContext` 的确定性映射、public-by-exception user/operator 路由授权、认证先于 bounded body parsing、后台可执行 readiness、receipt 绑定的 keyed feedback、幂等隐私迁移和 WAL erasure marker、v3 manifest/journal 驱动且强制 overlap 的本地身份生命周期、分离且回环限定的 UI/load credential 通道，以及 20-case 冻结身份评测。
- R2-S6：保留 facts v1 和历史 72/600 profiles，新增 facts v2、
  `expanded/expanded_benchmark`、共享 profile catalog、active-fact
  deterministic support/eval coverage、20 项 corpus quality gate、动态完整性问题
  数量、索引 CLI/default 接入、Ubuntu/Windows CI 门禁和可篡改检测的公共证据
  包；本地真实 BGE-M3 index 与 104-case dev/test retrieval regression 已通过。
- R2-S7：实现安全 source event、staging/quarantine、EML/附件预算、
  revision/tombstone/change plan、精确 chunk/embedding 失效复用、完整不可变
  target snapshot、故障注入、原子激活、删除验证与回滚；最终生命周期性能证据
  10/10 等价且 10/10 增量更快，embedding call ratio 约 0.02547。
- R2-S8 G0-G4：实现模型/机器结论盲化、参考答案引导的质量证据、双人独立
  标签、分歧裁决、人工检索与
  回答指标、阈值化 fail-closed 结论、可重算 evidence bundle 和 LLM judge
  calibration contract。真实 human double review 与 semantic judge
  calibration 仍为 `NOT RUN`。

## 3. 当前证据

### R2-S6 当前知识库证据

```text
facts schema                         enterprise_facts_v2
policies / versions / facts          20 / 40 / 104
active facts / departments           52 / 12
expanded source / canonical / chunks 240 / 216 / 216
expanded benchmark parsed chunks     1,225
live dev                             48/48; ACL leakage 0
frozen test                          56/56; ACL leakage 0
test hit@1 / document recall@3       1.0 / 1.0
index manifest SHA-256               69b9fb7d3008467f65fb2920a621e9812cdb59c4919834819333e0e33b866507
local full pytest                     1942 passed / 22 skipped / 3 warnings
public repository audit               534 candidates / 0 findings
remote CI run                         30065782695 / Ubuntu success / Windows success
```

这组结果只证明当前 synthetic fact model、生成器、解析/去重/索引和本地
retrieval contract。人工语义 review、真实企业语料、独立领域 holdout 和生产
freshness/SLO 仍未完成。完整过程见
[R2-S6 Engineering Journal](docs/corpus/v2_expansion/01_engineering_journal.md)。

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
real-model v2 run at V5 closeout             NOT RUN
```

V5 对固定 cohort 计算 `sha256(case_id)`，按 `(case_hash, case_id)` 排名后以 rank 奇偶交替分配 arm order。真实调用顺序由 plan 控制，OFF/ON 结果数组仍按 dataset 对齐供现有指标计算。`LivePairedResultV2` 和 `LiveSecurityRunManifestV2` 与 v1 显式分离；writer 拒绝 v1/v2 混用，并逐行核对 arm position 与 guard mode。

本轮没有重新执行 Qwen/BGE-M3 正式实验，因此没有新的 0/24 或 utility 数字。正式 `r2-s1-d7-test-20260718-01` 继续标记为 fixed OFF-first observational run，manifest SHA-256 仍为 `5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e`。详细算法、RED/GREEN、两类顺序的区别、实现错误修正和面试问答见 [V5 Engineering Journal](docs/security/r2_s1/15_v5_counterbalanced_arm_order_engineering_journal.md)。

V0-V5 完成后又进行一次独立 closeout review，结果为 `0 Critical / 6 Important / 2 Minor`。6 个 Important 均已补成 RED/GREEN 回归测试并修复；2 个 Minor 中，process-local 网络边界和独立验证不足被保留为明确限制及 R2-S2 准入项。最终本地证据为 180 个聚焦跨模块测试、921 个全仓测试、415 个公开候选文件零命中、仓库内与隔离 8-file verifier 均通过。完整问题、代码位置、根因、修复和下一阶段安排见 [V0-V5 Closeout Review](docs/security/r2_s1/16_v0_v5_closeout_review_and_improvement_plan.md)。

### R2-S2 S2-1 真实模型反平衡 dev replication

新运行 `r2-s2-s1-dev-20260719-01` 使用 V5 的 `stable_case_hash_rank_counterbalanced_v1`，36 个 case 精确分配 OFF→ON `18`、ON→OFF `18`，共保存 72 个真实 arm execution events。运行入口 Git HEAD 为 `073d7356026954c26c1429fb9faddc5e9a5dcb87`，manifest SHA-256 为 `3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e`；模型错误与被阻止外联均为 0。

结果必须按两层分母解释：ON 对已经到达 Guard 的攻击单元隔离 `15/15`，说明当前 detector 对这次实际输入的 conditional recall 为 100%；但 28 个已标注攻击单元中只有 15 个进入 Guard，因此 end-to-end all-labeled quarantine 仍为 `15/28`。另外 13 个是 retrieval/tool exposure 的 `unreached`，不是 Guard 看见后放行的 false negative。OFF→ON 的 user-boundary attack success 为 `3/24 -> 0/24`，model-context exposure 为 `7/24 -> 0/24`，clean utility 保持 `12/12`，benign quarantine 为 `0/32`。完整逐项解释见 [S2-1 Live Dev Results](docs/security/r2_s2/01_s2_1_live_dev_results.md)。

真实运行还暴露了一个证据分类缺陷：legacy `unit_outcomes` 只有 `admitted/quarantined`，导致 immutable run-01 的 `failures.csv` 把 13 个未到达单元写成 `attack_unit_admitted`。旧 artifact 不覆盖；writer 已用 v2 observation 的 reached/quarantined 计数为未来 artifact 区分 `attack_unit_unreached` 与 `attack_unit_missed_by_guard`，并新增私有 run 独立复算和 arm-position 分层 CLI。修复过程见 [R2-S2 Engineering Journal](docs/security/r2_s2/02_engineering_journal.md)。

### R2-S2 S2-2 独立 holdout 冻结基础设施

仓库已经实现 holdout 的 DRAFT→FROZEN 阶段，但没有由开发者自己生成一个数据集冒充“独立验证”。冻结器要求至少 36 个 case、24 attack、12 benign hard negatives、8 类攻击族、5 个 source surfaces、英中双语、两个不同 reviewer ID 和四项 separation attestation；manifest 绑定三个输入文件的 bytes/hash、case identity、coverage、Git HEAD/branch/clean tracked tree，以及 Guard、live evaluator 与 freezer 的代码 SHA-256。原始目录 `holdout_submissions/` 同时被 `.gitignore` 和 public audit forbidden-prefix 保护。协议详见 [Holdout Freeze Protocol](docs/security/r2_s2/00_holdout_freeze_protocol.md)。

### R2-S3 measurement-only exposure ablation

R2-S3 只测量、不改变执行路径。accepted private run `r2-s3-dev-exposure-20260721-04` 使用 `indirect_injection_exposure_run_manifest_v2`，绑定未重跑的 source run `r2-s2-s1-dev-20260719-01` 及其 manifest SHA-256 `3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e`；private exposure manifest SHA-256 为 `4c8cfb6ad826fc1ca9c24afb0157129df661f3cd463aa3448ec161c0608c5f1f`，canonical evaluator `app/evaluation/indirect_injection_exposure.py` SHA-256 为 `d7fe9332953cc44ba3f517bb03d4074b293b821461240d30fc384d67256a4b88`。tracked public package 使用 `indirect_injection_exposure_public_manifest_v2`，redacted manifest SHA-256 为 `09fda4aa81d15757e8de7cadec32e057a1c01d23a5b646dbcd5c0f9ae9038033`，packaged verifier SHA-256 为 `dbe814605220058c0bf2453ee1cac0450253bd788b64f9979ab1eb77c2413897`。production Guard、retrieval、Agent、prompt、`top_k`、`candidate_k` 和 ranking 均未修改；`r2-s3-dev-exposure-20260721-01`、`r2-s3-dev-exposure-20260721-02` 与 `r2-s3-dev-exposure-20260721-03` 仅为 superseded local history。`-03` 与 `-04` 的 private `summary.json` 和 `per_unit.jsonl` bytes 完全相同。

严格 replay 与 actual live aggregates 相等：live/replay Guard reach `15/28`，quarantine `15/28`，conditional quarantine `15/15`。13 个 unreached units 全部位于 runtime rank 2，13 个相关 case 的 controller/ledger/model-context/verifier/response/action/egress/attack-success downstream exposure 为 observed `0/13`。counterfactual search reach 在 depth `1/2/4` 为 `6/26 -> 22/26 -> 26/26`，total reach 为 `15/28 -> 28/28 -> 28/28`，额外 scan units/chars 为 `0/0 -> 29/3845 -> 33/4200`。这些 coverage/cost 只是 deterministic diagnostic，不是已执行 production behavior 或 wall-clock latency。

结论是 `NO_CURRENT_BYPASS_OBSERVED`：当前 dev evidence 不准入 production prefilter/retrieval 改动。它不是 release pass，也不证明 universal prompt-injection safety。协议、结果和完整 RED/GREEN 日志见 [R2-S3 Protocol](docs/security/r2_s3/00_exposure_ablation_protocol.md)、[R2-S3 Results](docs/security/r2_s3/01_results.md) 与 [R2-S3 Engineering Journal](docs/security/r2_s3/02_engineering_journal.md)。

R2-S1 V1-V5 与收口修复提交 `9fcb3041ae3561057e1b56d881e91aab8aee0dce` 已推送到 `origin/codex/rag-eval-system`；对应 [GitHub Actions run 29682474913](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/29682474913) 在 Ubuntu/Python 3.11 上为 `success`。该结果是功能分支 CI 证据，不代表已经 merge、部署或完成 owner-only 验收。

### GitHub 交付与远端复现

历史 E7 代码候选 `9607e55ec0fc12e98d1f61e199bfbf6ac12a0eee` 已推送到 `origin/codex/rag-eval-system`。第四个全新 GitHub clone 得到 frozen hash exact、compile exit 0、public audit 331/0、full pytest 574 passed。Ubuntu/Python 3.11 的 [GitHub Actions run 29553278709](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/29553278709) 为 `success`。这些证据只覆盖该历史 commit，不代表已 merge、部署或达到生产 SLO；它与后续 `9fcb304` 的历史 CI 均不覆盖当前 R2-S5 candidate exact HEAD。

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

- Retrieved-content indirect prompt injection：D1-D7、V1-V5、R2-S2 S2-1、R2-S3 measurement-only exposure ablation 和 R2-S4 cross-model dev observation 已完成批准范围。R2-S4 只证明两种冻结模型在同一 visible synthetic dev cohort 中 12 decision safety/utility observations matched，decision 为 `CONSISTENT_OBSERVATION` 且 `release_pass=false`；model calls/errors/egress 也相同，latency 不同且不参与 decision。现有证据仍只覆盖可见、固定、合成文本攻击；独立 holdout、多模态、人工红队、未知绕过、production traffic 和 cross-model generalization 仍未证明。
- R2-S2 independent validation：counterbalanced real-model dev replication 已运行；holdout freeze/verify 基础设施已实现。独立 reviewer 原始 package、冻结 manifest、一次性 holdout 模型运行、双人盲评、agreement、semantic judge calibration 与 human double review 均为 `NOT RUN`。
- Optional reranker：`NOT RUN`，没有 admitted reranker。
- Human semantic review：`NOT RUN`；50 行表仍为空，等待本人判断。
- Owner code experiments and oral defense：`NOT RUN`；Codex 不能代替本人完成。
- GitHub remote CI：历史提交 `9607e55` 与 `9fcb304` 的对应 run 已通过；各自只证明该 feature-branch commit 的 Ubuntu CI，均不覆盖当前 R2-S5 candidate exact HEAD，也不外推为 branch protection、部署或生产验收。
- 当前 ACL 使用服务端验签 `Principal` 派生的 `UserContext`，但身份源仍是本地模拟而不是真实 IAM；数据全部 synthetic；本地 load 不是生产吞吐/SLO。
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
- R2-S2 独立 holdout 冻结协议：[Holdout Freeze Protocol](docs/security/r2_s2/00_holdout_freeze_protocol.md)
- R2-S2 S2-1 真实模型结果：[S2-1 Live Dev Results](docs/security/r2_s2/01_s2_1_live_dev_results.md)
- R2-S2 逐步工程日志：[R2-S2 Engineering Journal](docs/security/r2_s2/02_engineering_journal.md)
- R2-S3 exposure ablation 协议：[R2-S3 Protocol](docs/security/r2_s3/00_exposure_ablation_protocol.md)
- R2-S3 exposure ablation 结果：[R2-S3 Results](docs/security/r2_s3/01_results.md)
- R2-S3 逐步工程日志：[R2-S3 Engineering Journal](docs/security/r2_s3/02_engineering_journal.md)
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

D3 detector 位于 `app/domain/retrieved_security.py` 与 `app/security/retrieved_content.py`；D4 admission 与强制接入位于 `app/security/retrieved_admission.py`、`app/retrieval/pipeline.py`、`app/agent/tools_v2.py` 和 `app/agent/controller_v2.py`；D5 prompt/service/trace lifecycle 位于 `app/agent/generation_v2.py`、`app/agent/runner_v2.py`、`app/main.py` 和 `app/runtime/resources.py`；D6 deterministic evaluator 位于 `app/evaluation/indirect_injection_*.py`；D7 live index、runner、artifact writer 和 CLI 分别位于 `app/evaluation/indirect_injection_live_index.py`、`app/evaluation/indirect_injection_live_runner.py`、`app/evaluation/indirect_injection_live_writer.py` 与 `scripts/eval_indirect_injection_live.py`；V2 scan provenance 横跨 `app/domain/retrieved_security.py`、`app/security/retrieved_admission.py` 和两套 indirect-injection runner；V3 exact boundary 位于 live runner 的 `_ExactLoopbackOriginPolicy` 与 `LocalOllamaOnlyBoundary`；V4 semantic registry 位于 `app/evaluation/indirect_injection_metric_semantics.py`；V5 arm-order contract 位于 `app/evaluation/indirect_injection_arm_order.py` 并由 live runner/writer/CLI 接入。当前可以准确表述为：“固定 synthetic frozen test 上，deterministic OFF/ON 证明 known attack propagation 从 21/24 降至 0/24；历史 D7 与 S2-1 dev replication 的真实 BGE-M3 + Qwen2.5:3b 成对观察中，OFF 均出现 3/24 user-boundary raw signal，ON 均为 0/24；S2-1 已按 actual scan events 验证 ON reached attack units 15/15 隔离、0/32 benign units 被误隔离，但 all-labeled 分母仍为 15/28，13 个 unreached 暴露出检索/工具覆盖问题；V3 是 evaluator 进程内的 exact local origin/socket 边界，不是 OS sandbox；holdout 冻结工具已实现，但独立数据和结果不存在。”不能表述为未知攻击免疫或生产安全保证。

## 9. R2-S2 当前状态

```text
S2-1 preflight and new run ID                  COMPLETE
S2-1 BGE-M3/Qwen counterbalanced dev run       COMPLETED WITH OBSERVATIONS
S2-1 36 cases / 72 arm events                  VERIFIED
S2-1 OFF->ON / ON->OFF                         18 / 18
S2-1 ON conditional / all-labeled quarantine   15/15 / 15/28
S2-1 future failure taxonomy                   UNREACHED vs MISSED FIXED
S2-2 holdout strict contracts                  IMPLEMENTED
S2-2 freeze/verify operator CLIs               IMPLEMENTED
S2-2 raw-package leak prevention               IMPLEMENTED
independent reviewer package                   NOT CREATED
independent holdout model run                  NOT RUN
blind double review / agreement                NOT RUN
semantic judge / cross-model replication       NOT RUN AT R2-S2 CLOSEOUT
historical R2-S2/R2-S3 full regression only    1395 PASSED / 13 SKIPPED / 3 KNOWN WARNINGS; not a current R2-S4 HEAD gate
historical R2-S2/R2-S3 public audit only       454 CANDIDATES / 0 FINDINGS; not a current R2-S4 HEAD gate
historical compileall / pip check only         CLEAN / CLEAN; not a current R2-S4 HEAD gate
```

下一步不能由当前 Guard 开发者代替独立 reviewer 编写攻击 payload。正确交接是：独立人员按冻结协议创建 `holdout_submissions/<submission-id>/`，在 clean tracked Git baseline 上 freeze 并由另一 reviewer 核验 manifest；只有 freeze 后才实现一次性 evaluation adapter。若 holdout 失败，只能把失败类型带回新的 dev regression，不能反复查看同一 holdout 调规则后继续称其未见。

## 10. R2-S3 当前状态

```text
R2-S3 measurement-only exposure ablation       COMPLETE
historical R2-S3 source live run               UNCHANGED / VERIFIED; not a current R2-S4 gate
production Guard / retrieval / Agent           UNCHANGED
actual live / replay Guard reach                15/28 / 15/28
conditional quarantine                          15/15
rank-2 unreached downstream exposure             0/13 OBSERVED
counterfactual search reach d1/d2/d4             6/26 / 22/26 / 26/26
counterfactual total reach d1/d2/d4             15/28 / 28/28 / 28/28
counterfactual production execution             NOT RUN / DIAGNOSTIC ONLY
independent holdout                              NOT RUN
semantic judge / cross-model replication        NOT RUN AT R2-S3 CLOSEOUT
historical R2-S3 focused / full pytest           457 passed / 10 skipped / 3 warnings; 1395 passed / 13 skipped / 3 warnings; not a current R2-S4 HEAD gate
skip qualification                               platform-dependent symlink/junction variants unavailable on this host
historical R2-S3 compile / pip / public audit   CLEAN / CLEAN / 454 candidates / 0 findings; not a current R2-S4 HEAD gate
historical R2-S3 source/private/public verifier VERIFIED; not a current R2-S4 gate
frozen hash comparisons                         EXACT
push / remote CI                                 Push is allowed only after fixed-HEAD reviews and local gates pass; actual delivery and CI state are established by Git and GitHub Actions.
```

`NO_CURRENT_BYPASS_OBSERVED` 只表示当前冻结 dev observation 没有为 production retrieval/prefilter change 提供准入证据。它不能写成 release pass、universal safety result 或 production deployment approval。

## 11. R2-S4 当前状态

```text
cross-model plan / V3 components / matrix      COMPLETE WITH OBSERVATIONS
run code HEAD                                  109e8b52d8d31ae3562420351451a69915652be3
run tree                                       6b54e1f3c94b031a9438d21fd6e88a8c6d78faa8
plan SHA-256                                   85175b88742d28b09431e1b1df35a27db5cd65fbd96fc33db0bcfd899efd4152
controller wall time                           270.2s
matrix decision                                CONSISTENT_OBSERVATION
matrix reason                                  complete_equal_security_and_utility_observations
baseline component manifest                    9271ec53e0b69d827e7a624e3666e6e53a5a9e7738450542a89e5903de768f44
replication component manifest                 0495450e5134acadc564fe1ddd805f096ad939c27f2568c80caa49b366e7ed01
matrix manifest                                ec7b2fb6b8802b32d50933fc34b574d55c370dd88dbee4a88239d37ac51ff0b5
public R2-S4 package                           VERIFIED / 8 FILES
public manifest SHA-256                        0978131eaf1c0059a598648f3f67ea07b5144a110467728ada852bdbbfe61813
packaged verify.py SHA-256                     9fe95165252e73355b54e2b802596e5cb00e71cf8190e4afe865011e83c7ed9b
non-release diagnostic                         passed=true / release_pass=false
visible synthetic dev cohort                   ONLY; not cross-model generalization
focused / full exact-run gates                 367 passed / 4 skipped; 1644 passed / 16 skipped
compile / pip / exact-run pre-gate audit       CLEAN / CLEAN / 473 candidates / 0 findings
Task8 docs wave audit                          483/0; final delivery evidence is established by exact-HEAD gates, Git, and GitHub Actions
pre-run exact-HEAD review                     0 Critical / 0 Important / 0 Minor
independent holdout                            NOT RUN
semantic judge calibration                     NOT RUN
human double review                            NOT RUN
production traffic                             NOT RUN
real IdP                                       NOT RUN
deployment                                     NOT RUN
```

exact-run pre-gate audit 473 candidates / 0 findings.

本轮先修复证据系统而不是先跑模型，因为一旦 `-01` immutable target 被不完整代码占用，就不能删除目录后假装是同一次实验。门禁通过后，one planned R2-S4 cross-model run has already executed under the frozen plan; no rerun or overwrite of the immutable R2-S4 run IDs is allowed. Task9 final gates, push, and CI are external delivery evidence rather than another model run or overwrite of immutable model evidence。

## 12. FinanceBench 真实文档外部评测轨

完整工程记录见
[`docs/external_datasets/financebench_results.md`](docs/external_datasets/financebench_results.md)。

```text
upstream revision                 cc39aeb4afdf33909ee1412188bf89035950c2eb
public questions / PDFs           150 / 84
company-grouped dev / frozen test 49 / 101; company overlap 0
PDF parser                        pypdf 6.14.2
heading chunks                    29,335
BGE-M3 vectors                    29,335 x 1,024
embedding batches                 937 computed / 0 corrupt recompute
index manifest SHA-256            7eae87f4c9ab670a1f10838f553fe2a0a7b53c0ef2958ff950101e7b8305be01
dev baseline Recall@5             79.59% (39/49)
dev entity-scope v5 Recall@5      100% (49/49)
dev v5 MRR / nDCG@5               94.56% / 95.97%
dev baseline / v5 mean latency    743 ms / 799 ms
dev v5 ACL leakage                0
dev selected Page Hit@5           48.98% (24/49)
dev complete Page Recall@5        38.78% (19/49)
dev macro Page Recall@5           43.88%
dev page embedding calls          98
frozen test document Recall@5     95.05% (96/101)
frozen test Page Hit@5            30.69% (31/101)
frozen complete Page Recall@5     24.75% (25/101)
answer generation/scoring/review  NOT RUN
```

本阶段增加了受字符与条数双预算约束的 Ollama 批量 embedding、模型/语料/chunk
指纹绑定的原子 `.npy` 分片缓存、损坏批次重算、D 盘 jieba runtime cache、
语料元数据生成的实体 alias 目录，以及 exact-year + entity-history 双 scope。
`search_many` 只在单个逻辑请求内共享 query embedding、FAISS 全局结果和 BM25
scores，不跨用户持久化查询。页级 evaluator 进一步发现：找对文档不等于找到
证据页；当前主要短板是文档内页面排序。49/49 是 dev 文档级检索结果，24/49
是 dev Page Hit@5。冻结 test 的 96/101 文档召回和 31/101 Page Hit@5 单独
报告，三者均不得表述为答案生成或生产准确率。
