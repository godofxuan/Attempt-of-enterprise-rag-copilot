# Multi-document Agent Fast Track

## Measured failure and hypothesis

The frozen WixQA Agent evidence showed one search per question, zero find/open
calls, and zero multi-article citation completeness. The code audit found two
different mechanisms:

1. ordinary fact questions produce one generic `answer` required aspect;
2. `ExtractiveResponseBuilder` selected only `hits[0]` for each supported aspect.

The 27 multi-article WixQA Simulated questions do not generally expose reliable
sentence-level subquestions. Their multiple gold articles often represent
separate support pages for one workflow. A deterministic clause splitter would
therefore invent aspects. The isolated candidate changed only final per-aspect
evidence aggregation from one to at most five admitted hits.

## Data and claim boundary

- cohort: 27 multi-article WixQA Simulated questions;
- source: `MULTIDOC_DEV_COHORT.json`, with question/source IDs and hashes;
- consumption: `RETROSPECTIVE_DEVELOPMENT_ONLY_ALREADY_OBSERVED`;
- retrieval: unchanged BGE-M3 BM25+dense equal RRF, top five;
- Guard and ACL: unchanged;
- generation: extractive, zero model calls and zero generation tokens;
- use: mechanism development only, not fresh validation or a resume metric.

## A/B/C result

Execution SHA: `62522f6be65fa498bd901180e1d987615a8f6beb`.

| Metric | A: B2 retrieval | B: current Agent | C: aggregate candidate |
|---|---:|---:|---:|
| Article Recall@5 | 43.83% | 43.83% | 43.83% |
| Multi-doc retrieval completeness | 22.22% | 22.22% | 22.22% |
| Required evidence completeness | n/a | 0.00% | 22.22% |
| Citation completeness | n/a | 0.00% | 22.22% |
| Citation recall | n/a | 20.37% | 43.83% |
| Citation precision | n/a | 44.44% | 18.52% |
| Search/open/find mean | n/a | 1 / 0 / 0 | 1 / 0 / 0 |
| Tool errors / budget exhaustion | n/a | 0 / 0% | 0 / 0% |
| p95 latency | 311.13 ms | 531.77 ms | 591.98 ms |

The registered completeness, recall, latency, tool-error, and budget gates pass:
completeness improves by 22.22 percentage points and candidate p95 is 1.11x the
current Agent. However, citation precision falls by 25.93 points because citing
every admitted top-five hit also exposes irrelevant sources.

## Decision

`DEVELOPMENT_GATE_PASS`, but `HOLD_NO_UNCONSUMED_VALIDATION` and
`PRECISION_REVIEW_REQUIRED`.

The candidate remains an explicit evaluation configuration; production defaults
still retain one evidence item per aspect. This experiment proves that final
evidence collapse caused the zero completeness result, but also rejects
"cite more retrieved documents" as a complete product solution. No Agent uplift
may be placed on the resume without a selective evidence policy and fresh
validation.
