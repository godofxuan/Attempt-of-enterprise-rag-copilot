# Serving-component retrieval replay

Scope: 200 consumed WixQA ExpertWritten questions, four frozen configurations,
800 completed query/configuration results. This is retrospective retrieval
measurement, not independent validation, answer accuracy, or an API SLA.

| Configuration | Macro Recall@5 | Hit@1 | nDCG@5 | MRR@5 | All-gold@5 | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| Hybrid | 56.00% | 33.50% | 45.07% | 44.12% | 48.50% | 411.41 |
| Dense | 65.92% | 35.50% | 52.08% | 49.97% | 59.50% | 335.58 |
| Safe raw20 + BGE | 72.25% | 44.50% | 59.20% | 58.01% | 65.50% | 333.94 |
| Safe raw50 + BGE | 74.25% | 44.00% | 59.93% | 58.40% | 67.50% | 754.46 |

All four configurations completed 200/200 without execution errors. Compared
with Dense, raw20 gains 6.33 percentage points of macro Recall@5; raw50 gains
8.33 points. Raw50 gains 2 points of Recall over raw20 but slightly reduces
Hit@1 and takes substantially longer. It is not uniformly better.

Timing excludes a separately recorded shared query embedding and initial model
warmup. It includes serving pipeline, full application admission and reranking.
There is one serial observation per question/configuration with rotated arm
order. Do not infer that raw20 is faster than Dense from these p95 values:
tails can include different local interference and this is not repeated API
timing. The main service deadline and context limits remain enabled.

The protocol uses candidate_k=200 for all four strategies. Hybrid retains its
default per-document limit of two, whereas the dense profiles use one; thus
this is a strategy/profile comparison, not a single-variable reranker ablation.
It is not a measurement of the stock controller's smaller candidate request.

Index equivalence: original FAISS/BM25 objects and exact ordered chunk IDs/text
are reused. Benchmark-only ACL/version metadata is added. No document-open
implementation or complete enterprise index activation is claimed by this
retrieval-only adapter. The application Guard scans matched/metadata/split
surfaces; historical body-only evaluator numbers are not substituted here.

Evidence:
- Protocol: `RETRIEVAL_PROTOCOL_V2.json`.
- Private result: `.private/runtime_delivery/wixqa_serving_B_v2b/summary.json`.
- Completed rows SHA-256: `19830ebd05002510a110d24e3d58e91b76f2b9176bc6b47a928b7a6f3a595d19`.
- Baseline Git HEAD: `d27c0f8a68830fd74bbb983567e8b4d50967c0ae`, dirty=true.
- Execution source-tree SHA-256: `5e4e8860d86a3224af3a2afd572036ad2b99a345f202ae0c0b1556a1617f04d0`.
- Completion verified unchanged execution source identity before/after.

Failed attempts are retained: v1 stopped after 267 rows (228 duplicate-context
budget failures); v2 lost its process after seven successful rows and has no
completion marker. Total observed rows across attempts: 1074. No failed rows
were spliced into the final cohort, no questions were replaced, and no extra
ranking parameter sweep was run. The budget deviation is disclosed rather
than calling this an 800-attempt experiment.

Decision: preserve the fast default until authenticated answer/service and
resource validation are complete. The result supports further delivery work,
not an immediate claim of production readiness or end-to-end answer quality.
