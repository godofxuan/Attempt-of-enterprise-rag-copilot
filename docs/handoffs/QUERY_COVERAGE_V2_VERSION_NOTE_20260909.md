# Query Coverage V2 local candidate version note

Date: 2026-09-09

## Version position

This is the local successor to the Query Coverage V1 candidate. V1 remains a
historical development record. Neither candidate is part of the canonical
public business code.

```text
canonical public checkout          D:\文档\agent\RAG_try
canonical public HEAD              c9984e92a10a6f417e2c1d8082af7e8f1e11aee1
candidate working tree             D:\文档\agent\RAG_try\.private\runtime_closure_20260907T160738
candidate branch                   fix/runtime-closure-20260907T160738
candidate base HEAD                b07c03d0256c393db5dfbb969e5d20abd70155b0
candidate source identity          BASE HEAD PLUS UNCOMMITTED MODIFICATIONS
main / GitHub business code        DOES NOT CONTAIN THIS CANDIDATE
active index / default runtime     UNCHANGED
commit / push / release / deploy   NOT PERFORMED
```

The candidate working tree already contains earlier uncommitted correctness and
V1 work. The V2 behavior cannot be identified by `b07c03d` alone.

## 2026-09-10 published review candidate

The latest reviewable candidate source is no longer available only through the
old `b07c03d` dirty working tree. It has been copied into an independent
checkout and pushed at an immutable review commit. The original dirty tree is
preserved, and `main` remains unchanged.

```text
review branch                      codex/local-closeout-20260910
review SHA                         152981aba3bc9a15a1035dbfa53dc57651b3c97f
candidate checkout                 D:\文档\agent\RAG_try\.private\release_candidate_20260910
candidate source fingerprint       5ebfbea12595e850149d6a77f3965c58e14e92ee6a4d7d56b149d09af3666164
main business-code SHA             c9984e92a10a6f417e2c1d8082af7e8f1e11aee1
merge to main                      NOT PERFORMED
production deployment              NOT PERFORMED
complete local regression          3973 PASSED / 3 FAILED / 36 SKIPPED
GitHub CI last observed            IN PROGRESS / PASS NOT CLAIMED
```

The immutable review entry is
[`152981a/docs/local_closeout_20260910`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/tree/152981aba3bc9a15a1035dbfa53dc57651b3c97f/docs/local_closeout_20260910).
This is a published candidate branch, not a `main` promotion or production
release. Future version comparisons should use this candidate for the newest
reviewable source while continuing to identify `c9984e9` as the main business
code.

The three local regression failures are two historical source-hash bindings
and one historical dependency-set binding; 36 skips remain environment-bound.
The result is not all-green. The public scan's 38 findings all map to
byte-unchanged `b07` files, while new or modified files contribute zero; this
does not erase the inherited findings. Public JUnit is a redacted derivative
with raw-hash mapping, and complete raw logs remain in the local audit ZIP.

The API and UI were exercised on `127.0.0.1:8010` and `127.0.0.1:8510` for
readiness, authentication, cited answering, identity refresh, shutdown, and
restart, then stopped. The material question still returned `partial`. This was
a loopback demonstration, not an Internet deployment, proof of complete
answers, or a production SLO. The demonstration token lasts 900 seconds and
must be refreshed under the original execution identity.

Default models and retrieval were not switched. LLM rewriting and XGBoost
remain unpromoted and outside shadow operation because no benefit was
established. GitHub Actions run `34455517994` was last observed in progress;
this record does not claim it passed.

The machine-readable receipt is
`docs/local_model_trials_20260910/DELIVERY.json`. Resume maintenance separately
published R20; future resume work must resolve
`D:\文档\工具\CURRENT_RESUME_POINTER.md`. This record authorizes no application,
upload, HR contact, or replacement of historical submitted attachments.

## 2026-09-10 broad-validation follow-up

V2 was subsequently retested together with five additional bounded production
file fixes. This follow-up is the latest local candidate snapshot, but it does
not change the public version position above.

```text
final Python file count            950
final Python source fingerprint    677f35a979c2ac41e5d6b3b8f2f1cee02a2bfb21d43d0a8e742e52fbccad1f8c
evidence ZIP                       .private/broad_validation_fixes_20260910/RAG_VALIDATION_FIXES_20260910.zip
evidence ZIP SHA256                beb14ac5e2306648bb5e99c858d76f406dd144619713482f003a5e91c20a5df5
ZIP verification                   PER-FILE HASHES AND ZIP CRC VERIFIED
main / GitHub business code        UNCHANGED / SNAPSHOT NOT PRESENT
commit / push / deployment         NOT PERFORMED
```

The follow-up changes only `answer_contract`, `evidence_relevance`,
`citation_verifier`, `generation_v2`, and runtime `resources`. It adds bounded
handling for natural/calendar/business-day expressions, avoids treating a
governance prefix as a policy entity, tightens acceptance of unrelated
evidence, admits only exact continuous full-sentence prefixes as citation
support, removes exact search/open packet duplicates, makes limited explicit
requirement-count omissions publish as partial, and starts readiness refresh
before the old snapshot expires. It adds no model, framework, retrieval
parameter, or automatic rewrite loop.

Final recorded verification:

| Measure | Before | Final local snapshot |
|---|---:|---:|
| Enterprise synthetic TEST automatic answer contract | 28/56 | 42/56 |
| Enterprise synthetic TEST full-layer contract | 27/56 | 41/56 |
| Authenticated local API contract | 170/240 | 193/240 |
| Erroneous `answered` API outcomes | 5/240 | 0/240 |
| Valid answered API outcomes | 123/240 | 139/240 |
| Main-request HTTP 503 observations | 6/240 | 0/240 |

The API cohort is 40 fixed questions under two configurations, each repeated
three times; it is not 240 independent questions. Pairwise comparison retains
39 recoveries and 16 regressions. The enterprise synthetic sets are consumed,
not fresh holdouts. Zero erroneous `answered` outcomes and zero 503 responses
apply only to this bounded run and do not establish zero hallucination,
availability, capacity, or production SLOs.

The software suite ended at 3,921 passed, 2 failed, and 32 skipped. The two
failures bind historical public evidence to the earlier `resources.py` source
hash; new current-mechanism evidence passed, but the historical assertions were
correctly left failed rather than rewritten. The skips represent unavailable
or unconfigured local platform features, including PostgreSQL and POSIX-related
coverage. Full-library Ruff still reports 1,173 pre-existing findings. Do not
summarize the repository as fully green.

WixQA was rerun for 800 configuration-question executions on this exact source
fingerprint. Rankings, status fields, failure fields, and quality metrics were
unchanged. The established Dense to safe raw50+BGE comparison remains Recall@5
`65.92%` to `74.25%` and nDCG@5 `52.08%` to `59.93%`. This is confirmation of
the previous retrieval result, not a new improvement, answer-accuracy figure,
or default-Hybrid result. FinanceBench, UDA, FinQA, FTS5, and the legacy WixQA
Agent adapter likewise showed no non-latency quality change.

The authoritative local reading entry is
`docs/broad_validation_fixes_20260910/README.md`. Detailed reports are under
`.private/runtime_closure_20260907T160738/docs/validation_followup_20260910/`,
and raw evidence is under `.private/broad_validation_fixes_20260910/`. The ZIP
is a source-and-evidence review package; it excludes model weights, full raw
indexes and external data, private keys, and runtime databases, so it is not a
self-contained deployment image.

## Bounded change set

- Adds finite expense-domain typo and colloquial normalization and uses the
  same interpretation for retrieval, evidence relevance, generation, and the
  limited answer contract. The original question and recorded `SearchRequest`
  remain unchanged.
- Protects quoted entities, identifiers, amounts, dates, negation, and hard
  filters. Risk detection is the union of the original and normalized views.
- Retains cited material and amount-limit claims that the existing approval
  publication contract previously removed.
- Checks material and amount coverage using complete requirement sentences,
  rather than treating a bare noun occurrence as complete support. Missing
  needs remain aligned across body, warnings, response mode, and trace.
- Clarifies the expense interpretation in the existing Qwen prompt and requires
  unique `C...` claim IDs, distinct from host-assigned `S...` source IDs.
- Retains the V1 same-document, same-version, same-filter bounded `find/open`
  path and all ACL, Guard, citation, budget, and deadline boundaries.

No LLM planner, evidence grader, generation retry, model, dependency, or MCP
wiring was added. The default architecture remains the Python controller,
tool registry, and document navigator.

## Verification and measured development result

The controlled corpus contains 12 scenario families, each expressed as clean,
typo, and colloquial forms: 36 questions and 69 complete reference-statement
occurrences. V1, a rules/retrieval intermediate, and final V2 each ran all 36
questions, for 108 real question runs. These are seen synthetic development
questions, not an independent user set.

| Measure | V1 | V2 intermediate | V2 final |
|---|---:|---:|---:|
| Reference statements delivered to the generation packet | 55/69 | 69/69 | 69/69 |
| Exact reference statements retained in final verified claims | 26/69 | 31/69 | 58/69 |
| Questions retaining all available reference statements | 14/36 | 21/36 | 25/36 |
| Missing/insufficient yet published as `answered` | 10/36 | 0/36 | 0/36 |
| System or output-shape failures | 6/36 | 6/36 | 0/36 |
| Complete-reference cases conservatively marked partial | 2/36 | 0/36 | 2/36 |

All 36 final outputs passed the existing citation publication checks. That is a
contract result, not human proof that citation semantics or answers are 100%
correct. The final prompt was adjusted after observing the same development
questions; it is not fresh validation. Two final cases also had evidence-packet
changes because the longer prompt affected the byte budget, so the final stage
is not a pure prompt-only single-variable experiment.

The adjacent regression gate passed 513 tests with 0 failures and 0 skips. It
contains 49 new V2 tests plus existing adjacent tests; it does not represent
513 new scenarios or users. Historical large suites and WixQA were not rerun.

## Residual omissions and regressions

Final V2 still omits at least one exact reference statement on 11 of 36
questions. Five questions retain fewer exact reference statements than V1:

- `condition_typo`
- `no_domain_repeat_typo`
- `unknown_material_clean`
- `unknown_material_typo`
- `unknown_approver_colloquial`

The last case still communicates that the approver is undetermined, but does
not retain the exact reference sentence. Other remaining misses include a
conditional original-invoice requirement, a later travel receipt, and a flight
cancellation certificate. Two otherwise fact-complete long-document cases are
conservatively partial because the prompt/packet budget indicates incomplete
reading. These negatives are part of the candidate result, not exceptions to
be hidden.

## Claim boundary

A suitable qualitative description is:

> 查询与答案一致性：针对报销错字、口语和多诉求遗漏，统一检索与生成的查询解释，保留否定、金额和制度名；按材料、审批、额度核对证据与最终回答，修复有依据答案误删和缺项误报完整，保持引用、正文与状态一致。

Do not claim that all typos or omissions are solved; that the candidate is on
GitHub, merged, deployed, or the default runtime; that MCP caused the result;
that 36 questions establish independent human accuracy; or that observed local
latency is an improvement. The established WixQA Recall/nDCG figures remain
unchanged, and the raw-50 experiment versus raw-20 serving distinction remains
in force. The `26/69` to `58/69` result must not be presented as a new WixQA or
online accuracy metric.

## Evidence locations

- V2 handoff: `.private/runtime_closure_20260907T160738/docs/query_coverage_v2/HANDOFF.md`
- V2 report: `.private/runtime_closure_20260907T160738/docs/query_coverage_v2/REPORT.md`
- V2 results: `.private/runtime_closure_20260907T160738/docs/query_coverage_v2/RESULTS.json`
- Implementation notes reside beside the report.
- Raw evidence root: `.private/query_coverage_v2_20260909`
- Preserved V1 root record: `docs/handoffs/QUERY_COVERAGE_V1_VERSION_NOTE_20260909.md`
