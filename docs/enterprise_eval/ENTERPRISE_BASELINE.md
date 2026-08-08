# Enterprise-aligned Baseline

## WixQA E1 retrieval baseline

Execution SHA: `234734657fe354a0ecd767022c6f7c22cdc329da`

Data and model identity:

- WixQA official repository revision:
  `d662dc42479c14e202eccd832f8c4b66a035c4cc`
- Dataset manifest SHA-256:
  `e40972d70a8c80685b3730733efd90ac82a01fd52a949a0d27e122809bc290dd`
- Flat index manifest SHA-256:
  `d21b3aa78bc578a86d421c4db724b6441d404e13ed628bd8c22fdaff002daa09`
- BGE-M3 Ollama model SHA-256:
  `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`
- Corpus: 6,221 articles, 11,975 fixed 1,800-character chunks, 150-character overlap.
- Retrieval: top 200 chunks, article identity deduplication, top 5 articles.
- RRF: equal BM25/dense weight, `k=60`.

The official files expose only a public `test` split. The local names below are
consumption roles, not official hidden splits.

### Synthetic development, 6,221 questions

| Arm | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 | mean / p95 latency |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 61.77% | 80.05% | 85.58% | 71.26% | 74.86% | 55.2 / 77.5 ms |
| Dense | **89.41%** | **96.46%** | **97.88%** | **93.00%** | **94.24%** | 152.1 / 160.7 ms |
| Equal RRF | 76.16% | 91.54% | 94.41% | 83.91% | 86.58% | 207.5 / 234.5 ms |

Synthetic uses one gold article per question. Its multi-article completeness is
undefined and must not be reported as zero or one.

### Simulated validation baseline, 200 questions

| Arm | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 | Multi-article complete@5 | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 11.92% | 27.08% | 35.50% | 22.90% | 24.83% | 14.81% | 79.2 ms |
| Dense | **29.75%** | **51.17%** | **61.42%** | **45.12%** | **47.78%** | 14.81% | 161.8 ms |
| Equal RRF | 23.25% | 43.50% | 52.92% | 37.11% | 39.61% | **22.22%** | 236.8 ms |

There are 27 multi-article cases. RRF improves completeness on this small subset
while reducing overall recall and ranking quality. This is a trade-off, not a
promotion result.

### ExpertWritten fixed external baseline, 200 questions

| Arm | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 | Multi-article complete@5 | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 17.67% | 33.33% | 42.75% | 31.16% | 32.15% | 11.54% | 151.8 ms |
| Dense | **31.00%** | **56.92%** | **66.42%** | **49.61%** | **52.16%** | **30.77%** | **157.4 ms** |
| Equal RRF | 30.92% | 47.92% | 59.25% | 45.89% | 47.16% | 19.23% | 304.6 ms |

There are 52 multi-article cases. Dense is the E1 retrieval champion. Equal RRF
is rejected: versus Dense it loses 7.17 percentage points Recall@5, 5.00 points
nDCG@5, and 11.54 points multi-article completeness while p95 latency is 1.94x.

## What this baseline proves

- The official WixQA corpus can be downloaded, verified, canonicalized, indexed,
  and evaluated from a fresh private cache with pinned data/model identities.
- BGE-M3 Dense is materially stronger than BM25 and equal-weight RRF under this
  flat article protocol.
- Realistic support questions are much harder than one-question-per-article
  Synthetic development data.
- Multi-article completeness is a primary measured bottleneck.

## What is still not proved

- No answer correctness, citation correctness, refusal, or bounded-Agent quality
  result exists yet for WixQA.
- ExpertWritten is a fixed public external benchmark, not blind or hidden.
- No candidate improvement was evaluated on an untouched WixQA holdout.
- No production traffic, SLO, concurrency, or general enterprise-domain claim is
  supported by these local measurements.

Public aggregate evidence:
`evidence/wixqa_retrieval_baseline_public_v1.json`.

## EnterpriseRAG-Bench E2 full-corpus B0

Execution SHA: `955d86f1ca244bc90025c89806fd786f978b98ff`.

The disk-backed BM25 control indexed all 511,962 official rows (511,958 unique
source IDs) without source-type oracle filtering. The 1.37 GiB FTS5 artifact was
built in 231.35 seconds with approximately 1.83 GiB peak working set. The frozen
retrieval cohort contains all 470 questions with document gold; high-level and
information-not-found questions are excluded from retrieval metrics rather than
counted as misses.

| Group | Cases | Recall@5 | MRR@5 | nDCG@5 | Multi-doc complete@5 | p95 latency |
|---|---:|---:|---:|---:|---:|---:|
| Overall | 470 | 60.37% | 57.96% | 55.89% | 28.26% (92 cases) | 1,821.0 ms |
| Basic | 175 | 67.43% | 58.83% | 61.01% | N/A | 1,326.7 ms |
| Semantic | 125 | 36.00% | 25.47% | 28.13% | N/A | 2,192.2 ms |
| Intra-document reasoning | 40 | 90.00% | 81.13% | 83.35% | N/A | 1,466.2 ms |
| Project-related | 40 | 49.70% | 84.38% | 55.55% | 12.50% | 1,795.4 ms |
| Constrained | 30 | 80.00% | 82.61% | 76.36% | 38.46% | 2,662.3 ms |
| Conflicting information | 20 | 85.00% | 84.17% | 83.07% | 78.95% | 800.2 ms |
| Completeness | 20 | 34.39% | 66.67% | 45.28% | 5.00% | 1,684.4 ms |
| Miscellaneous | 20 | 85.00% | 82.50% | 83.15% | N/A | 1,019.0 ms |

The result supports a narrow claim: a bounded disk-backed lexical baseline now
runs on the complete heterogeneous corpus. It does not measure answer quality,
citations, refusal, conflict acknowledgement, Evidence Ledger behavior, or Agent
value. Semantic retrieval and multi-document completeness are the dominant
quality gaps; global OR BM25 scoring is also too slow for an interactive SLO.

Public aggregate evidence:
`evidence/enterprise_rag_bench_bm25_public_v1.json`.

## WixQA E1 bounded-Agent missing arm

Execution SHA: `07b156ed4d1b4e7ff24a06aac7a8d8b41630e03b`.

The missing B3 arm ran the actual V2 Runner, typed ToolRegistry, retrieved-content
Guard, deterministic controller, evidence ledger, extractive response builder,
and citation verifier. Its first search reused the exact equal-RRF B2 ranking;
no stronger retriever or model was substituted.

| Cohort | B2 Recall@5 | Agent search-evidence recall | Citation precision | Citation recall | Multi-article citation complete | B2 / Agent p95 |
|---|---:|---:|---:|---:|---:|---:|
| Simulated (200) | 52.92% | 52.92% | 26.50% | 23.25% | 0.00% (27 cases) | 299.3 / 476.7 ms |
| ExpertWritten (200) | 59.25% | 59.25% | 35.18% | 30.92% | 0.00% (52 cases) | 342.5 / 502.7 ms |

Every case made exactly one search; mean find and open calls were both zero.
Simulated produced 129 answered and 71 partial responses. ExpertWritten produced
144 answered, 55 partial, and one not-found response. None of the 400 cases had
a structured tool error.

Decision: `AGENTIC_ROUTE_REJECTED`. The controller did not expand retrieval,
while final source selection collapsed multi-article evidence to one cited source.
Latency rose 1.59x on Simulated and 1.47x on ExpertWritten. This run measures
retrieval/citation identity and tool behavior, not answer correctness.

Public aggregate evidence: `evidence/wixqa_agent_public_v1.json`.
