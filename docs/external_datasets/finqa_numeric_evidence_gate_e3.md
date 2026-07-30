# FinQA Gate E3: Numeric Evidence Contract

## Status

`FROZEN_AFTER_DISCLOSED_E2_DIAGNOSIS_BEFORE_V2_IMPLEMENTATION`

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
