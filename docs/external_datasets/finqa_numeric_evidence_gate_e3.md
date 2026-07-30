# FinQA Gate E3: Numeric Evidence Contract

## Status

`INPUT_GATE_PASSED`

Gate E3 is a disclosed-development input calibration. It reuses only the 60
Gate E2 calibration cases. The 40-case internal-validation cohort remains
`NOT_RUN`, and the frozen test remains untouched.

## Why Gate E3 exists

Gate E2 reported a deliberately coarse `25/60` complete-operand figure. That
metric compared gold operands with normalized candidate values, plus a
percentage alternative. It did not account for:

- a FinQA program referring to surface `120` while a table header normalized
  `120 million` to `120000000`;
- explicit FinQA `const_*` operands that are formula constants rather than
  document retrieval targets;
- one candidate carrying both a surface representation and a normalized
  execution value.

A provenance-aware disclosed re-analysis of the same 60 cases found:

```text
gold operand occurrences                         154
selected evidence, normalized match               78
selected evidence, surface/scale view match        34
controlled FinQA constants                         24
missing because gold evidence was not retrieved    16
unresolved extraction/alignment                      2
runtime input complete cases                       49/60
complete when gold evidence is inspected           58/60
```

This supersedes `25/60` as the engineering diagnosis, but it does not rewrite
or invalidate the immutable Gate E2 public artifact. The old number remains an
accurate result for its stated coarse method.

Protocol erratum: the frozen `49/60` field is the selected-evidence candidate
pool before the 24-candidate shortlist. A follow-up audit at commit `1467aba`
measured `48/60` after the shortlist, with one complete case lost and zero
shortlist errors. The immutable 95% gate applies to post-shortlist completeness.
See `evidence/finqa_numeric_evidence_protocol_erratum_v1.json`.

## Frozen hypotheses

1. Narrative parentheses and accounting negatives require different policies.
   Parenthesized amounts in prose often mark an explanatory aside, while a
   standalone parenthesized table cell may represent a negative amount.
2. FinQA row headers can themselves contain value-bearing text. Extracting only
   data cells can therefore omit a gold operand even when the evidence row was
   retrieved.
3. Row-level retrieval loses table-parent structure. A bounded table-parent
   closure plus immediate text neighbors can recover related evidence without
   using gold labels.
4. The planner must see a provenance-bound surface value and normalized
   execution value, rather than treating scale-equivalent values as unrelated.

## Frozen runtime boundary

```text
existing selected evidence IDs
  -> deterministic bounded closure proposal
  -> RetrievedContentGuard scans every proposed addition
  -> admitted table cells, value-bearing row headers, and text spans
  -> versioned numeric extraction
  -> provenance-bound surface + normalized views
  -> question-conditioned shortlist (maximum 24)
  -> typed sketch planner
  -> host validator and Decimal compiler
```

Closure limits are 24 additions, 32 total evidence units, 8,000 source
characters, and 128 candidates before the 24-candidate shortlist. Exceeding a
hard contract must fail closed or record a bounded omission; it must never
silently publish an unbounded prompt.

## Frozen deterministic gates

- runtime input completeness at least 95%;
- gold-evidence parse completeness exactly 100%;
- at least 90% of the 16 diagnosed retrieval-missing operands recovered;
- p95 total evidence units at most 32;
- p95 evidence characters at most 8,000;
- p95 pre-shortlist candidates at most 96;
- v1 candidate bytes and identities unchanged;
- every added unit scanned by the retrieved-content Guard;
- no gold program or gold evidence ID used at runtime.

Passing these gates proves only that the input contract improved. It does not
prove answer accuracy improved and does not authorize a model run, internal
validation, frozen-test reuse, or typed-route adoption.

## Research basis

The implementation direction follows four established ideas without claiming
to reproduce their published scores:

- FinQA represents financial reasoning as executable DSL programs over table
  and text evidence.
- TAT-QA separates evidence span/cell extraction from symbolic operations.
- Program of Thoughts delegates arithmetic execution to a deterministic
  interpreter and emphasizes semantic variable binding.
- Structure-aware table QA preserves row, column, and table context instead of
  treating every row as unrelated prose.

The repository implementation remains local, bounded, provenance-first, and
fail closed.

## Implementation and failed attempts

Gate E3 was implemented at commit `6655ee8`. The frozen v1 extractor was not
modified. The new path is split into:

- `finqa_numeric_evidence_v2.py`: versioned extraction and guarded closure;
- `finqa_numeric_evidence_shortlist_v2.py`: bounded 128-to-24 shortlist;
- `finqa_numeric_evidence_audit.py`: zero-model-call input audit;
- `audit_finqa_numeric_evidence.py`: source verification and append-only
  private/public publication;
- `verify_finqa_numeric_evidence_public.py`: public-only or private-bound
  verification.

Four failures materially changed the implementation:

1. An initial v2 edit changed the source hash bound by the v1 manifest. It was
   reverted and isolated in a new module.
2. The first audit hit the old planner's 64-candidate pre-shortlist limit.
   The E3 shortlist now accepts the frozen 128 input budget and still emits at
   most 24 candidates.
3. A one-to-one duplicate-value audit rule contradicted the frozen baseline:
   one provenance-bound number may be referenced twice by a program. The rule
   was corrected before formal publication.
4. Numeric column-header extraction fixed the last gold parse miss but first
   raised p95 candidates to 99. Restricting expansion to complete amount-like
   headers excluded date and descriptive headers and restored p95 to 71.

No threshold was relaxed in response to these failures.

## Formal calibration result

The committed formal run is
`finqa-numeric-evidence-gate-e3-calibration-v2`.

```text
v1 selected, before shortlist                 49/60  81.67%
v1 selected, after shortlist                  48/60  80.00%
v2 selected, before shortlist                 51/60  85.00%
v2 guarded closure, before shortlist          60/60 100.00%
v2 guarded closure, after shortlist           58/60  96.67%
v2 gold-evidence parse                        60/60 100.00%
retrieval-missing operand recovery            15/16  93.75%
p95 total units / chars / pre-shortlist       27 / 4794 / 71
p95 post-shortlist candidates                 24
Guard scans / quarantines                     1168 / 0
model calls                                   0
decision                                      INPUT_GATE_PASSED
```

All 11 frozen checks passed. The result authorizes only the next disclosed-
development paired model calibration. It does not prove an answer-accuracy
gain, authorize the typed route, or permit consumption of the 40-case internal
validation cohort.

Public aggregate:
`evidence/finqa_numeric_evidence_calibration_public_v1.json`.

Detailed beginner explanation:
`../learning/24_FINQA_GATE_E3_NUMERIC_EVIDENCE.md`.

## Closeout verification

```text
focused pre-publication tests        40 passed
public verifier focused tests        17 passed
full repository regression           2741 passed / 30 skipped / 0 failed
public repository audit              1052 candidates / 0 findings
compileall / pip check / diff check   passed / passed / passed
Ruff                                 not installed; no lint claim
```

The three warnings are the repository's existing FAISS/SWIG deprecation
warnings. They are not test failures.
