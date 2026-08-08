# Enterprise Failure Analysis

## Bound source

- Retrieval run: `enterprise-rag-bench-b0-v1-955d86f`
- Retrieval execution SHA: `955d86f1ca244bc90025c89806fd786f978b98ff`
- Failure-analysis SHA: `ad3005201e73dd7d5af3d8621c39b3e9c670bbca`
- Private detail SHA-256:
  `9c5a46d7f6b92b87540cf42ffb976d2af7d97ba7112588b763dbd9db2257e7dd`
- Public taxonomy CSV SHA-256:
  `521574611460989fadd6d108bbda47042aed87f854a954a14d5715502d68f316`

The analysis covers the frozen 470 document-grounded questions on the complete
511,962-row corpus. It is retrieval-only and does not inspect generated answers.

## Deterministic priority

Each question receives exactly one label in this order:

1. `RETRIEVAL_MISS`: Recall@5 is zero.
2. `MULTI_DOC_INCOMPLETE`: at least one gold document is found, but not all gold
   documents are in top 5.
3. `WRONG_DOCUMENT`: all required evidence is in top 5, but rank 1 is not gold.
4. `OK`: required evidence is complete and rank 1 is gold.

This order prevents a multi-document question with no gold hit from being hidden
inside the weaker `MULTI_DOC_INCOMPLETE` category.

## Overall distribution

| Category | Count | Rate |
|---|---:|---:|
| `RETRIEVAL_MISS` | 153 | 32.55% |
| `MULTI_DOC_INCOMPLETE` | 59 | 12.55% |
| `WRONG_DOCUMENT` | 58 | 12.34% |
| `OK` | 200 | 42.55% |

The primary bottleneck is zero-recall retrieval, not ranking. A cross-encoder can
only reorder retrieved candidates and therefore cannot recover the 153 cases
whose gold evidence never reaches top 5.

## Category evidence

- Semantic: 80 misses among 125 questions (64.0%); these 80 account for 52.3%
  of every B0 retrieval miss.
- Basic: 57 misses among 175 questions (32.6%).
- Project-related: 34 of 40 questions are multi-document incomplete; only 5 are
  `OK`.
- Completeness: 15 incomplete, 4 complete misses, and only 1 `OK` among 20.
- Conflicting information: 15 `OK`, 2 incomplete, 2 misses, and 1 wrong-rank
  case. This supports retrieval coverage only, not conflict acknowledgement.
- Intra-document reasoning: 30 `OK` among 40 and 90.0% Recall@5, the strongest
  larger cohort for lexical retrieval.

## Candidate decision

The next justified capability is resumable, sharded dense retrieval using the
already pinned BGE-M3 identity. It directly targets semantic zero-recall and can
later support an honest RRF comparison. The capacity profile estimates 1,702,370
flat chunks, 6.49 GiB for one float32 matrix, and roughly 11.39 embedding hours
at the measured local rate, so the candidate requires checkpoints and
memory-mapped/sharded vectors before any full formal run.

The fixed EnterpriseRAG test is already consumed and cannot be used to tune
chunk size, fusion weights, or thresholds. Candidate choices must be frozen from
development evidence (for example WixQA Synthetic) and then reported on this
fixed cohort without repeated selection.

## Not assessed

The retrieval taxonomy cannot classify `CONFLICT_NOT_DETECTED`, answer reasoning,
unsupported claims, citation errors, refusal errors, parser errors, or tool-budget
exhaustion. Those labels remain `NOT_ASSESSED_RETRIEVAL_ONLY`; inferring them from
document rankings would be false precision.
