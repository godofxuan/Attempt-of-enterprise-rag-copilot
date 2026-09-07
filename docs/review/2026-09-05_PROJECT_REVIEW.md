# Project Review: Runtime Value and Remaining Work

Review date: 2026-09-05. Reviewed source: `d27c0f8a68830fd74bbb983567e8b4d50967c0ae`.
The checkout was clean at the start. This is a local source and artifact review,
not a new model experiment, an independent benchmark, or a complete security audit.

## Decision

Further work is justified, but it should be one bounded correctness and
integration pass. Stop adding frameworks and retrieval variants. The existing
retrieval improvements are supported by saved per-question records; the most
valuable remaining work concerns what the running application actually serves.

The earlier blanket closure statements were too strong. In particular, the
selected WixQA reranking experiment is not currently wired into the main chat
API. The repository can support a portfolio discussion of implementation and
retrieval experiments, but runtime quality and full integration need narrower
claims until the findings below are resolved.

## Findings

### R1 [P1]: Grounding can publish a value attached to the wrong subject

Locations: `app/agent/citation_verifier.py:106`, `:181`, `:246`;
`app/agent/generation_v2.py:188`, `:245`.

The verifier concatenates cited text, checks token overlap, and verifies that
claim numbers occur somewhere in that text. It does not bind the number to
the subject or relation asserted in the claim.

Reproduced with ordinary Guard-admitted fixture evidence:

```text
Evidence: Refunds are processed within 7 days. Invoices are retained for 30 days.
Claim:    Refunds are processed within 30 days.
Result:   supported=True, lexical_support=1.0
```

A second case also passes:

```text
Evidence: Employees submit expense reports. Managers approve expense reports.
Claim:    Employees approve expense reports.
Result:   supported=True, lexical_support=1.0
```

The first case was also passed through the real `GenerationV2ResponseBuilder`
using an injected deterministic chat response. It returned the incorrect
30-day claim with `mode=answered`, `stop_reason=completed`, and no warnings.
This establishes an accepting publication path, not the frequency with which
a real LLM would produce that error.

Minimum fix: bind critical numeric and permission claims to supporting
sentences or table cells and their subjects. Use a conservative extractive
fallback when support is ambiguous. Sentence-local number matching alone will
not solve every subject/relation error. Add positive paraphrase controls along
with value swaps, actor swaps, negation, dates, and table-row swaps; measure
both false acceptance and false rejection. Adding an LLM judge by itself does
not establish a hard correctness guarantee.

### R2 [P1]: The chat runner keeps an old index after active-version changes

Locations: `app/agent/runner_v2.py:417`, `:430`;
`app/api/lifecycle.py:96`, `:107`; `app/runtime/resources.py:363`.

The default runner is an argument-free `lru_cache(maxsize=1)` and loads its
snapshot only during construction. The operator activation/build endpoints
can switch the active index without invalidating or versioning that runner.
Readiness independently loads the active index, so readiness and serving can
describe different snapshots when deployment pinning is absent.

An in-process fixture probe used the actual runner factory, pipeline, and
navigator, with the snapshot loader replaced by a mutable active-snapshot
fixture. After switching from a snapshot containing doc-a to one containing
only doc-b:

```text
current active fixture: version-after-delete
cached runner reused:   true
snapshot load calls:   1
served run ID:         version-before-delete
served document:       doc-a
```

This was a simulated pointer switch, not a full operator-API deletion test.
The deployment runbook prescribes restarting for release rollback, which
avoids this case there. The live lifecycle API does not provide the equivalent
serving-version contract.

Minimum fix: resolve and pin the active manifest at a request boundary; cache
runners by validated index identity, with bounded retention. New requests must
observe activation, while each in-flight request uses one immutable version.
Alternatively, explicitly mark activation as pending restart and fail readiness
until the serving version matches. Test query -> activation/delete -> next
query -> rollback in the same process, then across worker processes. A single
process-local `cache_clear()` is not a complete multi-worker solution.

### R3 [P1]: Benign enterprise questions are rejected before retrieval

Locations: `app/agent/query_analysis.py:42`, `:164`, `:303`.

The credential-exfiltration regex matches topic words, including the Chinese
word for a voucher/credential, any password mention, and `API key`, without
requiring a request to expose a secret or bypass permissions.

Three ordinary requests were run through the real analyzer. All returned
`intent=unsafe`, `risk_flags=[credential_exfiltration]`:

- What supporting vouchers are required for travel reimbursement?
  Actual Chinese probe: `\u51fa\u5dee\u62a5\u9500\u8981\u63d0\u4ea4\u54ea\u4e9b\u51ed\u8bc1\uff1f`.
- I forgot my password; how do I reset it using the company process?
- How do I rotate an API key safely?

Minimum fix: distinguish requests for policy/procedure from requests to reveal
secret values, export protected data, or bypass access. Keep identity, ACL,
and retrieved-content admission in force. Add paired benign/malicious tests,
including instructions disguised as password-help requests. Measure benign
false refusal rather than optimizing attack blocking alone.

### R4 [P2]: The selected reranker is an evaluation profile, not a chat option

Locations: `app/agent/runner_v2.py:435`, `app/agent/controller_v2.py:136`,
`app/evaluation/wixqa_article_chunk_reranker.py:116`, `README.md:49`, `:76`.

Repository-wide Python/config reference searches found the raw reranker in
evaluation code and tests, with its executable caller in
`scripts/eval_wixqa_retrieval.py`. The final ablation/latency scripts implement
their own scoring loop. The main chat factory builds HybridRetrievalPipeline
and V2ToolRegistry; it does not create or select the BGE raw reranker.

The test named `test_final_evaluator_and_runtime_raw_reranker_agree_on_safe_fixture`
compares an evaluation helper with a class using synthetic scores. It is useful
class-level parity coverage, but does not establish HTTP/application integration.

Consequently, 302.75 ms is local embedding/retrieval/Guard/reranking/deduplication
latency in an evaluation harness. It includes actual model inference, but not
the complete authenticated API, controller, answer generation, and publication
path. Calling it an online application latency or an available serving profile
overstates the implemented scope.

Minimum fix now: correct the serving-profile and latency wording in the current
entry documents and resume rules. If an interactive GPU profile is wanted,
connect a server-selected, opt-in strategy through the existing ACL/admission
contracts and one shared scorer. Preserve admitted evidence and source/version
identity through generation. Test all-quarantined results, timeouts, OOM/model
unavailability, and same-case OFF/ON behavior through the actual entry point.

### R5 [P2]: The published latency checksum does not match Git bytes

Location: `docs/wixqa_reranker/RAW_CHUNK_GUARD_FINAL_RESULTS.md:108`.

Direct byte hashing of the working file and the Git blob at the reviewed SHA:

```text
Working-file SHA-256 (also the documented checksum):
043f043ccc67ba7aff6f78e7512bfe3a02d3f37dc45a0ee26876821cad5183d7

Committed Git-blob SHA-256:
287f8a20426256061f2d3b824e96ce79108e22e83fac5209b9078b52849dd2d0
```

The working file uses CRLF and Git stores LF under `.gitattributes`. Parsed
JSON content is equal. This is a release-byte integrity error, not a quality
metric change. A reader verifying the published file using the documented
checksum will fail.

Minimum fix: use stable output bytes and define whether an artifact checksum
means exact published bytes or canonical JSON content. Verify the actual Git
blob against the documented value in release checks. Keep private/pre-redaction
and public/post-redaction hashes distinct. The old Dense 44.41 ms figure in the
evaluation summary also remains a composite historical timer and should not
be compared as a newly measured clean Dense-only latency.

### R6 [P2]: Some provenance assertions are constants, not validations

Locations: `scripts/measure_wixqa_raw_chunk_online_latency.py:241`, `:249`, `:258`.

`git_dirty=False` is emitted without checking the worktree. Model revision is
a constant despite accepting an arbitrary local model directory; the weight
hash is recorded but not checked against the frozen quality artifact. The
Top-50 quality gate is also marked true without deriving it from that artifact.
Tokenizer/config identity is not bound by the single weight-file hash.

The historical hashes and rankings available locally are consistent; this is
not evidence that the recorded run used a different model or dirty source.
It means the exporter can mislabel a future run and is weaker than its claim.

Minimum fix: capture source state before measurement, validate the frozen input
identities including tokenizer/config, derive eligibility from the quality
artifact, and reject mismatches before expensive inference. Record normalized
effective CLI arguments; `main(argv=...)` must not publish unrelated process
arguments. Extend tests to changed inputs/dirty source rather than only checking
fixed aggregate values.

## Verified Results and Their Limits

Private candidates and private ranking signatures were available on D:. Their
candidate hash binding matches, and the private quality aggregate stripped of
private signatures equals the checked-in public quality JSON.

Independent scoring arithmetic (without calling the evaluator's metric helper)
recomputed all five arms from 200 unique questions and 258 gold article labels.
Every result agreed within 1e-12; maximum absolute float difference was below
4.45e-16. Recall is macro gold-article recall, not hit rate or answer accuracy.

| Configuration | Recall@5 | nDCG@5 | MRR@5 | Complete multi-article cases |
|---|---:|---:|---:|---:|
| Dense | 66.4167% | 52.1583% | 49.6083% | 16/52 |
| Raw Top-20, Guard ON | 72.5000% | 59.3507% | 57.9250% | 17/52 |
| Raw Top-50, Guard ON | 74.5000% | 60.0858% | 58.3167% | 18/52 |

Saved Top-20 retrieval has at least one gold article for 158/200 cases, but
complete gold coverage for only 132/200. Among the 52 multi-article questions,
only 17 have complete coverage. Better average recall does not establish
complete multi-document answers.

Additional read-only candidate diagnostics, before Guard and without a Top-5
output limit: raw Top-20 candidate recall 83.1667%, Top-50 92.4167%, Top-200
97.8333%. These are candidate coverage figures, not final retrieval metrics or
new resume claims. They show that ranking/evidence selection deserves attention
before indiscriminately increasing the indexed corpus or adding models.

No new real-model quality or latency run was performed for this review. The
existing CUDA scorer copies logits to CPU before ending its timer; the code
does not support a claim that GPU work was wholly omitted from latency.
The new timer does avoid the historical article-level extra query. Neither
fact makes it an end-to-end service measurement.

Top-50 remains a valid, higher-quality offline point. Its approximately 378 ms
extra p95 versus Top-20 is a product trade-off. The frozen 650 ms experiment
gate should remain recorded, but it is not a universal rule that 681 ms is
unusable. A future serving choice needs a real total-answer latency budget.

## Validation Executed

```powershell
& '.\.venv\Scripts\python.exe' -B -m pytest tests/agent_v2 tests/retrieval tests/security/test_retrieved_admission.py tests/security/test_api_v2_zero_leak.py tests/api_v2/test_identity_boundary_api.py tests/api_v2/test_real_jwt_integration.py tests/api_v2/test_observability_api.py tests/evaluation/test_wixqa_raw_chunk_guard_ablation.py tests/external_datasets/test_wixqa_retrieval.py -q -p no:cacheprovider --basetemp .private/review_20260905_pytest
```

Result: 271 passed, 3 pre-existing SWIG deprecation warnings, pytest time 5.26 s.
This is targeted coverage, not the entire repository suite or a production test.

The public-repository scan at the reviewed checkout returned 1,840 candidates
and zero findings. This scanner checks its configured publication patterns; it
does not validate the checksum in R5 or guarantee semantic data correctness.

All negative behavior probes used synthetic evidence or a mocked snapshot
loader. No secrets, real customer text, or private benchmark question text is
included here. Test artifacts remained under D:.

## Bounded Next Work

1. Repair runtime correctness: R1-R3. Accept only after paired positive/negative
   tests, actual same-process activation/query integration, and existing ACL,
   admission, citation, and identity tests pass. Explicitly define ambiguous
   claim handling and serving-version semantics. Preserve the old experiment.
2. Repair evidence/claims: R4 wording plus R5-R6. One verifiable current entry,
   one canonical checksum contract, real provenance capture. Audit the new
   resume wording against implementation. No reranker hyperparameter search is
   required for these repairs.
3. Connect and validate one useful workflow: authenticated question -> optional
   existing reranker -> admitted evidence -> answer/citations -> trace. Use a
   small frozen acceptance pack covering policy questions, safe account help,
   authorization differences, update/delete, incomplete evidence, and injection.
   Measure answer support, useful completion, false refusal, and full latency.
   Publish fixture results as fixture results; obtain genuinely new labeled
   questions before claiming independent quality. Then stop feature growth.

The default Agent already has bounded search/open execution, evidence state,
budgets, and LLM generation. Its default analyzer/controller are rule driven;
the optional LangGraph/harness work is separate. More LLM planning is not a
prerequisite for fixing the observed failures. After these three bounded work
packages, prioritize a reproducible demonstration and interview understanding
over additional framework breadth.

## Supplemental Review: Evidence Use and Remaining Opportunities

Second pass: 2026-09-05, same business-code HEAD `d27c0f8a68830fd74bbb983567e8b4d50967c0ae`.
Documentation and a synthetic diagnostic script were added in the working tree;
business code was not changed. This supplements R1-R6 instead of replacing them.

The source-level checks covered generation, the default controller/ledger,
navigation, PDF parsing/chunking, model transport, and existing failure reports.
The following probes used admitted synthetic evidence and an injected chat
function, not live model inference or actual customer documents.

### R7 [P1]: Prompt packing drops an aspect without downgrading completeness

Locations: `app/agent/generation_v2.py:29`, `:320`, `:323`, `:235`.

Sources are consumed aspect-by-aspect with a maximum of eight sources and 8,000
serialized record characters. Both matched and context text can duplicate the
same content. The generation result keeps the controller's `answered` mode if
its own generated claims pass, without checking that every required aspect
survived prompt assembly or was covered by those claims.

Reproduced with five ordinary long Policy A hits and one short Policy B hit:

```text
ledger coverage:             1.0
ledger supported aspects:    [Policy A, Policy B]
packed prompt aspects:       [Policy A]
packed source records:       4
published mode/stop reason:  answered/completed
answer mentions Policy B:    false
```

This is a packing/completeness failure, not a measured LLM reasoning failure.
Minimum fix: coverage-aware packing, explicit dropped-aspect accounting, and a
post-generation completeness decision. Do not solve it by increasing every
context budget or treating a claim's citation as proof of full question coverage.

### R8 [P1]: Generation and verification use different evidence views

Locations: `app/agent/generation_v2.py:187`, `:326`, `:338`, `:418`, `:511`;
`app/agent/controller_v2.py:268`, `:289`.

Two opposite failures were reproduced:

- A Guard-admitted `open` result adds the exact fact "Policy A allows 9 remote
  work days per quarter" to the prompt. A generated claim quoting that fact is
  discarded; the verifier receives only original search hits. It returns a
  partial extractive response instead of publishing the newly opened fact.
- A fact at the end of an admitted search hit is absent from the truncated
  prompt record. An injected generation claiming that fact is nevertheless
  accepted because the verifier examines the untruncated hit.

The second case is not unauthorized-data leakage: the full hit was admitted.
It establishes that current citation checks do not prove what evidence was
actually supplied to generation. The first case can suppress correct answers.

Minimum fix: one version-bound evidence packet shared by prompt construction,
verification, and publication, including source-specific open/find locators and
exact delivered spans. If a full-source verification view is intentionally
supported, model-visible and verifier-only evidence must be distinguished;
it cannot silently stand in for a prompt-grounding guarantee.

### R9 [P1]: Conflict fields exist but the default loop does not populate them

Locations: `app/agent/controller_v2.py:252`, `:289`;
`app/agent/evidence_ledger.py:28`, `:43`, `:48`;
`app/agent/evidence_relevance.py:65`.

The default controller admits anchor-related hits as support and calls
`build_ledger` without `conflicts`. The helper supports conflict resolution only
when a caller supplies conflicting evidence. A lexical anchor proves relevance,
not sufficiency or agreement.

A real controller/registry probe with two equally authoritative, active synthetic
records for the same refund rule (7 days versus 30 days) produced:

```text
Guard-admitted hits:          2
ledger relations:            [supports, supports]
conflicting aspects:         []
coverage:                    1.0
terminal mode:               answered
```

This does not show that every conflict evades detection in every project path;
it demonstrates that this default path does not supply that classification.
Minimum fix: separate retrieved/relevant/supported/conflicting states, detect
bounded structured conflicts, use trusted version/effective-time metadata where
applicable, and publish uncertainty for unresolved cases. Do not automatically
pick the higher BGE score as the more authoritative policy.

### R10 [P2]: Final answer and trace can report different outcomes

Locations: `app/agent/generation_v2.py:183`, `:239`, `:253`, `:255`;
`app/agent/runner_v2.py:198`.

The trace is created for the controller's terminal decision before generation.
When generation downgrades to partial or fails, it preserves that trace stop
reason. The synthetic open probe returned `partial/partial_evidence` with
`trace.stop_reason=completed`. An injected transport failure returned
`system/system_error` with the same completed trace.

The API separately sets `request.state.outcome = answer.mode`; this finding
does not mean every API metric falsely records success. The returned agent
trace itself is inconsistent. Broad exception handling also loses useful safe
error categories at the generation layer.

Minimum fix: retain controller decision and final outcome as different fields,
finalize the public trace from the actual response, and expose bounded safe
failure categories. Add partial, invalid JSON, invalid citation, transport,
deadline, and fallback outcome consistency tests.

### R11 [P2]: A historical failure report confuses Top-5 misses with pool misses

Location: `docs/enterprise_eval/ENTERPRISE_FAILURE_ANALYSIS.md:38`.

The report labels 153 zero-Recall@5 cases and concludes reranking cannot recover
them because their gold evidence never reaches Top-5. The inference is invalid:
gold outside final Top-5 may still be in the Top-N reranker candidate pool.
Those 153 cases are final-output misses; the report alone cannot establish
candidate recall or exclude ranking as the cause.

Minimum fix: correct the interpretation while retaining historical counts. New
diagnostics must distinguish index absence, candidate absence, Guard exclusion,
ranking loss, packing loss, generation omission, and publication rejection.
Unknown stages remain unmeasured, not inferred from the final score.

### R12 [P2, Capacity Risk]: Full-index ranking work merits a bounded benchmark

Locations: `app/retrieval/pipeline.py:339`, `:341`;
`app/retrieval/navigation.py:105`.

Dense search requests `faiss_index.ntotal` results before selecting visible
candidates. `find` scans the global chunk map to gather one document's chunks.
These mechanisms are verified in source, but no new scale/latency experiment
was run in this review. They are not evidence that today's workstation API is
already slow because of these operations.

Worthwhile next action: benchmark the existing exact path at representative
sizes and visibility ratios before changing it. A bounded exact candidate
search or snapshot-local document map may avoid unnecessary result allocation.
Blindly replacing `ntotal` with 200 before ACL filtering can destroy recall for
restricted users; preserve exact visible-scope behavior and deterministic ties.
Do not add ANN, a vector service, or cross-user result caches without evidence.

### Source-Verified Limits, Not Proven Quality Causes

- `PdfDocumentParser` emits `tables=[]`, has no OCR, and reports empty pages.
  Parent/child chunks follow per-page sections; the PDF path does not itself
  reconstruct cross-page tables. DOCX/structured-table handling is a different
  path and should not be described as absent.
- Completeness currently opens the document prefix, and generation uses only
  the first 2,000 opened characters. This is not location-centered recovery of
  a fact late in a long document. Check useful new evidence before adding calls.
- Generation does not supply `max_output_tokens` although the transport has
  the option. Existing API request-context timeouts do exist. Verify combined
  deadlines, retries and token budgets; do not claim there is no timeout at all.
- Historical FinanceBench diagnostics found only one parser-risk signal among
  31 failures; numeric/table-shaped questions are not proof of extraction errors.
- V3 reported a 72.38% false-retry rate for its LLM assessor. An additional LLM
  planning step is not justified simply because the project should look agentic.

### Supplemental Validation

Reproducible component probes:

```powershell
& '.\.venv\Scripts\python.exe' -B docs/review/runtime_gaps_probe_20260905.py
```

The five probe functions reproduce R7, both directions of R8, R9 and R10.
The script records actual HEAD and dirty status. Documentation is dirty at this
review; business sources are unchanged. Its outputs describe synthetic accepting
paths, not real-model failure rates.

```powershell
& '.\.venv\Scripts\python.exe' -B -m pytest tests/agent_v2/test_generation_v2.py tests/agent_v2/test_controller_v2.py tests/agent_v2/test_evidence_ledger.py tests/retrieval/test_navigation.py tests/runtime/test_model_transport.py tests/ingestion/test_parsers_office.py tests/ingestion/test_chunking_v2.py tests/security/test_navigation_zero_leak.py -q -p no:cacheprovider --basetemp .private/review_20260905_supplement_pytest
```

Result: 78 passed, three existing SWIG warnings, pytest time 1.05 s. Existing
tests passing alongside these negative probes shows a coverage gap; none of
the findings was fixed by this review. No live model run, full test suite,
production load test, or new independent benchmark was performed.

Public scan after the supplemental artifacts were created: 1,843 candidates,
zero configured-pattern findings. Local Markdown links and UTF-8/whitespace
checks passed. These checks do not establish semantic correctness or security
against threats outside the configured scanner.

### External Design Checks

Only design guidance is taken from these primary sources, not their performance
numbers or an assumption that adopting their framework will improve this repo:

- [Sentence Transformers retrieve and rerank](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html):
  first-stage candidates and final reranked results are separate. This supports
  the corrected R11 diagnostic distinction.
- [Haystack sentence windows](https://docs.haystack.deepset.ai/docs/sentencewindowretriever):
  retrieve surrounding context by location, rather than repeatedly taking the
  beginning of a document. Reuse this project's navigation/ACL/Guard contracts.
- [Lost in the Middle](https://arxiv.org/abs/2307.03172): relevant context position
  can affect model use. This motivates testing packing and ordering, not a claim
  that this repo's observed truncation bug is caused by the paper's mechanism.
- [FAISS query-specific subset selection](https://github.com/facebookresearch/faiss/wiki/Setting-search-parameters-for-one-query):
  evaluate the installed version's exact subset selection before designing a
  new indexing backend. Correctness and latency still require local tests.

The combined plan is
[Runtime correctness and reranker delivery](../roadmap/runtime_correctness_delivery_plan_20260905.md).
