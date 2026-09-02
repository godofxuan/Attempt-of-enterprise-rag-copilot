# UDA R5 Fresh Canary Confirmation

Status: `PROTOCOL_FROZEN_NOT_RUN`

## Why R5 exists

R4 observed a useful page-retrieval gain, but its 64-question validation missed
the preregistered Hit@5 gate and the later canary decision was exploratory. R5
is a new confirmatory experiment for the exact frozen v3 candidate. It does not
rerun or relabel the R4 frozen test.

## Population audit

The pinned UDA FinHybrid file contains 788 reports. The original UDA page
evaluation, R3 selections and R4 reserve together consumed 96 eligible
companies. Those rounds already cover every company with a report containing
at least eight questions.

R5 therefore uses all 41 remaining companies. For each company it chooses the
report with the largest question count, using a SHA-256 tie break, and retains
up to eight questions. This yields 192 questions with 2-7 questions per
company. Selection uses only identity and question-count metadata, not answers
or retrieval outcomes. The public protocol stores only counts and hashes.

## Frozen candidate and baseline

- Baseline: one BGE-M3 Dense query, candidate K=40, at most five chunks per
  document.
- Candidate: the unchanged R4 v3 Dense + original BM25 + focused BM25 page
  fusion, shared visible-scope computation, source top-20, candidate K=80,
  equal lexical weights and RRF K=60.
- Both arms use the same index, model digest, ACL scope, report filter and
  top-five output.
- Per-question arm order is deterministically counterbalanced so one arm does
  not always benefit from warm caches or run first.

## Preregistered promotion gates

Every check must pass:

1. Page Hit@5 improves by at least 2 percentage points.
2. Page nDCG@5 improves by at least 3 percentage points.
3. The 95% company-cluster bootstrap lower bound is positive for both metrics.
4. Candidate-only rescues exceed baseline-only regressions.
5. Candidate p95 latency is no more than 1.15x baseline.
6. Each arm makes exactly one embedding call per question.

Questions from one report are correlated, so the confidence interval resamples
companies rather than pretending all 192 questions are independent. Question-
weighted and company-macro metrics are both published.

Passing authorizes the fixed page-fusion strategy as the default implementation
for explicitly identified finance known-report retrieval. It does not authorize
open-corpus document discovery, non-finance retrieval, answer-accuracy claims,
or bypassing the operator policy allowlist. Failure retains the limited canary.

## Data and parser boundary

Preparation produced 41 PDFs and 192 cases. The parser preview produced 15,045
page-located chunks, zero duplicates and zero structured table chunks. R5 tests
page-text retrieval only. Table-aware extraction remains a separate unverified
hypothesis.

Private questions, answers, company IDs, document IDs, PDFs, source paths and
per-case results stay under `.private` on drive D. Only aggregate evidence and
cryptographic bindings may enter Git.

## Frozen artifacts

- Protocol: `docs/r5/evidence/uda_finance_r5_protocol_v1.json`
- Protocol SHA-256:
  `23ba6ec6be272bf528736743f76b2f069ce93e203d7570b20a5f43e16d1674d5`
- Selection SHA-256:
  `587aab612301b648e189aa8803e61cf60e3ca5c134bba055b1042c6c5faa648d`
- Private cases SHA-256:
  `a703cb7d7abf405c91265f07eca5d0e71072a1eaa83983ab04c8c75a4841d552`
- Private corpus-manifest SHA-256:
  `9a25b42e4e55df56a85979379c1fd47a633268c0858d01646e6a5a769937ff0e`
