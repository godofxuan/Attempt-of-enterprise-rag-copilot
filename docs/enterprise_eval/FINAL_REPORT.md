# Enterprise-aligned Evaluation Final Report

Closeout baseline: `a5d0356` on branch `codex/rag-eval-system`.

This report closes the enterprise-aligned evaluation round. Experiment numbers
remain bound to their individual execution SHAs and public JSON evidence; the
closeout SHA is not a substitute for those bindings.

## Executive decision

The repository now has two complementary enterprise results:

1. WixQA is the primary resume benchmark because it contains authentic,
   anonymized customer-support questions against a real support knowledge-base
   snapshot. BGE-M3 Dense is the accepted retrieval arm.
2. EnterpriseRAG-Bench is the scale and heterogeneity benchmark. A full-corpus,
   disk-backed lexical baseline ran over all 511,962 official rows, exposing
   semantic and multi-document retrieval as the main unresolved bottlenecks.

The current bounded Agent route is not promoted. On 400 WixQA cases it executed
one search per query, zero `find` calls, and zero `open` calls. It did not improve
retrieval and reduced final multi-article citation completeness to zero while
raising p95 latency. The correct engineering result is
`AGENTIC_ROUTE_REJECTED`, not a cosmetic Agent success claim.

## Reproducibility envelope

| Component | Frozen identity |
|---|---|
| WixQA dataset | revision `d662dc42479c14e202eccd832f8c4b66a035c4cc`; manifest SHA-256 `e40972d7...90dd` |
| WixQA retriever | BGE-M3 model SHA-256 `79076464...6bab`; index manifest `d21b3aa...aa09`; execution `2347346` |
| WixQA Agent | protocol SHA-256 `043625d1...b389`; execution `07b156e` |
| EnterpriseRAG-Bench | revision `69916e31c68aa5963c00248fd7f0bc12d04fd235`; corpus SHA-256 `6b0747bf...a9f` |
| Enterprise FTS5 | artifact SHA-256 `e2de7adf...17cf`; index manifest `046f37d2...d350`; execution `955d86f` |
| Enterprise failure analysis | taxonomy SHA-256 `52157461...316`; analysis `ad30052` |

Private raw data and indexes remain under `.private/external` on `D:` and are
excluded from Git. Public evidence contains aggregate metrics and cryptographic
bindings, not benchmark labels or private case details.

## 1. Primary enterprise benchmark

**WixQA ExpertWritten is the primary benchmark for the project story.** Its 200
questions are the closest available evidence for a customer-support knowledge
copilot. It is a fixed public-label external benchmark, not a hidden or blind
holdout. EnterpriseRAG-Bench is the secondary scale/heterogeneity track.

## 2. WixQA results

### ExpertWritten, 200 fixed external questions

| Arm | Recall@5 | MRR@5 | nDCG@5 | Multi-article complete@5 | p95 |
|---|---:|---:|---:|---:|---:|
| BM25 | 42.75% | 31.16% | 32.15% | 11.54% | 151.8 ms |
| BGE-M3 Dense | **66.42%** | **49.61%** | **52.16%** | **30.77%** | **157.4 ms** |
| Equal RRF | 59.25% | 45.89% | 47.16% | 19.23% | 304.6 ms |

Dense improved Recall@5 by 23.67 percentage points and nDCG@5 by 20.01 points
over BM25 for only 5.6 ms additional p95 latency. Equal-weight RRF was rejected:
it was worse than Dense on all reported quality metrics and used 1.94x Dense p95.

The Synthetic result of 97.88% Dense Recall@5 is useful only for development.
It is much easier than ExpertWritten and is forbidden as the headline result.

## 3. EnterpriseRAG-Bench full-scale status

The full official corpus was acquired and verified: 511,962 rows across Slack,
Gmail, Linear, Drive, HubSpot, Fireflies, GitHub, Jira, and Confluence. The formal
full-corpus B0 FTS5 arm completed. The B1 Dense, B2 RRF, and B3 Agent arms are
`NOT_RUN`, so a full B0/B1/B2/B3 comparison does not exist.

The 1.37 GiB FTS5 index built in 231.35 seconds with approximately 1.83 GiB peak
working set. This replaced an unsafe in-memory BM25 design estimated at 36.60
GiB of Python token objects. This is a measured industrial capacity improvement,
not a retrieval-quality improvement against another arm.

Full-corpus B0 retrieval on all 470 document-grounded questions produced:

- Macro document Recall@5: **60.37%**
- MRR@5: **57.96%**
- nDCG@5: **55.89%**
- Multi-document completeness@5: **28.26%** across 92 multi-document cases
- mean / p50 / p95 latency: **1101.3 / 1004.4 / 1821.0 ms**

## 4. HERB and Agentic retrieval

HERB is `LICENSE_AND_CAPACITY_BLOCKED` and was not run. It therefore proves
nothing about this Agent. WixQA supplied the same-retriever Agent comparison,
and that comparison rejected the current route.

## 5. BM25, Dense, and RRF on enterprise data

WixQA provides the only complete three-arm comparison. Dense wins; BM25 is a
useful lexical control; equal RRF is not Pareto competitive. EnterpriseRAG-Bench
currently has only the full-corpus BM25/FTS5 arm. It would be false to transfer
the WixQA Dense/RRF ordering to the heterogeneous corpus without running it.

## 6. Does bounded Agent beat single-shot RAG?

No. On WixQA Simulated and ExpertWritten, Agent search-evidence recall exactly
equaled B2 RRF Recall@5: 52.92% and 59.25%. The controller made one search and no
`find/open` calls on every case. Multi-article citation completeness was 0% on
both cohorts, while p95 latency rose 1.59x and 1.47x. Answer correctness was
`NOT_MEASURED`, so the 99.5-100% answered rate is not an accuracy metric.

## 7. Largest failure category

On EnterpriseRAG-Bench B0, 153/470 cases (32.55%) are `RETRIEVAL_MISS`, followed
by 59 `MULTI_DOC_INCOMPLETE` and 58 `WRONG_DOCUMENT`. Semantic questions account
for 80 of the 153 misses and have only 36.00% Recall@5. Project-related questions
account for 34 of the 59 incomplete cases. This supports a future sharded Dense
candidate before a reranker: a reranker cannot recover documents absent from the
candidate set.

## 8. Source-aware chunking

`NOT_RUN`. Adapters preserve source identity and the design is documented, but
there is no paired flat-versus-source-aware score. EnterpriseRAG-Bench exposes
only document-level title/content fields, not rich Slack threads, email order,
or timestamps, so fabricating that structure would violate provenance.

## 9. Evidence Ledger for conflict/completeness

`NOT_PROVED_EXTERNALLY`. The mechanism ran in the WixQA Agent path, but final
selection collapsed evidence to one cited source and multi-article citation
completeness was 0%. EnterpriseRAG conflicting-document retrieval completeness
was 78.95%, but answer conflict acknowledgement and Ledger ON/OFF were not
measured. Retrieval availability must not be presented as conflict resolution.

## 10. Refusal on unanswerable cases

`NOT_MEASURED` in this enterprise external round. EnterpriseRAG information-not-
found questions were excluded from retrieval metrics because they have no gold
document. Existing synthetic and security refusal tests remain valid mechanism
evidence but do not establish external enterprise refusal precision/recall.

## 11. PDF/table bottleneck

PDF/table handling remains a separate complex-document stress track. It is not
the dominant failure observed in WixQA or EnterpriseRAG-Bench, which are HTML or
record-like corpora. The current enterprise bottlenecks are semantic discovery
and multi-document completeness. Parser metrics cannot substitute for QA metrics.

## 12. FinQA and UDA disposition

Retain both as secondary stress evidence. FinQA tests numerical reasoning and
table/text grounding; UDA tests known-report page localization. Neither should
drive the primary enterprise product story or trigger more feature development
unless a target job specifically requires financial-document QA.

## 13. Three safest resume metrics

1. **WixQA ExpertWritten Dense:** 66.42% Recall@5 and 52.16% nDCG@5 on 200
   authentic anonymized support questions, versus BM25 42.75% and 32.15%.
2. **Enterprise full-scale engineering:** built and queried a verified 511,962-
   row heterogeneous corpus with a 1.37 GiB resumable FTS5 index in 231.35 s at
   about 1.83 GiB peak memory; measured 60.37% Recall@5 on 470 questions.
3. **External retrieved-content defense:** existing pinned garak subset result,
   Guard OFF/ON attack success 4/12 to 0/12 and exposure 12/12 to 0/12, with all
   small-subset qualifiers retained.

## 14. Forbidden resume metrics

- WixQA Synthetic 97.88% as the project accuracy.
- Enterprise 60.37% Recall@5 as answer correctness or end-to-end accuracy.
- WixQA Agent 99.5-100% answered rate as answer accuracy.
- A claim that RRF, source-aware chunking, Evidence Ledger, refusal, or the Agent
  improved external quality when the paired experiment is rejected or not run.
- A claim that HERB, full Enterprise Dense/RRF/Agent, a hidden holdout, human
  review, production traffic, SLO, or cross-domain generalization was completed.
- `0% false-positive rate` from a denominator of two; report `0/2` instead.

## 15. Stop or continue feature development?

**Stop broad feature development.** The project already demonstrates more than
enough architecture. Further value comes from learning, interview preparation,
independent reproduction, and one narrowly preregistered experiment only when
resources permit: sharded Dense retrieval on a development-safe EnterpriseRAG
protocol. A source-aware or bounded multi-document candidate is justified only
after its target failure can be isolated without reusing the consumed public test
as a tuning set. No new framework is justified by the current evidence.

## Final Go/No-Go table

| Candidate | Decision | Reason |
|---|---|---|
| WixQA BGE-M3 Dense | GO as retrieval baseline | clear quality gain over BM25 with nearly equal p95 |
| Equal-weight RRF | NO-GO | lower quality and 1.94x p95 versus Dense |
| Current bounded Agent | NO-GO | no additional tools/evidence, citation collapse, added latency |
| Enterprise FTS5 | GO as reproducible B0/capacity control | full corpus fits and runs; quality/latency remain baseline-only |
| Enterprise Dense | FUTURE EXPERIMENT | directly targets semantic misses, but costs about 11.39 h embedding at measured rate |
| Source-aware chunking | NOT_RUN | no paired evidence and insufficient official structure for several sources |
| HERB | NOT_RUN | license/resource qualification not completed |

Primary evidence: `ENTERPRISE_BASELINE.md`, `ENTERPRISE_FAILURE_ANALYSIS.md`,
`NEGATIVE_RESULTS.md`, `EXPERIMENT_REGISTRY.md`, and JSON files under `evidence/`.

## Closeout verification

- Enterprise-focused contracts: `8 passed`.
- Full repository: `3147 passed, 30 skipped, 3 known SWIG warnings`.
- Public repository audit: `1489 candidates, 0 findings`.
- `git diff --check`: passed.

The full suite was run with `TEMP` and `TMP` directed to `.private/test_tmp` on
`D:`. A prior sandboxed run produced one Windows `PermissionError` in an existing
multi-process byte-lock test; the isolated test and the full suite passed outside
the restricted sandbox. No cache-lock production change was made from that
environment-specific failure.
