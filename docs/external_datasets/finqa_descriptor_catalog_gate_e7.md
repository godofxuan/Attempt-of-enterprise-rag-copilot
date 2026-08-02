# FinQA Gate E7: Safe Descriptor Selection

## 1. Gate question and boundary

E6 showed that value-free role descriptions have enough theoretical capacity,
but it did not show that a runtime planner can create them. E7 asks a narrower
and security-sensitive question:

> Can a question-only runtime select the right value-free descriptors before
> the host exposes any numeric candidate identity or value?

This is a disclosed development calibration on the same 60-case cohort. It is
not final-answer accuracy, held-out evaluation, or a serving authorization. The
40-case internal validation remains `NOT_RUN`, the frozen test remains
`UNTOUCHED`, and the typed serving route remains `DISABLED`.

## 2. Data and authority flow

```text
question + value-free typed skeleton
                    |
Guard-admitted numeric candidates (host only)
                    |
safe descriptor catalog
  metric/entity/row/column/period/source kind
  no value, candidate ID, evidence ID, source ID or provenance
                    |
descriptor selector/retriever
                    |
strict descriptor enum per role (maximum 4)
                    |
host-only descriptor -> candidate-ID mapping
                    |
candidate ranking and controlled Decimal compiler
```

The selector can express semantics. It cannot grant itself access to a
candidate, mutate provenance, or execute arithmetic.

## 3. E6-to-E7 question-only baselines

The first attempt generated free-form role queries from the question. All
results failed the frozen quality gate.

| Planner | Recall@4 | Recall@8 | Complete@8 | Model requests |
|---|---:|---:|---:|---:|
| deterministic question-only v1 | 62.60% | 79.67% | 70.69% | 0 |
| conservative deterministic v2 | 65.85% | 80.49% | 74.14% | 0 |
| `qwen3:8b` free-query v1 | 54.47% | 63.41% | 58.62% | 58 |

V1 over-inferred years from OCR text. V2 made period constraints conservative
but still could not recover hidden table-row semantics. The local model was
slower and 17.07 percentage points worse than deterministic v2 at Recall@8.
This rejected the hypothesis that another free-form query rewrite was the
missing capability.

## 4. Safe descriptor catalog

`finqa_safe_descriptor_catalog_v1.py` projects each admitted candidate into a
number-free semantic key. Candidate IDs and values remain in a host-only
mapping. Raw and sanitized fields are both scanned by
`RetrievedContentGuard`. Catalog ordering and IDs are deterministic.

The first Oracle catalog result failed only Recall@4:

| Catalog | Oracle Recall@4 | Oracle Recall@8 | Complete@8 | Edge reduction |
|---|---:|---:|---:|---:|
| v1 | 93.50% | 98.37% | 96.55% | 85.31% |
| contextual v2 | 95.93% | 100.00% | 100.00% | 89.35% |

V1 collapsed unlabeled text numbers into one generic descriptor. V2 adds a
bounded, Guard-admitted context fallback only when structured metric/entity/
row/column fields are absent. The frozen Oracle gate then passed.

This `100%` is catalog capacity. Offline gold is used only to ask whether the
correct candidate remains representable. It does not measure whether a model
can find the descriptor or answer the question.

## 5. Real local selector result

The `qwen3:8b` selector received only the question, value-free roles,
operations and descriptor enum. It used strict JSON schema, temperature zero,
`think=false`, one request per typed case and the pinned digest `500a1f067a9f`.

| Metric | Result |
|---|---:|
| Schema-valid rate | 93.10% |
| Recall@4 | 56.91% |
| Recall@8 | 59.35% |
| Complete@8 | 51.72% |
| Mean latency | 2591.14 ms |
| Edge reduction | 88.32% |

Four responses repeated a descriptor ID despite `uniqueItems`; host validation
rejected them. More importantly, semantic selection was weak even if those
format errors are ignored. In one minimized case the model ignored a
descriptor containing `matching buy sell volumes` and selected unrelated fuel
product rows. The route stayed disabled.

## 6. Deterministic and hybrid retriever ablations

All retriever protocols were frozen before their full runs and preserve their
negative results.

| Retriever | Recall@4 | Recall@8 | Complete@8 | Mean latency | Requests |
|---|---:|---:|---:|---:|---:|
| v1 lexical + role anchors | 67.48% | 78.05% | 74.14% | 0.44 ms | 0 |
| v2 normalized lexical | **70.73%** | 78.86% | **75.86%** | 1.25 ms | 0 |
| v3 BGE-M3 + lexical RRF | 65.04% | 74.80% | 72.41% | 511.55 ms | 58 embedding |
| v4 typed structural priors | 69.11% | **80.49%** | **75.86%** | 2.63 ms | 0 |

V1 proved that a deterministic host retriever beats the unconstrained local
selector. V2 fixed `S&P`/compound-token normalization and an additional
part-total question pattern. V3 pinned local `bge-m3` by full SHA256 and used
one batch request per typed case, but thin descriptors made dense similarity
harm reliable lexical order. V4 added only two typed priors: balance rows for
percent change and grouped descriptor cardinality for multi-operand ADD or
AVERAGE. It improved Recall@8 but reduced Recall@4.

Every runtime variant failed the unchanged `85% / 95% / 90%` Recall@4,
Recall@8 and complete-case thresholds. No variant is adopted.

## 7. Failure decomposition

For the strongest general lexical baseline v2, 26 roles missed Top8:

| Failure class | Roles | Meaning |
|---|---:|---|
| no question lexical signal | 8 | visible descriptor lacks the business topic |
| lexical signal below descriptor Top4 | 12 | four-descriptor budget/ranking loses it |
| descriptor selected, candidate ranking misses | 6 | host mapping expands to several values and the correct value falls below Top8 |

Examples include `unrecognized tax benefits` mapped only to `balance at
December`, and long-term debt maturity roles mapped to a generic `amount in
thousands` descriptor. This proves that the next bottleneck spans both data
representation and second-stage candidate ranking.

## 8. Engineering incidents and repairs

1. Ollama rejected a JSON schema using `prefixItems/items:false` with HTTP 400.
   The schema was reduced to supported array constraints and exact role order
   stayed enforced by host validation.
2. The live selector emitted duplicate IDs despite `uniqueItems`. The result
   was recorded as a schema failure; duplicates were not silently removed.
3. A one-second command timeout terminated the first v3 launch before any
   case or artifact existed. Process and artifact absence were verified, then
   the same frozen protocol was rerun with the correct outer timeout.
4. Initial BGE-M3 loading took seconds. The public result separately reports
   one initialization probe and 58 logical per-case embedding requests.
5. Dense retrieval regressed quality. The result was kept and serving remained
   disabled instead of tuning weights against the same result until it passed.

## 9. Research rationale

- [FinQA](https://arxiv.org/abs/2109.00122) defines the hybrid table/text
  numerical-reasoning task and executable-program supervision used by this
  track. It motivates separating evidence selection from symbolic execution.
- [TAT-QA](https://arxiv.org/abs/2105.07624) and TAGOP explicitly extract
  relevant table cells/text spans before applying symbolic operators. E7's
  descriptor layer follows that separation of responsibilities, while adding
  this project's Guard, identity and provenance boundaries.
- [RegHNT](https://arxiv.org/abs/2209.07692) models relationships among the
  question, table and paragraphs. The E7 failure taxonomy supports a future
  structured context contract instead of treating every descriptor as an
  isolated text string.
- [Self-RAG](https://arxiv.org/abs/2310.11511) motivates adaptive retrieval and
  reflection. The local E7 ablations show that generic reflection or query
  rewriting alone is insufficient when table-row semantics are absent from
  the selector-visible contract.

These papers informed the architecture direction. The exact safety contract,
pre-registered thresholds, failure taxonomy and negative results are local
project work, not claims reproduced from those papers.

## 10. Decision and next gate

```text
safe catalog capacity: PASSED (offline Oracle only)
question-only planners: FAILED
qwen3:8b descriptor selector: FAILED
deterministic/hybrid retrievers v1-v4: FAILED
serving route: DISABLED
internal validation: NOT_RUN
frozen test: UNTOUCHED
```

The next admissible work is a versioned, retrievability-aware catalog with
balanced local context/table topic metadata, followed by a descriptor-aware
candidate reranker. It must first measure descriptor recall separately from
candidate recall. New weights, larger models, internal validation and frozen
test consumption are not justified yet.
