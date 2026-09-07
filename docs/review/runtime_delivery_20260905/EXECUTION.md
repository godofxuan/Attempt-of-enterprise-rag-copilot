# Runtime delivery execution record

Status: IN_PROGRESS. This record does not claim RC0-RC7 are complete.

## 2026-09-07 Final finite measurement completed

Final local full regression: 3653 passed / 32 skipped, 189.28 s; XML SHA-256
`7c9ff780cfdba3fefc5a748d2f84106e2fe272eab665769eaba0d7d511fa06cd`.
After adding the retrieval arithmetic export test, focused public evidence
suite: 6 passed. Service export replay: VERIFIED 775 rows. Retrieval export:
800 rows, every aggregate and latency quantile checked. Final prepublication
public scan: 1900 candidates / 0 findings. Ruff and git diff --check passed.

Full code regression at c33484c: 3647 passed / 32 skipped, 202.06 s.
Service baseline: 360 main + 15 warmup + 36 resource requests completed.
Correctness repair: 240 main + 10 warmup + 24 resource requests completed.
Repair Hybrid included nine service_not_ready 503s, retained as failures.
Early-refresh deterministic reproduction: 1 failed / 4 passed before fix;
207 related runtime/API/export tests passed afterward. Serving-only early
refresh wakes the existing background worker at half TTL, without stale grace.
Original resources.py is unchanged. The nine historical responses lack
per-probe diagnostics; TTL expiry is a reproduced mechanism consistent with
the burst, not an exclusive proven explanation of every historical failure.

Final code 0bca953: 80 main + 10 warmup requests, zero 503s, one round each
Hybrid/raw20, no extra concurrency test. Total 680 main, 35 warmup, 60
resource = 775 exported observations. Application/harness stayed byte-stable
during each run. Final complete contracts: Hybrid 32/40, raw20 31/40. Do not
equate the final one-round smoke with the earlier three-round estimates.

Exporter verification and public case/hash regression are added. No raw
answers/evidence/JWTs are published. RESULTS.md records outcome, mechanisms,
negative results, remaining subject-relevance failures and the supporting-only
conflict-fixture design error. The fixture's failures remain in the denominator.
No further model tuning is authorized inside this exhausted finite protocol.

Code commits c33484c and 0bca953 pushed normally to main; old refs preserved.
c33484c Windows, Ubuntu and PostgreSQL CI passed; container and final evidence
commit CI/clean checkout/related-task final receipts still require verification.
Initial resume correction ACK received: R11 was not overwritten or promoted.
EvalOps ACK received: no RAG edits/GPU work; waits for final evidence.

## 2026-09-07 service baseline and bounded repair

Quiescent full regression: 3641 passed, 30 skipped, 2 deselected in 236.26 s.
Actual RC6-C service_C_v1 completed 360 main requests, 15 warmups and 36
resource requests. Complete automatic contracts: Hybrid 85/120, raw20 90/120,
raw50 87/120. These repeated synthetic contracts are NOT human accuracy.
All original responses, partial answers and failures are retained privately.

Diagnosis identified two mechanism defects rather than justification to add a
model or parser: quoted titles were excluded from primary query anchors, while
a generic predicate could admit an unrelated policy; conflict grouping used
document-specific version_id instead of shared policy revision version.
Three new deterministic reproductions failed before the repair (12 passed).
The repair requires a named-entity match, allows named list requests to retrieve
their document, and compares same-policy/revision active evidence across
different document IDs. Explicit years, unsupported predicates, ACL, admission,
exact critical spans and separate revisions remain enforced. Initial relevant
regression: 243 passed. A multi-document comparison positive was also added.

SERVICE_REPAIR_PROTOCOL.json separately declares 240 confirmation requests for
Hybrid and raw20, unchanged 40 cases/indexes/models/labels, three rounds, plus
10 warmups and 24 resource requests. This is a correctness-repair deviation
under plan section 10.6.8, not a new independent test or a Q2 quality sweep.
Total main budget is 600, below the 680 ceiling. Raw50 has no post-repair
service confirmation and is not promoted from its retrieval score alone.
No unsupported-claim rule is relaxed to improve the completion count.

Q2: NOT_JUSTIFIED. Inspected table facts are already in delivered exact spans;
the three list cases fail relevance before generation. Neither demonstrates a
missing adjacent fact recoverable by another open call. Fix those mechanisms
first rather than consuming a quality-candidate sweep. General semantic
completeness and unknown-question refusal remain explicit quality limitations.

## 2026-09-07 pre-service acceptance freeze

Subsequent implementation adds full serialized prompt/retry/schema/output
budgeting, explicit per-call num_ctx=8192 and num_predict=1024, a bounded
duration-answer sufficiency check, packet digest/drop/coverage diagnostics,
content-free scorer failure categories, and strict readiness model identities.
Original config.py, retrieved_admission.py and ollama_chat.py bytes remain unchanged.
Q1/Q3/Q4/Q5 diagnostics and decisions are in CONDITIONAL_DECISIONS.md.

The first subsequent full regression was 1 failed / 3639 passed / 30 skipped /
2 deselected (224.20 s). The sole failure was the existing Git-stability guard
detecting concurrent public file edits during its synthetic evaluation test.
This is an execution-order error, not justification to disable that guard.
Separate evaluation-module rerun: 1163 passed / 16 skipped (92.24 s).
All contributors must finish writes before the quiescent full rerun.

SERVICE_PROTOCOL.json freezes 40 synthetic acceptance scenarios, three profiles,
three rounds (360 requests), 15 warmups and 36 separately reported resource
requests. Index preparation uses real BGE-M3 embeddings in isolated D-drive
assets, not mocked retrieval. Protocol SHA-256:
`4bac324a0b21edccdccbbe5f319ec1deae599af71dea9a5d858819206bc34137`.
Three immutable snapshots (base/updated/deleted) exercise activation/deletion/
rollback without modifying the production active pointer. Source/version
identities and actual code hash are captured by the run itself.

Preparation failures retained: v1 was rejected because duplicate authoritative
versions violate ingestion governance. Supporting documents with equal scope/
authority are used for the legal unresolved-conflict fixture instead. v2/v3
were pre-service drafts; final v4 fixes the update's effective date so it is
actually active on the experiment date and excludes an ambiguous negative
substring from the security-leak oracle. No service labels were changed after
seeing model outcomes. Each successful build made 30 unique real embeddings
reused between snapshots; this does not claim 30 newly independent questions.
Automatic scoring is phrase/source/span contract checking, not human semantic
accuracy. All service attempts, including failed ones, must be retained.

Latest completed full checkpoint including navigation-output binding and
capacity/fault tests: **3588 passed, 30 skipped, 2 deselected**, 239.57 s,
three existing SWIG warnings. No required command remains running at this
checkpoint; remaining delivery gates below are not thereby completed.
RC6-B now has a complete real retrieval replay (800 rows); see
[retrieval results](RETRIEVAL_RESULTS.md). A real authenticated GPU API smoke
now returns a verified answer for the previously failing case. Neither is the
pending 40-scenario paired service evaluation. No commit, push, default-profile
promotion, or RC0-RC7 completion is claimed.
Checkpoint XML SHA-256:
`6e4f1539512fcbcfbc7e4a5c57d44ad57e9f1f9eb4864ec86a74e89125a3ac1b`.

```powershell
& '.\.venv\Scripts\python.exe' -B -m pytest -q -m 'not integration' -p no:cacheprovider --basetemp .private/runtime_delivery/pytest_navigation_final --junitxml .private/runtime_delivery/pytest_navigation_final.xml
```

Latest public scan: **1876 candidates / 0 findings**. Changed Python surfaces
pass Ruff and `git diff --check` passes. Historical test counts below
describe earlier checkpoints and are not additive. Detailed continuation:
[API diagnosis and navigation binding](API_AND_NAVIGATION_REPAIR.md).

## RC0 baseline capture

- Baseline business HEAD: `d27c0f8a68830fd74bbb983567e8b4d50967c0ae`.
- Capture command: `python -B -m scripts.capture_runtime_delivery_baseline --output .private/runtime_delivery/rc0_baseline_20260905.json`.
- Private artifact SHA-256: `5c6f10d25e68df9579d2d248bf0f94b8f3b5b6065dca6b6d92c1f917ee8841fc`.
- The worktree contained review/planning changes; the app sources were unchanged at capture time. Exact per-app-file hashes were captured.
- Answer model: `qwen2.5:3b`, digest `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`.
- Evidence model: `qwen3:8b`, digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
- Embedding: `bge-m3:latest`, digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`.
- GPU: RTX 5060, 8,151 MiB, driver 610.88. No inference performed for this capture.
- Active run: `20260724T024653Z_expanded_bge_m3_fixed`; manifest `69b9fb7d3008467f65fb2920a621e9812cdb59c4919834819333e0e33b866507`.
- Full live-model protocol/case freeze remains pending. No quality run may start until it is recorded.

## RC1 first vertical slice

Changed: `app/agent/query_analysis.py`; new regression file `tests/agent_v2/test_runtime_delivery_routes.py`.

The previous credential rule treated reimbursement vouchers and reset/rotation procedures as secret requests. The first red run was 3 failed / 5 passed. A bounded procedure exception fixed those cases, but the next mixed-clause tests found four unsafe requests could inherit an earlier safe clause, plus one false rejection of "show me how". That intermediate implementation was not accepted as final.

The revised rule separates credential clauses, distinguishes financial vouchers, strips only explicit guidance prefixes, and checks disclosure verbs across the complete request. Unknown credential clauses remain conservative. A first integration run caught the separate "I forgot my password" introductory clause; recognizing that recovery context restored the positive without removing mixed-request checks.

Final command for this slice:

```powershell
& '.\.venv\Scripts\python.exe' -B -m pytest tests/agent_v2 tests/security/test_api_v2_zero_leak.py tests/api_v2/test_identity_boundary_api.py -q -p no:cacheprovider --basetemp .private/runtime_delivery/pytest_rc1_verified
```

Result: 186 passed, three existing SWIG warnings, 1.75 s pytest time. These are deterministic checks, not a live-model benign false-refusal rate. Broader end-to-end acceptance remains pending.

## RC2 delivered evidence and publication slices

Changed `app/domain/evidence_packet.py`, `app/domain/evidence.py`,
`app/agent/generation_v2.py`, and `app/agent/citation_verifier.py`.

- `DeliveredEvidence` wraps admitted values rather than creating fake Guard approvals. Search text must be a prefix of the admitted field. Open content must match its admitted document and has a distinct citation identity and navigation target.
- Generation and verification consume the same bounded text. Previously open text was embedded under a search source while verification used the unexpanded search hit; a correct open-only fact was rejected. A red test now passes with a separate open source.
- Aspect round-robin selection reserves room for missing aspects and does not repeat identical matched/context text. A long Policy A fixture no longer consumes every slot before Policy B.
- A supported Policy A claim alone no longer marks a Policy A/B comparison complete. The comparison check is conservative literal aspect identification, not a universal semantic coverage evaluator.
- A further red test found extractive fallback still published a truncated-away tail. Fallback now extracts only from the delivered packet; unsupported generated prose is never reintroduced.
- Focused verification after these changes: 189 passed / 3 existing warnings, 2.01 s. Counts overlap with RC1 and must not be added as independent coverage.

## Final outcome trace slice (R10, pulled forward from RC5)

Changed `app/agent/runner_v2.py`. Three red tests covered generated success,
partial fallback, and transport failure. Trace now preserves
`controller_stop_reason` but reports the response's actual `stop_reason` and
`final_mode`. Controller steps remain historical decisions, not fabricated
successful generation steps. Verification across agent/API/zero-leak tests:
272 passed / 3 existing warnings, 5.09 s. This does not complete RC5 reranking
or budget/resource integration.

## Critical fact grounding slice

Added server-resolved `SupportingSpan` fields (citation, index, version,
source field, exact offsets and quote). `support_kind` distinguishes legacy
compatibility records, heuristic support, exact source units, and rejection.
Numbers and bounded approval/permission vocabulary require complete source
units; `Claim.critical=false` cannot opt out. Only whitespace and case
normalization are allowed in this slice. The resolver does not accept an
arbitrary substring that drops a preceding qualifier and does not split a
decimal point as a sentence boundary.

Red tests: 15 failed / 2 passed (10 wrongly accepted value/role combinations,
5 missing span annotations, 2 already correctly rejected negations). After
implementation: 289 passed / 3 existing warnings across agent/API/zero-leak
tests, 4.78 s. A generation-path regression was added afterward; full
non-integration suite is being run and is not yet declared passed.

Limits: exact source agreement is not document truth or answer completeness.
Legitimate paraphrases of critical facts may become extractive partial
answers. This tradeoff needs the frozen real-model acceptance run. General
conflict classification, precise snapshot binding for open/find, whole-unit
packing, token budgeting and full RC0 protocol freeze remain outstanding.
No new Recall/nDCG, latency, or resume effectiveness claim has been made.

## Full-suite regressions found and repaired

The first full non-integration run returned **6 failed, 3518 passed, 30
skipped, 2 deselected**, 221.93 s. Artifact:
`.private/runtime_delivery/pytest_full_first.xml`.

These failures were not ignored:

1. One EvalOps artifact test detected raw `SupportingSpan` contents in the
   trajectory. `orchestrator._complete_trajectory` had exported the entire
   citation model. It now uses an explicit allowlist of citation flags/IDs
   and span count; source text/offsets are not exported to the trajectory.
   The authorized answer can retain its support span while the audit
   artifact stays content-free. No safety assertion was weakened.
2. Five security-evaluation failures shared one cause: a preceding quoted
   training sentence ended in a closing quote after its period. The unit
   resolver did not recognize that boundary and rejected the subsequent
   exact numeric fact. Sentence boundaries now consume closing quotes
   without treating the quoted directive as a standalone trusted command.
   Dataset contents, expected facts, gates and frozen hashes were unchanged.

Targeted regression rerun: 90 passed / 3 warnings, 12.48 s.

A further red packing test demonstrated a sentence with a trailing
qualification could be truncated midway. `complete_evidence_prefix` now
returns the preceding complete source unit when truncation is necessary;
JSON-overhead trimming uses the same boundary policy. A source with no
complete unit fitting the budget is omitted rather than fabricated.
This is a conservative prose safeguard, not table-layout understanding.
Combined follow-up: 319 passed / 3 warnings, 7.18 s.

Static checks on changed Python surfaces pass. Public repository scan:
1850 candidates / 0 findings before adding the next conflict test file.
`git diff --check` passed. All test outputs/temp files are under the D-drive
workspace `.private/runtime_delivery/`.

## Verified checkpoint before conflict integration

After the six full-suite regressions and whole-unit packing fix, the complete
non-integration suite passed: **3529 passed, 30 skipped, 2 deselected**,
214.52 s, three existing SWIG warnings. XML:
`.private/runtime_delivery/pytest_full_final.xml`.
The filename reflects that checkpoint, not completion of the whole plan.
The conflict implementation below was added afterward and has separate tests.

## Bounded numeric conflict slice

The red runner test reproduced two active same-scope refund statements,
7 days and 30 days, being published as an ordinary answered result.
`evidence_ledger._numeric_conflicts` now compares only single-value source
units with matching policy/version/index/tenant/region/ACL/authority and
identical normalized surrounding wording. Decimal equality makes 7 and 7.0
equivalent. A changed explicit condition or relation is not automatically
labeled a conflict. This function does not read `fact_ids` or gold labels.

`controller_v2` stops with partial evidence for unresolved conflicts.
Both extractive and generation builders use bounded, independently cited
conflict excerpts without asking the model to choose a winner. The final
trace still distinguishes the decision from the published outcome.
First agent/API/domain integration: 307 passed / 3 warnings, 5.13 s.
The subsequent compatibility suite includes an explicit assertion that an
unresolved conflict does not call the generation model.

Compatibility suite: 1263 passed, 16 skipped, 2 deselected, 99.51 s
(`tests/evaluation`, `tests/agent_runtime`, conflict tests). These overlap
with the full suite; do not add their counts. A subsequent adversarial test
found that an unrelated higher-authority hit could trigger the legacy
priority resolver and mask a detected lower-authority numeric conflict.
Automatic same-template conflicts now remain unresolved regardless of an
unrelated supporting hit's authority. Explicit caller-supplied conflict
priority behavior remains compatible. The new red run was 1 failed / 5
passed; after repair agent/API/domain checks were 309 passed, 5.17 s.

This is deliberately NOT general contradiction detection: paraphrased
policies, several numbers in a clause, table relations, open-only conflicts,
and unknown applicability remain outside this slice. Related-but-insufficient
evidence is not fully modeled yet. RC2 therefore remains IN_PROGRESS.

## 当前进度说明（中文）

这轮已经在代码中修复了正常问题的部分误拒答、open 引用错位、
提示词与验证证据不一致、多方面证据被挤掉、降级回答引用未交付原文、
关键数字/角色错配、最终 trace 终态不一致，并加入有限范围的数值冲突处理。
每项都有反例测试；完整回归发现过真实问题，已经记录并修复，没有删测试或改题目。

这些结果证明机制修复，不等于模型正确率提升。尚未进行本轮真实模型
质量/延迟比较，也没有新增简历数字，没有发布到 GitHub 或向其他任务宣称完成。
RC0 的完整评测协议、RC2 剩余边界、RC3 索引生命周期到服务的一致性、
RC4 证据口径、RC5 主接口重排/预算、RC6 成对实测及 RC7 发布同步仍有工作。
后续按主方案继续，不需要用户重新审核这批已批准的阶段。

## Next exact work items

1. Freeze the complete real-model acceptance manifest before any new quality
   run; preserve the captured baseline identity and historical artifacts.
2. Finish RC2: explicit relevance versus sufficiency, packet source/version
   binding for navigation, coverage/drop records and token accounting. The
   current conflict rules are bounded and do not settle those requirements.
3. RC3 must replace the no-argument serving cache with request-bound active
   version identity and test activation/deletion/rollback/concurrent workers.
4. Only then proceed to truthful provenance, opt-in guarded BGE serving,
   paired real-model comparison and release/synchronization. Do not treat
   these local code changes as a published default promotion.

## RC3 serving-index binding continuation

Changed `app/agent/runner_v2.py`; added
`tests/agent_v2/test_runtime_delivery_index_binding.py`.

The first red test built two real index versions with synthetic embeddings,
activated the second version, and still observed `first` in the default
service factory. The old no-argument `lru_cache(maxsize=1)` retained the first
snapshot indefinitely. The factory now reads the atomic active pointer for
each lookup and caches by resolved root, run ID, manifest SHA, runtime
configuration and selected finance policy configuration. At most two runner
entries are retained. A lock serializes cold construction so concurrent
requests do not load duplicate large snapshots. The lock is not held while
generating answers. There is no Redis or worker invalidation bus.

The next behavior test activated a new version inside the response builder;
the previous implementation published the old answer as answered. Before
reproducing that behavior, a fixture incorrectly called `user_context` with
keyword arguments and was corrected; that fixture TypeError is NOT evidence
of a production failure.

A bound runner now checks the pointer before tool execution and immediately
before returning its result. A changed pointer (including activation then
rollback with a new activation timestamp) withholds claims and sources and
returns a system outcome with bounded `index_binding_status`. An unreadable
pointer is unavailable, never an excuse to serve a cached old answer.
The verified run/hash identity is included in the response trace; paths and
raw exceptions are not. The original search/open pipeline remains pinned to
one immutable snapshot throughout the request.

Regression coverage includes:

- Activation and rollback through the actual index store and snapshot loader.
- New pointer with incorrect manifest hash: no cached-old fallback.
- Activation, activation/rollback, or pointer disappearance during generation.
- Removal of an entire policy from a newly built target: the removed document
  cannot be opened; a retained old runner cannot publish; rollback restores it.
- Eight parallel cold lookups share one runner instance.
- Two spawned processes independently observe first/second/first without
  receiving a cache-invalidation instruction.

The removal fixture tests serving against a rebuilt target, not a new claim
that the existing incremental deletion machinery was rewritten. Existing
lifecycle tests remain part of the full suite.

Targeted commands/results:

```powershell
& '.\.venv\Scripts\python.exe' -B -m pytest tests/agent_v2/test_runtime_delivery_index_binding.py -q -p no:cacheprovider --basetemp .private/runtime_delivery/pytest_lifecycle_serving
```

8 passed, 3 existing warnings, 6.01 s. Earlier agent/API/zero-leak integration:
303 passed, 6.11 s, before the additional lifecycle/concurrency cases.
Full non-integration verification for this continuation is recorded separately.

Publication boundary: this checks the active pointer immediately before the
Python response returns. It does not claim to revoke bytes already in transit
or hold a publication lock until a remote client acknowledges receipt. An
activation after that check belongs to the subsequent request boundary.

## RC4 documentation corrections (partial)

- `ENTERPRISE_FAILURE_ANALYSIS.md`: 153 final-Top-5 misses are not evidence
  that all 153 are absent from the larger reranker candidate pool. Kept every
  historical count; removed the unsupported ranking-bottleneck conclusion.
- `RAW_CHUNK_GUARD_FINAL_RESULTS.md`: verified Git blob SHA-256 with binary
  `git show` output and corrected LF identity to `287f8a20426256061f2d3b824e96ce79108e22e83fac5209b9078b52849dd2d0`.
  Retained the CRLF working-copy hash as historical explanation. Explicitly
  disallowed a matched latency ratio between old Dense 44.41 ms and the
  corrected Guard-on runs. No result JSON, labels or metric values changed.
- Latency script provenance hardening remains pending; these prose corrections
  do not claim that hard-coded execution metadata has already been fixed.

本次继续的实际收益是“制度更新/删除后不再静默沿用旧答案”，不是新增
Recall 提升数字。当前仍未启动 RC6 真实模型质量比较，也未推送或同步简历。

## RC5 admitted reranking integration (in progress)

Implemented the optional server-owned profiles `dense_reference`,
`safe_dense_raw20_bge`, and `safe_dense_raw50_bge`; default remains unchanged.
Configuration lives in `app/retrieval/serving_config.py`, using `V2_` environment
variables. Profile selection is included in the versioned runner cache key.
The requested identity and metadata scope are preserved. Dense requests retrieve
up to 200 raw candidates, slice to 20/50 before admission, scan full text,
metadata and applicable parent/split surfaces, score only admitted matched text,
then deduplicate by document and return Top-K. No outside-pool backfill occurs.

Changed files: `tools_v2.py`, `retrieved_admission.py`, `runner_v2.py`, new
`local_cross_encoder.py` and `serving_config.py`. The scorer is local-only,
uses safetensors, disables remote code, limits batches to 16 and input to 512
tokens, and allows at most 50 candidates. A shared scorer serializes inference
with a 250 ms lock wait. Failures return no evidence; no silent unguarded
fallback. Deadline checks discard late results, but do not cancel GPU kernels.
Model initialization is lazy and cold-start time is not excluded from calls.

Test-first evidence: five new admission tests initially failed because no scorer
hook existed, then passed after implementation. Four registry tests verify raw
depth, fixed dense policy, missing scorer rejection and model failure. Combined
agent/security/API regression: 565 passed, 6 skipped (40.74 s), XML at
`.private/runtime_delivery/pytest_reranking_checkpoint.xml`.

An intermediate regression failed because adding fields to `app/config.py`
changed the hash bound into historical identity evidence (all 20 behavior cases
still passed). Moved new configuration into its own module and restored the
original config bytes. Did not rewrite historical evidence or weaken the test.

Environment check: main venv has torch 2.13.0+cpu, CUDA unavailable. The separate
CUDA environment is not the main API environment. No real reranker inference or
new Recall/latency claim has been established by this slice. GPU serving setup,
full model identity binding, deadline/resource validation and RC6 remain open.

## RC4 executable provenance corrections (partial)

`capture_runtime_delivery_baseline.py` now includes untracked application files
and deleted-file markers, and uses git status to detect untracked app changes.
The latency erratum script now measures dirty state and a source-tree hash,
checks weights against quality evidence before inference, rejects changed
execution identity, computes the existing quality rule instead of hard-coding
True, and keeps machine-specific argv private. Historical artifacts are not
rewritten. Two new quality-rule tests and nine existing ablation tests pass.
Tokenizer/config pinning and a fresh actual measurement are still pending.

### Subsequent verification and historical replay boundary

Real BGE scorer smoke in the existing CUDA environment succeeded: two synthetic
query/passage pairs produced scores -1.673828125 and -11.0234375. Cold load plus
inference took 44.536 seconds. This is NOT a quality evaluation and NOT a warm
service latency measurement. It establishes a deployment prerequisite: warm the
model in the serving process before accepting reranker requests; the current
lazy cold path cannot meet the 15-second request budget. The smoke subprocess
exited, releasing its model allocation.

The first broad suite was interrupted after repeated failures. An isolated
first-failure run confirmed the immutable historical replay dependency hash
rejected edited admission bytes (967 passed before that first failure). The
fix preserves the original `retrieved_admission.py` exactly and introduces
`reranking_admission.py` as the new optional serving boundary. Historical
replay continues using its original implementation; new serving behavior must
earn separate security/quality evidence. This intentionally versions the search
admission method while reusing its scan helpers and typed result contracts.
No pinned historical hash or artifact was updated to disguise the difference.
After separation, 179 focused replay/new-admission/registry tests passed.
The full suite is being rerun against the separated implementation.

Full regression completed: 3554 passed, 30 skipped, 2 integration tests
deselected, 316.56 seconds. XML:
`.private/runtime_delivery/pytest_reranking_final.xml`, SHA-256
`ae0966855abff384990568e40d9918a98ee0e347a12d1da544e31d0104b2e689`.
After final trace/format adjustments, 25 targeted tests passed separately.
Public audit: 1858 candidates, zero findings. These counts overlap; do not add
them as independent cases. No GitHub release or resume metric update occurred.

Optional reranking step traces now expose only retrieval mode and allowlisted
aggregate counts (scored candidates, scorer calls, elapsed milliseconds,
returned count). Default trace keys remain unchanged. No passage text is added.

Next release prerequisites remain: explicit in-process warmup/readiness and
resource validation; full scorer file identity; frozen RC6 evaluation protocol
and index equivalence; real paired quality/service measurement; remaining RC2
evidence coverage work. This is not RC5 or RC6 completion.

## Continuation: startup and measured budget defect

Added `app.serving:create_app`, an opt-in API factory composing the original
authenticated API and original lifespan. It warms the shared scorer before
the application accepts requests. Failed warmup fails startup. This preserves
the original API file identity for historical evidence; deployment must use
the new factory for a reranker profile. Two lifespan tests went red, then green.

Added `reranker_identity.py`: verifies all six runtime files against frozen
SHA-256 values, not just weights. Local cached upstream tree identifies revision
953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e; weights/tokenizer LFS identities match
that tree. Missing/corrupt snapshots are rejected before inference.

RC6-B protocol v1 was frozen before execution. The adapter reuses the original
FAISS and BM25 objects and exact ordered chunk IDs/text. It adds explicit
benchmark-only ACL/version/locator metadata. It is retrieval-only, has no
document-open capability, and is not an activated enterprise index. Do not
describe its added metadata as authentic enterprise provenance.

The first run exposed duplicate context accounting: identical matched and
context strings were both charged, although generation packs them once.
267 rows were retained; 228 hit the context budget and 39 succeeded. The run
was deliberately aborted rather than wasting the remainder on the same defect.
A new regression reproduced the rejection, then passed after the registry
subtracts only exactly identical repeated context. Distinct parent content
and metadata remain charged. Historical admission scan accounting is unchanged.
Nineteen related tool/boundary tests passed. This is a correctness repair, not
an increase to the context limit or a change to ranking parameters.

Protocol v2 explicitly records the extra 267 failed-run rows. Its first process
disappeared after seven successful rows without a completion marker; it is
not a completed evaluation. The same protocol was restarted into a separate
v2b directory with stdout/stderr captured on D. Those seven rows are also
preserved. The v2b run is now complete: 800 rows, zero execution errors.
Total attempted-row accounting is 267 + 7 + 800 = 1074,
not the initial 800 budget. No more ranking configurations were added.
