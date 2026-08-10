# Multi-document RAG Long-term Plan and Candidate Protocol

## 1. Why this stage exists

The 20-case ExpertWritten attribution established two ordered failures:

- 17/20 first lose required evidence in Top-20 acquisition or Top-5 selection.
- 3/20 reach the response builder complete and then lose evidence because the
  current extractive path selects one item for the sole required aspect.

An earlier 27-case Simulated experiment already tested the naive response:
raise `max_evidence_per_aspect` from 1 to 5. Completeness improved from 0% to
22.22%, but citation precision fell from 44.44% to 18.52%. That candidate is
not repeated and remains `PRECISION_REVIEW_REQUIRED`.

This stage tests whether bounded query decomposition plus selective evidence
choice can address both failures without citing every retrieved document.

## 2. Long-term roadmap

| Phase | Goal | Entry gate | Exit gate |
| --- | --- | --- | --- |
| L0 Attribution | Locate first evidence loss | frozen negative result | complete: 20/20 replay, 0 unknown |
| L1 Candidate development | Test one bounded causal mechanism | consumed development cohort only | pre-registered quality/cost gate |
| L2 Fixed validation | Evaluate frozen candidate outside tuning cohort | candidate code/config frozen | no regression and reproducible gain |
| L3 Default-off integration | Wire one typed policy behind configuration | L2 pass | ACL/Guard/trace/fallback contracts pass |
| L4 Shadow operation | Observe cost, errors and drift without changing answers | L3 pass | operational budget and rollback evidence |
| L5 Human quality review | Review answer/citation semantics | retained private outputs and two reviewers | calibrated agreement and adjudication |
| L6 Release decision | Consider changing default | L2-L5 all pass | explicit release or permanent rejection |

No framework, vector database, model, reranker, or extra Agent is admitted by
this plan. Every phase may end in `NO_GO`.

## 3. Cohort and claim boundary

- Cohort: the same 20 ExpertWritten multi-document cases already used for
  attribution.
- Status: `RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED`.
- Allowed use: diagnosis and candidate development.
- Forbidden use: final validation, resume quality uplift, production accuracy.
- A passing result can only produce
  `DEVELOPMENT_CANDIDATE_HOLD_FOR_FIXED_VALIDATION`.

## 4. Frozen four-arm design

The two factors are candidate acquisition and response selection.

| Arm | Acquisition | Selection |
| --- | --- | --- |
| A `current` | original question ranking | first admitted evidence only |
| B `decompose_only` | bounded original + clause-query fusion | first admitted evidence only |
| C `select_only` | original question Top-5 | one preferred admitted document per bounded query variant |
| D `combined` | bounded original + clause-query fusion | one preferred admitted document per bounded query variant |

The experiment changes only evaluation objects. Production defaults remain the
current single-query, one-evidence path.

## 5. Deterministic decomposition contract

1. Always retain the original normalized question.
2. Split only on explicit English separators: `and`, `or`, `versus`, `vs`,
   semicolon, or comma.
3. Keep only clauses with at least three alphanumeric tokens.
4. Require at least two valid clauses before enabling decomposition.
5. Return at most two clause queries plus the original query: maximum three.
6. Never inspect gold documents, answers, source titles, or retrieved text when
   constructing query variants.

This is deliberately narrow. It is not an LLM planner and makes no claim to
understand implicit multi-hop questions.

## 6. Candidate acquisition

Each query variant uses the unchanged WixQA BM25 + BGE-M3 dense ranking and the
same RRF constant as the active immutable index. Variant rankings are fused by
the existing deterministic RRF function. The Agent still makes one typed
search call; the candidate arm records the number of internal query rankings
and embedding calls separately.

## 7. Selective response contract

For each query variant, choose its highest-ranked document that survived ACL
and Guard in the Agent's admitted Top-5. Deduplicate document IDs and stop at
three. If no preferred document survives, fall back to the first admitted
evidence. The normal extractive claim and deterministic citation verifier are
then reused.

This differs from the rejected max-five candidate: it does not cite every
admitted Top-5 document.

## 8. Frozen metrics

Per arm:

- retrieval all-gold completeness;
- citation completeness, recall, and precision;
- answered/partial/source-free counts;
- selected sources per answer;
- query variants and embedding calls;
- search/find/open calls and tool errors;
- Guard quarantine and filtered counts;
- mean, p50, and p95 wall-clock latency.

Paired case transitions must list fixes, regressions, and unchanged failures.

## 9. Pre-registered development gate

Arm D may become a frozen development candidate only if all are true:

1. citation completeness improves by at least 15 percentage points over A;
2. citation recall improves by at least 15 percentage points;
3. citation precision is no more than 10 percentage points below A;
4. there are at least 3 paired fixes and 0 paired regressions;
5. p95 latency is at most 2.0 times A;
6. mean selected sources are at most 3;
7. tool errors and budget exhaustion are zero;
8. Guard/ACL are enabled and no production file is modified.

Failure produces `DEVELOPMENT_CANDIDATE_REJECTED`. Passing produces only
`DEVELOPMENT_CANDIDATE_HOLD_FOR_FIXED_VALIDATION`.

## 10. Stop rules

- Do not tune separators, query count, source count, or thresholds after seeing
  the 20-case result.
- Do not run a blind/fixed test in this same change.
- Do not modify `app/agent/query_analysis.py`, `controller_v2.py`,
  `evidence_ledger.py`, `runner_v2.py`, Guard, ACL, or retrieval defaults.
- Do not promote a candidate that passes completeness by reproducing the old
  precision collapse.
- Stop after one four-arm run and publish positive or negative evidence.

