# Final Evidence Closure Report

## A. Verdict

`PORTFOLIO_READY_WITH_EXPLICIT_QUALITY_GAPS`

The project is credible as an evaluation, safety and lifecycle engineering
portfolio. It is not production proven, and the current Agent route is not a
quality improvement over its retrieval control.

## B. Frozen baseline

Baseline SHA `02d855d40766af954d5a744a5eb78a9be9438895` on Windows 11 and
Python 3.11.9 produced `1 failed, 3187 passed, 29 skipped, 3 warnings`.
The only failure was the computation-cache pre-lock write race. Baseline raw
logs remain private; sanitized facts are in `00_ENVIRONMENT_AND_BASELINE.md`.

## C. Reliability repairs

1. Computation-cache lock initialization moved under exclusive locking.
2. FTS directory lock became a cross-platform OS file lock.
3. Active pointer gained locked temp cleanup and POSIX directory fsync.
4. Portfolio verifier v2 enforces branch and optional exact SHA.
5. Agent deadline claim was narrowed to cooperative semantics.

No RAG framework, database, model, reranker or Agent was added.

## D. Crash evidence

- FTS: 30/30 hard process terminations recovered; zero corruption, stale-lock
  failures or manual intervention.
- Active pointer: 12/12 hard exits produced a verified old or new snapshot;
  zero mixed/truncated pointer and zero restart failure.
- Power-loss durability: `NOT_RUN`.

## E. Answer and citation evidence

The 60-case WixQA ExpertWritten retrospective subset contains 40 single- and
20 multi-document questions. Control and Agent Recall@5 were both `61.11%`.
Agent citation precision was `43.33%`, citation recall `35.56%`, and
multi-document citation completeness `0/20`. Agent p95 was about `556.18 ms`
versus control `347.40 ms`.

This candidate is rejected. Semantic answer correctness, supported-claim
precision and critical unsupported numeric/date count are `NOT_RUN` because the
immutable source run did not retain answer text. Twelve double-human reviews
remain required before any answer-quality claim.

## F. Security evidence

The existing safe external claim remains the 12-attack combination-disjoint
garak subset: ASR `4/12 -> 0/12`, model exposure `12/12 -> 0/12`, local
Qwen3-8B, one probe subset. A new 60-attack/30-benign independent holdout was
not run because no qualifying immutable dataset exists. Existing custom and
garak runs cannot be pooled across protocols and models.

## G. Rejected candidates

Equal RRF, generic cross-encoder reranking, typed numeric planning, the current
Agent quality route and unjustified Enterprise full-corpus Dense are disabled
or `NOT_RUN`. Exact reasons and metrics are machine-readable in
`evidence/rejected_experiments_v1.json`.

## H. Current bottleneck

The 0/20 multi-document result has now been localized rather than attributed
generically to orchestration. On the consumed 20-case cohort, first loss was
`RETRIEVAL_TOP20_MISS` for 7 cases, `RETRIEVAL_TOP5_MISS` for 10, and
`RESPONSE_BUILDER_CITATION_OMISSION` for 3. Ledger coverage was 1.0 while gold
document coverage was incomplete in 17/20. A diagnostic Gold Retrieval Oracle
passed all gold documents through Guard in 20/20 but still produced 0/20 final
complete citations because the extractive path selected one document per sole
required aspect. Grounding removed no source document. See
`docs/multidoc_attribution/02_RESULTS.md`. The next experiment must separately
test acquisition and multi-evidence representation on development data, then
use a new blind cohort; adding orchestration frameworks is not justified.

## I. Three safest resume metrics

1. garak 12-attack Guard OFF/ON metric, with every narrow qualifier.
2. WixQA 200-question BM25 versus Dense external retrieval metric.
3. EnterpriseRAG-Bench 511,962-row FTS build/size/Recall@5 metric.

The new crash numbers are suitable as supporting engineering evidence, not as
external model-quality metrics.

## J. Forbidden claims

- Agent answer accuracy or quality improvement on the new 60-case subset.
- 100% security, full garak coverage or a new 60/30 security holdout.
- Hard wall-clock Agent cancellation.
- Power-loss-safe Windows activation.
- Production reliability, SLO, HA or third-party reproduction.
- Any pooling of custom synthetic and external security denominators.

## K. Remaining work

Human-only: run two independent reviewers on at least 12 retained-answer cases
after a new immutable run that stores private answer text. Scientific follow-up:
freeze a genuinely unseen 60/30 security holdout before further Guard changes.
Neither is silently treated as complete.

## L. Stop decision

Stop adding features. The repository is already broad; more frameworks would
reduce clarity. Future work is justified only by one of two measured gaps:
multi-document evidence completeness or a genuinely independent security
holdout. Until then, maintain tests, evidence hashes and claim discipline.

## M. Final validation

The final local regression suite passed `3202` tests, skipped `30` explicitly
environment-dependent tests, and emitted three known SWIG deprecation warnings.
The final public-repository audit scanned `1560` candidates and found `0`
potential leaks.
The reproducible Windows command uses `--basetemp .private\t\full`; the short
private path avoids OS path-length failures while preserving the identity
artifact boundary. This is local verification, not third-party reproduction.
