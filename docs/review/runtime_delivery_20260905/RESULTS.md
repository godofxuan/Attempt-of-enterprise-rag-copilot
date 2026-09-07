# Runtime correctness delivery: results and limits

Status: LOCAL_EVIDENCE_COMPLETE; final release verification and cross-task
receipts are tracked in EXECUTION.md. This is a bounded portfolio service,
not a production certification or a claim that every answer is correct.

## Decision

- Global default remains `hybrid_default`, without a CUDA requirement.
- `safe_dense_raw20_bge` is an implemented, explicit GPU serving option through
  `app.serving:create_app`, not merely an offline ranking script.
- `safe_dense_raw50_bge` remains an opt-in retrieval experiment. It has no
  post-repair service confirmation and is not promoted from Recall alone.
- No additional model, framework, always-on rewrite, parser or vector selector
  was introduced. The finite main-request budget is exhausted: 680 requests,
  plus 35 separately counted warmups and 60 resource probes.
- No new independent generalization claim or human answer-accuracy claim is
  justified. Known semantic failures and the flawed conflict acceptance fixture
  stay visible and counted, rather than disappearing from the denominator.

## Exact execution identities

| Run | Business source | Status and scope |
|---|---|---|
| Retrieval B v2b | dirty development tree, exact per-file hashes in retrieval evidence | 800 query/config rows; consumed WixQA cohort |
| Service C v1 | `d27c0f8a68830fd74bbb983567e8b4d50967c0ae` plus recorded dirty app tree | 360 main + 15 warmup + 36 resource requests |
| Service repair v1 | `c33484c93eebe242478cc7354cdbf087392ba12f`, clean at start | 240 main + 10 warmup + 24 resource requests |
| Readiness confirmation v1 | `0bca9534fd0cf9d4b02d65c1c46de1a8fec67a4f`, clean at start | 80 main + 10 warmup requests; one round per profile |

[manifest.json](manifest.json) binds actual input/output bytes, application
files, harness, model digests, pinned reranker files, settings and hardware.
Public records are a later export, not a fabricated clean SHA for the earlier
dirty run. All runs verified unchanged application/harness bytes during
measurement. Documentation/export-only work can make the final Git status
dirty without changing those execution bytes; both statuses are retained.

Original SERVICE_PROTOCOL.json input used Windows CRLF bytes. Git publishes
LF under .gitattributes: the input hash is not interchangeable with a Git-blob
hash. The two follow-up protocols were frozen separately; none changes the
40 questions, expected facts, index manifests, models or response deadline.

## Retrieval results

Same 200 consumed WixQA ExpertWritten questions, original BGE-M3 embeddings,
ACL-filtered adapter and application admission before cross-encoder scoring:

| Profile | Macro Recall@5 | Hit@1 | nDCG@5 | MRR@5 | All-gold@5 | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| Hybrid | 56.00% | 33.50% | 45.07% | 44.12% | 48.50% | 411.41 |
| Dense | 65.92% | 35.50% | 52.08% | 49.97% | 59.50% | 335.58 |
| Safe raw20 BGE | 72.25% | 44.50% | 59.20% | 58.01% | 65.50% | 333.94 |
| Safe raw50 BGE | 74.25% | 44.00% | 59.93% | 58.40% | 67.50% | 754.46 |

Dense -> raw20 is +6.33 percentage points; Dense -> raw50 is +8.33.
These times exclude shared query embedding and startup. One observation per
query/config, rotated arms, desktop conditions: not a chat/API SLA, not proof
that reranking is intrinsically faster than Dense. Hybrid per-document limits
differ from Dense profiles, so this is a profile comparison, not a pure
single-variable ablation. Full setup, abandoned attempts and hashes:
[RETRIEVAL_RESULTS.md](RETRIEVAL_RESULTS.md). All 800 per-query/config metrics
and their aggregate arithmetic are public in
[retrieval_evidence.json](retrieval_evidence.json), without question/document
text. The export verifies sums and quantiles, not independent gold semantics.
The abandoned runs total 267 + 7 rows; including 800 completed rows there were
1074 attempts, seven above the amended 1067 cap. That execution deviation is
retained explicitly, not folded into a claim of one flawless 800-row run.

Historical 66.42/72.50/74.50 results use another admission protocol. They remain
historical evidence; do not substitute them into this new comparison.

## Real service results

Actual local Ollama, RS256 JWT verification, production API/controller/tools,
real BGE-M3 embeddings and pinned BGE reranker. Chat: `qwen2.5:3b`; readiness
also verifies configured `qwen3:8b`, which is not an always-on answer judge.
Temperature 0, no model seed supplied; fresh security nonces and observed
generation variation mean repeated answers are not bitwise deterministic.

The acceptance set is 40 synthetic scenarios over 29 documents, including
three CSV tables and three immutable snapshots. Some lifecycle questions are
related repetitions. It is not an external enterprise accuracy dataset.

| Run/profile | Complete automatic contracts | Mean ms | p50 ms | p95 ms |
|---|---:|---:|---:|---:|
| Baseline Hybrid | 85/120 (70.83%) | 914.33 | 920.20 | 1148.13 |
| Baseline raw20 | 90/120 (75.00%) | 910.58 | 930.80 | 1073.80 |
| Baseline raw50 | 87/120 (72.50%) | 911.35 | 942.64 | 1062.33 |
| Repair Hybrid | 87/120 (72.50%) | 946.21 | 927.90 | 1394.52 |
| Repair raw20 | 96/120 (80.00%) | 1021.11 | 945.29 | 1624.63 |
| Final readiness Hybrid, one round | 32/40 (80.00%) | 840.50 | 905.74 | 1372.47 |
| Final readiness raw20, one round | 31/40 (77.50%) | 847.13 | 934.50 | 1227.20 |

Client times include failed requests, actual embedding/generation and tool
work. They exclude application startup. ASGI TestClient measures an in-process
API, not network transport or a deployed SLA. Main rows also retain first-call
model reload costs in later blocks, rather than removing slow observations.
[metrics.csv](metrics.csv) separates complete, failed and all rows, and separates
warmup/resource requests from main requests. Empty subsets have blank latency,
not zero or a fabricated 100% score.

Paired before/repair changes across the same case/repeat IDs:

- Hybrid: 77 retained, 10 gained, 8 regressed, 25 missed; net +2/120.
- raw20: 85 retained, 11 gained, 5 regressed, 19 missed; net +6/120.
- The multi-fact/table category improved 2/18 -> 10/18 for Hybrid and
  1/18 -> 8/18 for raw20. This is consumed development confirmation, not
  an independent improvement estimate. It includes the unchanged hard tables.
- Raw20's +5pp overall repair result costs higher p95 (1074 -> 1625 ms).
  It is incorrect to say all metrics improved or time stayed unchanged.

## What changed and why

1. Clause-aware credential routing distinguishes reimbursement vouchers and
   reset/rotation procedures from secret disclosure. A later unsafe clause
   cannot inherit an earlier benign exception.
2. An immutable delivered-evidence packet binds admitted text, exact spans,
   source/version/index identities and actual prompt boundaries. Complete-unit
   packing, round-robin aspect allocation and a distinct open citation ID
   prevent citations to text the generator never received.
3. Numeric/date/permission claims require bound source spans. Exact quotation
   does not establish that a quote answers the question; that limitation is
   deliberately retained in trace and the failure analysis below.
4. Runtime runners bind the active immutable snapshot, check it again before
   publication and invalidate cache entries on activation. Open/find results
   are checked against that same authorized snapshot before admission.
5. Raw reranking actually serves through the API: ACL -> candidates -> full
   content Guard -> scorer -> document deduplication -> bounded packet. No
   quarantined text reaches the scorer; no Dense backfill hides failures.
6. Readiness verifies exact model identity, warms the scorer before accepting
   requests and requests an explicit 8192-token context / 1024-token output.
   Scorer lock/capacity/OOM/unavailable/invalid-score failures are typed and
   fail closed without exporting private exception text.
7. Real service failures exposed title-anchor and cross-document version-key
   bugs. Requiring a named document and allowing its list request restored
   real `search -> open -> answer` execution. Conflict comparison now uses
   shared policy revision, not document-specific version_id. Neither change
   relaxes ACL, source binding or critical-claim checks.
8. A later run retained nine readiness 503s. The existing worker waited a full
   TTL before starting its next probe, creating an expiry window. A failing
   deterministic test reproduced absence of early refresh; serving requests
   now wake the worker at half TTL. Expired snapshots still fail closed.
   The historical nine responses lack per-probe diagnostics, so this mechanism
   is a supported explanation, not uniquely proven causality for all nine.
   The final fixed 80 requests had zero 503s; this is not a long-duration soak.

## Failures that remain

- Critical table or numeric answers can be paraphrased by the small generator
  and rejected; the fallback contains correct exact evidence but remains
  `partial`. Do not relabel it a completed answer for a better score.
- Non-quoted subjects still have a weak lexical relevance boundary. After
  deleting the courier policy, no deleted document is cited, but the model
  can answer using a different freight policy. Version correctness passed;
  question-answer relevance failed. Unknown parking questions can similarly
  receive unrelated grounded text. No zero-hallucination claim is valid.
- The frozen conflict fixture used two `supporting` documents while ordinary
  requests require `authoritative_only=True`. Its desired two-source answer
  is unreachable under that filter. All failures remain counted. This is an
  evaluation-design defect plus an unrelated-answer risk, not proof that the
  repaired conflict detector saw two facts and ignored them. Deterministic
  admitted-conflict tests pass; live conflict acceptance is NOT VERIFIED.
- No human answer/citation semantic review was performed. Phrase matching,
  source membership and version/span consistency are automatic contracts,
  not entailment or a human-labelled answer accuracy.
- Finite tests observed no unauthorized/forbidden/stale-source publication
  flagged by their oracles. That is not an external attack-success-rate
  estimate or a guarantee against every prompt injection.
- Concurrency probes were only four requests at each of 1/2/4 workers per
  profile, not a saturation experiment. Whole-GPU peak reached 7758 MiB on
  an 8151 MiB GPU; memory headroom is small and includes Ollama/other processes.

## Conditional work

Q1 exact selector: rejected because tie ordering changed despite speed gains.
Q2 additional open: not justified by the inspected failures; relevant facts
were already present or excluded by relevance, not absent adjacent content.
Q3 parser replacement: not justified; available layout counts do not prove
fact loss. Q4 adaptive retry: not enabled; the old assessor over-triggered.
Q5 fresh validation: blocked on an identified, permitted, unused compatible
cohort. Do not open an unrelated frozen test just to produce another number.
Details: [CONDITIONAL_DECISIONS.md](CONDITIONAL_DECISIONS.md).

## Reproduce and demonstrate

Use the existing verified local model files; do not download another model or
change the production index pointer. All paths below are project-relative on
the D-drive workspace; authentication setup remains mandatory.

```powershell
$env:V2_RETRIEVAL_PROFILE = 'safe_dense_raw20_bge'
$env:V2_RERANKER_DEVICE = 'cuda'
& '.\.private\reranker_cuda_env\Scripts\python.exe' -m uvicorn app.serving:create_app --factory --host 127.0.0.1 --port 8001
```

For fresh synthetic assets and a new declared run:

```powershell
python -m scripts.prepare_runtime_service_eval --output .private/runtime_delivery/new_assets
python -m scripts.eval_runtime_service --assets .private/runtime_delivery/new_assets --output .private/runtime_delivery/new_run
```

Fresh preparation creates new manifest/time identities, not identical bytes.
Use its generated protocol; the published protocol intentionally binds the
historical index hashes and cannot silently accept a newly built index.
Do not run these commands again as part of this already-exhausted budget.

For offline public review use service_cases.json and the three protocols.
Follow fact_remote, acl_allow/deny_release, lifecycle_before/update/delete/
rollback, direct_secret and retrieved_injection in their recorded order.
They are real historical API observations, not a live demo generated by this
document. Supporting mechanical fault tests cover model failure and wrong
numeric claims without requiring another paid/real inference.

Private-to-public replay check, when the private artifacts are available:

```powershell
python -m scripts.export_runtime_delivery --baseline .private/runtime_delivery/service_C_v1 --final .private/runtime_delivery/service_C_repair_v1 --confirmation .private/runtime_delivery/service_C_readiness_v1 --output docs/review/runtime_delivery_20260905 --check
```

Public exports have an explicit whitelist: no full answers, evidence bodies,
JWTs, reviewer identity secrets or local user paths. This custom contract
package is not silently labelled `enterprise.agent-run/1.0`.

## Resume-safe use

Prefer the scoped external retrieval result, implemented ACL/Guard-before-
reranker serving, immutable index activation checks and measured failure
handling. The 680 main requests and 775 total observations are execution
counts, not 680 independent questions. Do not call the final 80% a production
or external answer-accuracy score, claim zero hallucinations, merge old/new
WixQA protocols, or replace retrieval-only p95 with API p95.

The next valuable quality work would need a separately approved protocol for
subject/relation sufficiency and valid live conflict fixtures, with a genuine
held-out cohort and human semantic review. It is not justified to add another
framework or keep rerunning these same 40 cases until the output looks good.
