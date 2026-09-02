# UDA R4 Hierarchical Retrieval Engineering Journal

Status: original gate `VALIDATION_REJECTED_TEST_FORBIDDEN`; later rollout
decision `LIMITED_CANARY_APPROVED`

## Objective and evidence boundary

R4 tested whether page-aware multi-channel retrieval could improve the weak
known-report financial page-localization result without adding another model.
The experiment used 28 companies that had not entered the earlier R3 cohorts:
12 companies/96 questions for development, 8/64 for validation and 8/64 for a
frozen test. Company, document and question identities are disjoint.

The public UDA labels are not blind. They are treated as a fixed public-label
protocol with one-shot validation and test ledgers. Private questions, answers,
company IDs, PDFs, paths and per-case failures remain under `.private` on drive
D. Only aggregate evidence is checked into Git.

## Frozen inputs

- UDA-Benchmark Git revision:
  `fca5237ac316e776d8dbccffa55ca29c0efdc185`
- UDA-QA revision: `d4367103fe8fe86b3bb76c66be8eafc4fb4117b2`
- Selection SHA-256:
  `4ec7a555985f0031ae2ac28405e2e45e4706bbffb59b54a721e8ae088d6c0abe`
- Index manifest SHA-256:
  `3697fd99110f1b87f7bc039a0ef8097ef7f66577eeaef1c8e6f3001d8bf82a0e`
- Final protocol SHA-256:
  `eaa8044a45ec6e597081579c0211c2bc07f7ccb1103160b8bc6888ac304fd631`
- Evaluation Git SHA: `c128c7a23fc1aea78b2a7c288a5a2a5f1d4a9909`

The parser produced 10,383 page-located chunks from 28 PDFs. It produced zero
structured table chunks, so this experiment tests page text retrieval, not a
table-structure parser.

## Implementation path

### Candidate v1: focused lexical rescue

`focus_financial_query()` removes question scaffolding such as "what was the
percentage change" while retaining entities, financial metrics and years.
`FocusedPageFusionPipeline` runs the original BGE-M3 Dense query and the focused
BM25 query, deduplicates chunk hits by `(doc_id, page)` and applies weighted RRF.
It returns original `SearchHit` objects, preserving locators, ACL metadata and
source provenance.

Development result: Hit@5 +4.17pp, nDCG@5 +6.93pp, p95 1.814x. It failed the
+5pp Hit@5 and 1.5x latency gates. Validation was not run.

### Candidate v2: dual BM25 coverage

A development-only mechanism probe showed that original and focused BM25
rescued different pages. v2 retained one Dense embedding and added both lexical
rankings with weights 0.5/0.5. Three complete searches were first run in
parallel.

Quality passed on development, but p95 reached 2.304x. Parallel execution made
CPU/index work contend with the local embedding request; it did not remove the
repeated work. Scoring BM25 only on ACL/metadata-visible indices reduced p95 to
1.700x but still failed.

### Candidate v3: reuse the trusted visible scope

`HybridRetrievalPipeline.search_many_same_scope()` now validates that every
request has exactly the same `UserContext` and `QueryFilters`, computes ACL and
metadata visibility once, and reuses the immutable scope across channels.
`_rank_bm25()` calls `get_batch_scores()` for only those visible indices. Dense
still performs exactly one BGE-M3 call. This changes work performed, not the
ranking formula for any eligible candidate.

The first implementation passed a tuple to `rank-bm25 0.2.2`; NumPy interpreted
the tuple as multidimensional indexing and raised `IndexError`. The retrieval
regression suite found it before a formal run. The boundary now converts the
immutable tuple to the list required by that dependency.

v3 development result: Hit@5 `83.33% -> 88.54%`, nDCG@5
`66.82% -> 73.95%`, p95 `112.68 -> 117.29 ms` (1.041x). All registered
development gates passed.

## Evaluation-control repair

The original script made validation/test one-shot, but it did not mechanically
prove that validation used the same code and protocol as a passing development
run. `require_development_authorization()` now verifies the development
manifest and arm hashes, exact Git SHA, protocol hash, dev case hash and all
three gates before creating the validation execution marker. Test execution
still requires a completed validation marker with the exact authorization
decision.

## Independent validation

On 64 company-disjoint validation questions:

| Metric | Dense baseline | Candidate | Delta |
|---|---:|---:|---:|
| Page Hit@5 | 76.5625% | 81.2500% | +4.6875pp |
| Page nDCG@5 | 64.4133% | 72.6128% | +8.1994pp |
| p95 latency | 112.65 ms | 120.06 ms | 1.0658x |

The gate was conjunctive: Hit@5 delta >=5pp, nDCG@5 delta >=3pp and p95 <=1.5x.
Hit@5 missed by 0.3125pp. The recorded decision is
`VALIDATION_REJECTED_TEST_FORBIDDEN`; the 64-question test was not executed.

## Post-hoc paired review and limited canary

The 5pp threshold was a conservative release rule, not a definition of whether
the observed change had value. It would be wrong to rewrite that rule after
seeing validation, but it would also be wasteful to discard a candidate solely
because `3/64` net additional hits equals 4.6875pp rather than 5pp.

A later exploratory review compared every validation case under both arms:

| Paired outcome | Cases |
|---|---:|
| Hit in both arms | 46 |
| Candidate-only hit (rescue) | 6 |
| Baseline-only hit (regression) | 3 |
| Miss in both arms | 9 |

Misses fell from `15` to `12`, a 20% relative reduction. A fixed-seed 100,000
sample paired bootstrap estimated the Hit@5 delta at `+4.6875pp` with a 95%
interval of `-4.6875pp to +14.0625pp`; the exact two-sided McNemar p-value was
`0.5078`. Hit improvement therefore remains uncertain. The nDCG@5 delta was
`+8.1994pp`, with a paired bootstrap 95% interval of `+1.5773pp to +15.0354pp`,
so the ordering improvement is the more stable signal.

This review did **not** retroactively pass the original gate and did not unlock
the frozen test. It approved the exact v3 configuration only as the explicit
`finance_known_report_page_fusion_v1` canary. The application default is
unchanged. Operators must set
`RETRIEVAL_PROFILE=finance_known_report_page_fusion_v1`, and the wrapper still
requires `RETRIEVAL_CANARY_POLICY_IDS` as an operator-owned allowlist. It
activates only when the request has exactly one server-validated `policy_id`
and that ID is allowlisted; missing or stale configuration fails closed.
Its ranked candidate pool continues through the existing Retrieved-content
Guard; broad or unbound requests fall back to the default pipeline. Expanding beyond that scope requires a fresh company-disjoint
cohort; the old validation and frozen test cannot be relabeled as new evidence.

That exit requirement was later satisfied by the separate R5 protocol. R5 did
not alter this R4 decision or run this frozen test; it used all 41 remaining
previously unused UDA companies and confirmed the unchanged candidate on 192
questions. See `docs/r5/ENGINEERING_JOURNAL.md`.

## What improved and what did not

The work established a repeatable quality mechanism and removed most of its
runtime overhead. It did not establish a global-default external quality gain.
The correct conclusion is that focused lexical evidence improves ordering and
often page coverage, while Hit@5 needs fresh confirmation. That is enough for a
bounded canary, not for a broad production or test-quality claim.

The next quality round must use a genuinely new evaluation population. R4
validation/test cannot be repartitioned or rerun as a new independent claim.
The clearest remaining product limitation is structured table understanding:
the R4 PDF ingestion produced no structured table chunks. That hypothesis must
be tested on new data with a paired parser protocol before replacing ingestion.

## Evidence and reproduction

- Protocol: `docs/r4/evidence/uda_finance_r4_protocol_v3.json`
- Aggregate public evidence: `docs/r4/evidence/uda_finance_r4_public_v1.json`
- Paired canary review: `docs/r4/evidence/uda_finance_r4_canary_review_v1.json`
- Canary review SHA-256:
  `dc8db412fa9b57ca0e3c05390f832783253b2801965851afb6c294b1064683b3`
- Public evidence SHA-256:
  `730eff46cdb82e56254c3c9bce63baa41bafbd216c4323b4e67bb69bc60fa2e7`
- Core tests: `tests/external_datasets/test_uda_finance_hierarchical.py`,
  `tests/external_datasets/test_uda_finance_r4_eval.py`,
  `tests/external_datasets/test_uda_finance_r4_public.py` and
  `tests/retrieval/test_pipeline_ranking.py`

Private replay requires the pinned PDFs, prepared cases, index and local
`bge-m3` model. Public verification does not require private case content.
