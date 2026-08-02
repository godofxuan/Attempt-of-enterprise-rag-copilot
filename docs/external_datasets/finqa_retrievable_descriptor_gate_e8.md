# FinQA Gate E8: Retrievability-Aware Descriptors and Candidate Reranking

## 1. Decision and claim boundary

E8 is a disclosed development calibration on the same frozen 60-case cohort
used by E5-E7. It asks two separate questions:

1. Can a value-free descriptor expose enough safe context for a question-only
   retriever to select the correct candidate group?
2. Once a group is selected, can a descriptor-aware host reranker retain the
   correct numeric candidate within Top-4 or Top-8?

The answer is mixed. Catalog coverage and the Oracle candidate upper bound
passed, and descriptor Recall@4 improved by one role. Runtime candidate quality
did not pass the frozen development thresholds. The authoritative decision is
`E8_DEVELOPMENT_PROGRESS_GATE_FAILED`; serving remains disabled, internal
validation is `NOT_RUN`, and the frozen test is `UNTOUCHED`.

## 2. Frozen protocol

`finqa_retrievable_descriptor_protocol_v1.json` was written before the v3
catalog, v5 retriever and new reranker. It binds the E7 source artifacts, exact
60-case cohort, budgets, E7 baselines, progress gates, longer-term targets and
non-claims.

The progress thresholds were not changed after results were observed:

| Metric | E8 threshold |
|---|---:|
| Descriptor Recall@4 | 88% |
| Descriptor complete case@4 | 86% |
| Candidate Recall@4 | 75% |
| Candidate Recall@8 | 84% |
| Candidate complete case@8 | 80% |
| Conditional candidate retention@8 | 98% |
| Oracle candidate Recall@8 | 98% |
| Edge reduction | 70% |

## 3. Implemented data path

```text
Guard-admitted evidence and numeric candidates
                  |
retrievability-aware catalog v3
  structured fields + balanced local hint + safe topic hint
  same-context unlabeled numbers grouped by safe content fingerprint
                  |
question-only deterministic retriever v5
  E7 structural score first
  context hints only when structural fields have no lexical signal
                  |
maximum four descriptor enums per role
                  |
host-only descriptor -> candidate mapping
                  |
descriptor-aware candidate reranker
  hard compatibility + explicit evidence rank + local provenance window
  global score with a descriptor-coverage floor
                  |
maximum eight immutable candidate IDs
```

No candidate value, candidate ID, evidence ID, source ID, table ID or
provenance is included in the descriptor prompt payload. Raw contexts and the
projected fields are Guard-scanned. Candidate identities and provenance are
never rewritten.

## 4. Main code changes

| File | Responsibility |
|---|---|
| `finqa_safe_descriptor_catalog_v3.py` | immutable v3 schema, balanced hints, topic projection, safe text grouping and host-only mapping |
| `finqa_descriptor_retriever_v5.py` | conservative structural-first descriptor scoring with context backoff |
| `finqa_descriptor_candidate_reranker_v1.py` | hard-compatible, group-aware candidate ranking and structured empty result |
| `audit_finqa_retrievable_descriptor_v1.py` | exact-cohort Oracle/runtime evaluation, paired E7 deltas and immutable evidence |
| `finqa_retrievable_descriptor_public_v1.json` | authoritative aggregate result and implementation hashes |
| `finqa_retrievable_descriptor_ablation_public_v1.json` | disclosed failed hyperparameter runs and selected configuration |

Historical E7 implementation files were not edited because their public
evidence binds their SHA-256 digests.

## 5. Failures found during implementation

### 5.1 Unbalanced context truncation

E7 v2 centered a 240-character window on a number, then kept the first 96
sanitized characters. A business term immediately to the right of the number,
such as `34 countries`, could disappear. V3 allocates separate left and right
budgets, so right-side units and entities survive without exposing the number.

### 5.2 Context hints initially regressed retrieval

The first E8 smoke run reduced descriptor Recall@4 from 83.74% to 79.67%.
Context fields were influencing descriptors that already had reliable row or
metric overlap. V5 now starts with the unchanged E7 v2 structural score and
uses local/topic hints only when primary fields have no question or role-anchor
signal.

### 5.3 One evidence paragraph became many descriptors

Each unlabeled number initially received a slightly different local window.
One sentence with several values could occupy all four descriptor slots. V3
now groups unlabeled candidates by a SHA-256 fingerprint of the same
number-free, Guard-admitted context. The fingerprint controls host grouping;
the evidence ID is not exposed.

### 5.4 Fixed round-robin quotas lost correct values

The first reranker gave each of four descriptors exactly two Top-8 slots. In
16 roles the correct descriptor was selected but its correct number was often
the third to sixth member. Candidate Recall@8 fell to 66.67%. The final merge
returns to global candidate scoring and only enforces a coverage floor when a
selected non-empty descriptor is completely absent from Top-8.

### 5.5 Alphabetical evidence order changed scores

Sorting evidence IDs lexically puts `table_10` before `table_2` and discards
the original retrieval/admission order. The reranker now accepts an explicit
stable evidence-rank map. Reversing candidate and context container order does
not change results.

## 6. Authoritative result

The final configuration uses descriptor-priority step `0` and local candidate
weight `1`.

| Metric | E7 baseline | E8 | Delta | E8 gate |
|---|---:|---:|---:|---:|
| Descriptor Recall@4 | 83.74% | **84.55%** | +0.81 pp | 88% |
| Descriptor complete case@4 | 82.76% | **82.76%** | 0.00 pp | 86% |
| Candidate Recall@4 | 70.73% | **66.67%** | -4.07 pp | 75% |
| Candidate Recall@8 | 78.86% | **78.86%** | 0.00 pp | 84% |
| Candidate complete case@8 | 75.86% | **74.14%** | -1.72 pp | 80% |
| Conditional candidate retention@8 | 94.17% | **93.27%** | -0.91 pp | 98% |
| Oracle candidate Recall@8 | not the runtime baseline | **100.00%** | n/a | 98% |
| Candidate edge reduction | 77.78% | **75.10%** | -2.68 pp | 70% |

Catalog coverage, Oracle capacity, edge reduction, schema validity, zero model
calls, zero forbidden-field leakage, candidate identity, input-order
invariance, Guard projection and disabled serving all passed. Six runtime
quality checks failed. This is why E8 is not adopted even though one descriptor
metric and the Oracle result improved.

## 7. Hyperparameter ablation

Uniform bonuses for descriptor rank were tested at `0/1/2/4/8`. Every positive
bonus reduced Candidate Recall@8 from 78.86% to 78.05% or 77.24%. A high-ranked
broad descriptor contains both useful and irrelevant values; adding the same
bonus to every member amplifies that noise.

Disabling local candidate context kept Recall@8 at 78.86% and improved Recall@4
to 68.29%, but reduced complete case@8 to 72.41% and Oracle candidate Recall@8
to 99.19%. Local weight `1` was retained for capacity and complete-case
behavior. Neither arm passed the gate.

## 8. Next allowed work

E9 should be a frozen, training-only learned ranking experiment rather than
another hand-tuned bonus. It should train on FinQA train data, group folds by
document/company, use only runtime-available value-free and host ranking
features, compare against E7 v2 and E8, and retain the current internal/frozen
cohort boundary. A challenger cannot replace the E7 champion unless it passes
both retrieval quality and security/identity invariants.

## 9. Verification

- E8 focused protocol/catalog/retriever/reranker tests: `15 passed`.
- External-dataset regression: `359 passed`.
- Full repository regression: `2871 passed, 30 skipped`.
- Compileall, `pip check` and `git diff --check`: passed.
- The three warnings are the repository's known SWIG/FAISS deprecation
  warnings. Ruff is not installed in the project environment, so no lint claim
  is made.
- Pytest temporary output was directed to `.private` under the D-drive project;
  this stage did not intentionally place evaluation data on C:.
