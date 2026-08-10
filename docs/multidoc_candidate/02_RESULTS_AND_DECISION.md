# Bounded Multi-document Candidate Results

## Result

```text
DEVELOPMENT_CANDIDATE_REJECTED
fixed validation authorized: false
serving change authorized: false
resume quality claim allowed: false
```

The run completed all 20 paired cases with zero tool errors and zero budget
exhaustions. Rejection is a valid experiment outcome.

## Four-arm metrics

| Metric | A current | B decompose | C select | D combined |
| --- | ---: | ---: | ---: | ---: |
| Retrieval recall | 48.33% | 48.33% | 48.33% | 48.33% |
| Retrieval all-gold complete | 15.00% | 15.00% | 15.00% | 15.00% |
| Citation completeness | 0.00% | 0.00% | 0.00% | 0.00% |
| Citation recall | 21.67% | 21.67% | 24.17% | 24.17% |
| Citation precision | 45.00% | 45.00% | 41.67% | 39.17% |
| Mean selected sources | 1.00 | 1.00 | 1.35 | 1.40 |
| Mean query variants / embeddings | 1.00 | 1.80 | 1.80 | 1.80 |
| Answered / partial | 19 / 1 | 18 / 2 | 18 / 2 | 18 / 2 |
| p50 latency | 477.37 ms | 509.32 ms | 511.36 ms | 502.65 ms |
| p95 latency | 600.09 ms | 1119.36 ms | 1113.52 ms | 1115.59 ms |

No answer-correctness or semantic-entailment score was measured. The answer
path was extractive and made zero generation-model calls.

## Pre-registered D versus A gate

| Check | Observed | Pass |
| --- | ---: | --- |
| Citation completeness gain >=15 pp | +0.00 pp | no |
| Citation recall gain >=15 pp | +2.50 pp | no |
| Citation precision drop <=10 pp | -5.83 pp | yes |
| Paired complete-case fixes >=3 | 0 | no |
| Paired regressions =0 | 0 | yes |
| p95 latency <=2x | 1.859x | yes |
| Mean selected sources <=3 | 1.40 | yes |
| Tool errors / budget exhaustion =0 | 0 / 0 | yes |
| Guard / ACL enabled | yes / yes | yes |
| Protected production paths unchanged | 0 changed | yes |

Three quality checks failed, so the candidate is rejected even though the
precision, cost ceiling, and engineering-safety checks passed.

## What each arm tells us

- `B == A` on retrieval and citation quality: the frozen lexical clause split
  did not acquire additional gold evidence.
- `C` and `D` added sources and one case gained partial gold coverage, but no
  case became complete.
- `D` lost 5.83 precision points and nearly doubled p95 latency for only 2.50
  recall points. That is not a useful quality/cost trade-off.
- The result does not show that decomposition is universally ineffective. It
  rejects this exact deterministic policy on this consumed development cohort.

## Evidence

- `evidence/protocol_v1.json`: code, data, model, index, boundary, and command.
- `evidence/case_matrix_v1.json`: 80 public arm rows and paired transitions.
- `evidence/aggregate_v1.json`: summaries, gate, decision, and claim boundary.
- `evidence/failure_analysis_v1.json`: deterministic loss and noise counts.

Verification:

```powershell
python -m scripts.verify_wixqa_multidoc_candidate
```

Expected status: `VERIFIED_REJECTED_CANDIDATE`.
