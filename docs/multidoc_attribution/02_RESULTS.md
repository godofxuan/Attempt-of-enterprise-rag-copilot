# Multi-document Evidence Failure Attribution Results

## 1. Access / HEAD

- Branch: `codex/rag-eval-system`
- Starting SHA: `38d81b835abedbcc5aa2277e91502df6ad1c1254`
- Diagnostic execution SHA: `122bef3672dac07bc76e6686ce0f4e67b14b16b9`
- OS: Windows 11 Pro 64-bit, build `10.0.26200`
- Python: `3.11.9`
- Run: `wixqa-multidoc-attribution-v3`
- Runtime: `24,238.388 ms` for 20 current-path and 20 Gold Retrieval
  Oracle executions
- Serving behavior change: `false`

The evidence binds to the committed diagnostic execution SHA. Later commits
only add verification, documentation, and checked-in evidence.

## 2. Baseline

At the starting SHA:

| Command | Result | Runtime |
| --- | --- | ---: |
| `python -m pip check` | pass | 3.9 s |
| `python -m compileall -q app scripts tests` | pass | 3.9 s |
| `python -m pytest -q --basetemp .private\\t\\multidoc-baseline` | 1 failed, 3201 passed, 30 skipped, 3 warnings | 226.53 s |
| isolated failed test, 10 separate reruns | 10 passed, 0 failed | local reruns |
| `python -m scripts.verify_portfolio_release --expected-sha <starting-sha>` | VERIFIED, 5/5 gates | local |

The one full-suite failure was a Windows `PermissionError` while replacing a
staged WixQA flat-index directory. It did not reproduce in ten isolated runs,
so this stage records it as a baseline order/timing transient rather than
silently claiming that every baseline test passed. No production fix was made
without a deterministic reproducer.

## 3. Current 60-case evidence revalidation

The frozen protocol really contains 60 distinct ExpertWritten cases:

- 40 single-document cases.
- 20 multi-document cases.
- Of the 20 multi-document cases, 18 require 2 distinct articles and 2 require
  3 distinct articles.

The immutable source evidence remains:

| Metric | Control | Agent candidate |
| --- | ---: | ---: |
| Retrieval Recall@5 | 61.11% | 61.11% |
| Citation precision | n/a | 43.33% |
| Citation recall | n/a | 35.56% |
| Multi-document citation complete | n/a | 0/20 |
| p50 latency | 259.00 ms | 392.60 ms |
| p95 latency | 347.40 ms | 556.18 ms |

Answer correctness and human review remain `NOT_RUN`. The source run retained
IDs and metrics, not answer text suitable for semantic scoring.

Source: `docs/final_evidence_closure/evidence/answer_citation_60_automated_v1.json`.

## 4. Evaluator validation

Verdict: `VALID`.

- All 20 frozen question hashes and answer hashes match the source dataset.
- Every gold article ID resolves to the verified WixQA corpus.
- Every multi-document row has at least two distinct physical article IDs.
- There are no duplicate gold IDs inside a case.
- The evaluator compares article/document IDs, not chunk IDs.
- Complete means `gold IDs subset-of cited IDs`; one of two gold articles is
  correctly scored as incomplete.
- The source details hash is still
  `9730ff5b0b0e377f3b202a807c82b2ca77fbd9d53340798fc279c3d18d095e16`.

No evaluator correctness bug was found, so the old 0/20 artifact is retained.

## 5. Query analysis and controller

| Observation | Cases |
| --- | ---: |
| `intent=fact` | 16/20 |
| `intent=process` | 4/20 |
| `required_aspects=['answer']` | 16/20 |
| `required_aspects=['process_steps']` | 4/20 |
| exactly one required aspect | 20/20 |
| one search call | 20/20 |
| any find call | 0/20 |
| any open call | 0/20 |
| Controller terminal `answer/completed` | 20/20 |

Observed flow:

```text
one required aspect -> one search -> Ledger coverage 1.0 -> answer/completed
```

The Controller is behaving according to its current contract. The contract
does not express "this answer requires two or three distinct documents".

## 6. Retrieval all-gold coverage

`mean gold recall` counts the fraction of required gold documents found per
case. `all-gold complete` is stricter: every required document must be present.

| k | All-gold complete | Partial | Zero | Mean gold recall |
| ---: | ---: | ---: | ---: | ---: |
| 5 | 3/20 (15%) | 14/20 (70%) | 3/20 (15%) | 48.33% |
| 10 | 9/20 (45%) | 9/20 (45%) | 2/20 (10%) | 66.67% |
| 20 | 13/20 (65%) | 6/20 (30%) | 1/20 (5%) | 79.17% |

This explains why an average Recall@5 can look non-zero while completeness is
zero: partial retrieval receives partial credit, but a multi-document answer
needs the whole set.

## 7. First-loss attribution

| First-loss stage | Cases | Percentage |
| --- | ---: | ---: |
| `RETRIEVAL_TOP20_MISS` | 7 | 35% |
| `RETRIEVAL_TOP5_MISS` | 10 | 50% |
| `RESPONSE_BUILDER_CITATION_OMISSION` | 3 | 15% |
| ACL | 0 | 0% |
| Guard | 0 | 0% |
| Ledger assembly | 0 | 0% |
| Grounding document removal | 0 | 0% |
| Evaluator mismatch | 0 | 0% |
| Unknown | 0 | 0% |

The primary first-loss family is retrieval acquisition/selection: 17/20 cases
lose required evidence before the Controller receives its Top-5 search result.
The remaining 3/20 reach the response builder with all gold documents, then
lose completeness because `ExtractiveResponseBuilder` defaults to one evidence
item per aspect.

## 8. Case matrix

Values are gold-document coverage at each stage. Case labels are shortened
pseudonymous WixQA IDs; no question or answer text is public.

| Case | Gold | @5 | @20 | Guard | Ledger | Selected | Final | First loss |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 0f74c25a | 2 | 0.50 | 1.00 | 0.50 | 0.50 | 0.50 | 0.50 | `RETRIEVAL_TOP5_MISS` |
| 101d32e2 | 2 | 0.50 | 1.00 | 0.50 | 0.50 | 0.00 | 0.00 | `RETRIEVAL_TOP5_MISS` |
| 1df17928 | 2 | 0.50 | 1.00 | 0.50 | 0.50 | 0.00 | 0.00 | `RETRIEVAL_TOP5_MISS` |
| 3b60ed66 | 2 | 0.50 | 0.50 | 0.50 | 0.50 | 0.00 | 0.00 | `RETRIEVAL_TOP20_MISS` |
| 48756571 | 2 | 0.50 | 1.00 | 0.50 | 0.50 | 0.50 | 0.50 | `RETRIEVAL_TOP5_MISS` |
| 4d86e2bd | 2 | 0.50 | 1.00 | 0.50 | 0.50 | 0.50 | 0.50 | `RETRIEVAL_TOP5_MISS` |
| 6e443614 | 2 | 0.50 | 0.50 | 0.50 | 0.50 | 0.50 | 0.50 | `RETRIEVAL_TOP20_MISS` |
| 7a66bb71 | 2 | 0.50 | 1.00 | 0.50 | 0.50 | 0.50 | 0.50 | `RETRIEVAL_TOP5_MISS` |
| 7b927a38 | 2 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | `RETRIEVAL_TOP20_MISS` |
| 80fe3347 | 2 | 0.50 | 1.00 | 0.50 | 0.50 | 0.50 | 0.50 | `RETRIEVAL_TOP5_MISS` |
| 9d7b6cf7 | 2 | 0.50 | 0.50 | 0.50 | 0.50 | 0.00 | 0.00 | `RETRIEVAL_TOP20_MISS` |
| a9260629 | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 0.50 | 0.50 | `RESPONSE_BUILDER_CITATION_OMISSION` |
| aa280bde | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | `RESPONSE_BUILDER_CITATION_OMISSION` |
| ac0cca09 | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 0.50 | 0.50 | `RESPONSE_BUILDER_CITATION_OMISSION` |
| b1a85c51 | 2 | 0.00 | 0.50 | 0.00 | 0.00 | 0.00 | 0.00 | `RETRIEVAL_TOP20_MISS` |
| c9a62133 | 2 | 0.00 | 0.50 | 0.00 | 0.00 | 0.00 | 0.00 | `RETRIEVAL_TOP20_MISS` |
| d9162d54 | 3 | 0.33 | 0.33 | 0.33 | 0.33 | 0.00 | 0.00 | `RETRIEVAL_TOP20_MISS` |
| e25e3df2 | 2 | 0.50 | 1.00 | 0.50 | 0.50 | 0.00 | 0.00 | `RETRIEVAL_TOP5_MISS` |
| e47a3af2 | 2 | 0.50 | 1.00 | 0.50 | 0.50 | 0.00 | 0.00 | `RETRIEVAL_TOP5_MISS` |
| ef977059 | 3 | 0.33 | 1.00 | 0.33 | 0.33 | 0.33 | 0.33 | `RETRIEVAL_TOP5_MISS` |

The machine-readable matrix preserves full stage document sets and is the
authoritative source.

## 9. Ledger representation test

- Ledger coverage is `1.0` in 20/20 cases.
- Ledger coverage is `1.0` while gold-document completeness is below `1.0` in
  17/20 cases.
- Result: `SUPPORTED_REPRESENTATION_GAP` relative to this benchmark.

This does not mean `evidence_ledger.py` violates its own implementation
contract. The Ledger computes supported required aspects. Because every query
has exactly one required aspect, any supporting hit can satisfy 1/1 aspects.
The benchmark's separate contract requires 2 or 3 distinct gold documents.

## 10. Oracle probes

### Gold Retrieval Oracle

`DIAGNOSTIC_ONLY`:

- All gold documents survive Guard: 20/20.
- Final all-gold citations: 0/20.
- Response builder selects exactly one document in 20/20 oracle cases.

This supports two causal statements: retrieval is a real bottleneck in the
normal run, but retrieval repair alone cannot solve completeness under the
current one-aspect/one-evidence response contract.

### Gold Prompt Oracle

`NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE`.

The source run constructed answers with `ExtractiveResponseBuilder` and made
zero generation-model calls. Calling a new LLM now would create a different
pipeline, not diagnose the frozen run.

### Grounding diagnostic

- Pre/post-gate source-set removal: 0/20.
- Controller terminal outcome: `answer/completed` in 20/20.
- Final response downgrade: 1/20.
- Deterministic reason: `negation_mismatch`.

The gate affected one response mode but did not remove a source document and
did not cause the 0/20 completeness result.

## 11. Root-cause assessment

### OBSERVED

- Source and current replay both produce 0/20 complete citations.
- All 20 cases use one search and no find/open.
- All 20 cases expose one required aspect and Ledger coverage 1.0.
- First-loss distribution is 7 Top-20, 10 Top-5, 3 response builder.
- Guard removes no gold document ID; grounding removes no source document ID.

### DERIVED

- 17/20 (85%) first lose completeness in retrieval acquisition/selection.
- 17/20 show Ledger 1.0 despite incomplete benchmark-required document sets.
- Top-20 all-gold completeness is 13/20, 50 percentage points above Top-5's
  3/20, but that is a diagnostic depth comparison, not a proposed top-k change.

### SUPPORTED

- Primary bottleneck: retrieval acquisition and Top-5 selection.
- Secondary bottleneck: one-aspect/one-evidence response representation.
- Retrieval-only repair is insufficient: Gold Retrieval Oracle still ends 0/20.

### INFERRED

- A future candidate likely needs both better multi-document candidate
  acquisition and an explicit multi-evidence completeness contract.
- It is not yet known whether query decomposition, a reranker, or another
  bounded mechanism is the smallest effective acquisition change.

### REJECTED

- Evaluator bug.
- ACL as the cause.
- Guard as the cause.
- LLM generator citation omission: no generator ran.
- Grounding document removal as the cause.

### UNKNOWN

- Semantic answer correctness and human agreement.
- Performance on a new blind multi-document cohort after any candidate change.

## 12. Top failure modes

1. Top-5 selection loss, 10/20. All gold exists within Top-20 but at least one
   required document is outside Top-5.
2. Top-20 acquisition miss, 7/20. At least one required document is absent even
   from the 20-candidate diagnostic pool.
3. Response-builder omission, 3/20. All gold reaches Ledger, but the default
   `max_evidence_per_aspect=1` selects at most one document for the sole aspect.

## 13. Resume / interview value

Safe statement:

> Built hash-bound stage-level failure attribution for 20 consumed
> multi-document WixQA cases, localized 17/20 first losses to retrieval
> acquisition/Top-5 selection and 3/20 to extractive response selection, and
> verified all aggregate metrics from public case evidence without changing
> serving behavior.

This is a debugging/evaluation engineering result, not a quality improvement
metric. It is useful as supporting interview evidence, not one of the three
primary resume outcome numbers.

## 14. Forbidden claims

- Multi-document RAG is solved.
- Agent quality or answer accuracy improved.
- 0/20 was caused by an LLM generator.
- Guard blocked benign gold evidence.
- Increasing top-k to 20 would produce 65% final completeness.
- The Gold Retrieval Oracle is a production benchmark.
- The system is production-ready or universally grounded.

## 15. Final decision

```text
ATTRIBUTION_COMPLETE_NO_OPTIMIZATION
NEXT_BOTTLENECK_MIXED
```

The bottleneck is mixed but ordered: retrieval acquisition/selection is the
primary first-loss location; response representation is a proven downstream
blocker once retrieval is made complete. No candidate is implemented here.

