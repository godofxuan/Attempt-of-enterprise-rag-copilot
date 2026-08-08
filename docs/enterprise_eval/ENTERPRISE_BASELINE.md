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

