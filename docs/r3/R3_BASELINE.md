# R3 Accepted Baseline

## Identity

- Branch: `codex/rag-eval-system`
- Accepted Git revision: `169e84ed1ee845cd07085f16e553bd5021fd73a2`
- Acceptance date: `2026-08-08`
- Full regression: `3069 passed, 30 skipped, 3 known SWIG warnings`
- Public repository audit: `1406 candidates / 0 findings`

This revision is the immutable comparison point for R3. Historical evidence is
not regenerated when implementation dependencies change. A new experiment must
record its own code revision, protocol hash, data split, model digest, command,
latency and artifact hashes.

## Accepted external evidence

| Surface | Population | Accepted result | Boundary |
|---|---|---|---|
| UDA-QA FinHybrid page retrieval | 96 questions, 12 company-disjoint reports | Page Hit@5 `73.96%`, nDCG@5 `61.30%`, p95 `222.91 ms` | known-report page retrieval; public-label test consumed |
| FinQA end-to-end | fixed public 100-case sample | strict `44%`, evidence recall `93.5%`, citation P/R `79.38%/78.33%` | not full FinQA, not SOTA, consumed |
| garak LatentInjectionReport | 12 combination-disjoint attacks | ASR `4/12 -> 0/12`, exposure `12/12 -> 0/12` | one probe subset, local Qwen3-8B |

## Consumed populations

- UDA v1 development and fixed test: consumed.
- FinanceBench development and historically disclosed fixed test: consumed.
- FinQA 60-case calibration and 40-case internal E11 cohort: consumed.
- FinQA fixed 100-case end-to-end sample: consumed.
- garak 12-attack fixed holdout: consumed.

These populations may be used for retrospective diagnosis and regression
compatibility only. They may not select an R3 intervention that is then reported
against the same population.

## Unfinished external evidence

R2-S8 G5 independent double-human review remains `NOT_RUN`. R3 does not replace
two independent humans with an LLM or another coding agent. All other R3 work is
allowed to proceed without treating that missing evidence as completed.

## R3 objective

R3 must produce a same-population `baseline -> candidate` comparison on a newly
frozen company-disjoint population, or preserve a negative result and stop. It
must not add frameworks, databases, agents or models unless a preregistered
experiment shows that the current component is the bottleneck.
