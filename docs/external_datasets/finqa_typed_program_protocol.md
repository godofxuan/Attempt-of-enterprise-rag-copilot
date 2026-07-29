# FinQA Temporal Operand Alignment and Typed Financial Program Protocol

Status: `GATE_A_DESIGN_AND_RED_TESTS_ONLY`

Baseline revision:
`d2a6bf945b5d3c724ed03aa6288fb609f5bc54cd`

This document freezes the design boundary for the next FinQA development
stage. It does not claim that candidate extraction, the typed planner, the
validator, the compiler, retrospective evaluation, or confirmatory evaluation
has been implemented.

## 1. Goal

The current FinQA planner generates a free arithmetic-expression string.
The host verifies that the expression is syntactically bounded and executable
with `Decimal`, but it cannot prove that each numeric literal came from the
right metric, year, unit, scale, sign, or admitted evidence source.

The proposed intervention is:

```text
question + admitted evidence
  -> deterministic NumericCandidate extraction
  -> planner selects candidate IDs and a restricted financial DSL
  -> host validates temporal, metric, unit, scale, sign, and provenance
  -> host compiles and executes with Decimal
  -> result + provenance + diagnostics
```

The model selects references and operations. The host owns identity,
validation, execution, and failure semantics.

## 2. Data and claim boundary

The following rules are mandatory:

1. The disclosed 100-case FinQA dev diagnostic cohort and disclosed
   100-case selective cohort may be used only for retrospective error analysis,
   synthetic fixtures, and mechanism development.
2. The frozen FinQA test is not a development input and must not be rerun for
   prompt or rule tuning.
3. Few-shot examples, hard negatives, and learned components may use only an
   explicitly admitted train split.
4. A confirmatory run requires a new zero-overlap cohort or a separate public
   financial-QA dataset.
5. Any result on already disclosed data must be labelled
   `RETROSPECTIVE_DEVELOPMENT_ONLY`.
6. Result disclosure cannot be followed by relaxed gates, removed regressions,
   changed samples, or an added arm presented as part of the same experiment.

## 3. Read-only baseline at Gate A

### 3.1 Repository state

```text
branch                     codex/rag-eval-system
HEAD                       d2a6bf945b5d3c724ed03aa6288fb609f5bc54cd
worktree before Gate A     clean
AGENTS.md                   absent
```

### 3.2 Static and deterministic checks

```text
Ruff                       NOT RUN: package/config absent
mypy                       NOT RUN: package/config absent
FinQA deterministic        74 passed / 23 deselected / 3 warnings
full deterministic pytest  2610 passed / 29 skipped / 3 warnings
```

Ruff and mypy are not silently reported as passing. Gate A does not modify the
environment merely to make a baseline tool available. Adding and pinning these
tools is a separate repository-tooling decision.

### 3.3 Read-only metric recomputation

The public evidence was parsed again without modifying any run or protocol.

| Recomputed item | Value |
| --- | ---: |
| Selective protocol SHA-256 | `f403ff7a25e4f09d5b2a956bfeeee11ef0c15a77fc07a4d01867067c21f695fc` |
| Oracle diagnostic errors from categories | `37` |
| Hybrid diagnostic errors from categories | `41` |
| Oracle minus Hybrid strict | `4` percentage points |
| Selective strict delta | `+2` percentage points |
| Selective grounded-strict delta | `+2` percentage points |
| Incremental generation-call reduction | `32.00%` |
| Incremental Calculator-call reduction | `30.5194805%` |
| Selective time reduction versus shadow full | `23.8289344%` |
| Beneficial-case capture | `75%` |
| Exact McNemar | `p=0.625` |

The recomputed protocol hash equals the value recorded in the public result.

### 3.4 Current error classification

On the disclosed 100-case dev diagnostic:

| Category | Oracle | Hybrid K=10 |
| --- | ---: | ---: |
| correct grounded | 56 | 52 |
| correct, citation incomplete | 7 | 7 |
| retrieval miss | 0 | 12 |
| generation protocol error | 0 | 0 |
| unsupported gold operation | 1 | 1 |
| operand-selection signal | 20 | 21 |
| operation-plan signal | 11 | 1 |
| composition/scale signal | 5 | 6 |

Oracle strict was `63%`; Hybrid strict was `59%`. Retrieval can directly
address the 12 Hybrid retrieval-miss classifications and may close part of the
four-point paired gap. It cannot explain the 37 Oracle errors that remain when
gold evidence is supplied.

The categories are deterministic mechanical signals. Operand and operation
signals are not guaranteed semantic root causes because algebraically
equivalent programs can differ from the official program.

## 4. Answers to the six baseline questions

### 4.1 Which errors can retrieval fix?

Retrieval can fix cases where required gold evidence is absent from the
selected context. The current direct count is 12 Hybrid retrieval misses.
The paired observation contained 10 Oracle-only-correct and 6
Hybrid-only-correct cases, so retrieval changes do not map one-to-one to the
four-point aggregate gap.

Reranking is not admitted in this stage because Oracle errors remain the larger
mechanism problem and no new confirmatory result has established retrieval as
the dominant remaining bottleneck.

### 4.2 Which errors remain under Oracle evidence?

The 37 Oracle errors contain:

- 20 operand-selection signals;
- 11 operation-plan signals;
- 5 composition/scale signals;
- 1 unsupported gold operation.

This motivates operand identity and financial typing before another retrieval
change.

### 4.3 How does the current planner represent numbers and programs?

`LocalFinQAProgramAnswerer` supplies temporary IDs for whole evidence units,
then asks the model for:

```json
{
  "expression": "(120 - 100) / 100",
  "cited_candidate_ids": ["evidence-01"]
}
```

The expression contains free numeric literals. The citation identifies an
entire evidence unit, which may contain multiple metrics and years. There is no
machine-checkable mapping from literal `120` to the 2023 revenue cell, or from
literal `100` to the 2022 revenue cell.

### 4.4 Which paths admit literals?

- `FinQAProgramPayload.expression`;
- the baseline program prompt and repair prompt, which explicitly request
  numeric literals;
- the plan-review payload, prompt, and repair prompt;
- `DecimalProgramStep.arguments`, which accept numeric strings when they are
  not previous-step references;
- `execute_decimal_expression`, which safely executes any bounded allowed
  numeric literal regardless of provenance;
- the direct-answer path's free-text calculation field, although that field is
  not the preferred Calculator program strategy.

The anonymous adjudicator cannot create a third expression, but both candidates
it chooses between already contain untyped literals.

### 4.5 Where are year, unit, scale, sign, and provenance lost?

1. `build_finqa_evidence_units` flattens each table row into text. Header words
   remain visible to the model, but table coordinates and typed relationships
   are not part of the planner schema.
2. The planner copies numbers into an expression independently from its
   evidence-ID list.
3. A citation names a whole unit, not the exact span or cell used by each
   operand.
4. The Calculator checks syntax, numerical range, and zero division, not
   financial semantics.
5. Reviewer and adjudicator prompts mention years, sign, and scale, but the
   host cannot enforce those instructions.
6. Parentheses-as-negative, percent-as-ratio, and thousand/million conversion
   are not preserved as typed source metadata.

### 4.6 What is the minimal viable change surface?

Gate A adds only this document and RED contract tests.

Gate B/C should prefer a new module:

```text
app/external_datasets/finqa_typed_program.py
```

and new focused tests. Historical files bound by frozen protocols must remain
byte-identical until a separately versioned adapter is ready. Later integration
should add a new answerer/CLI version rather than silently changing the old
`LocalFinQAProgramAnswerer`.

## 5. NumericCandidate contract

Planned version: `finqa_numeric_candidate_v1`.

```text
NumericCandidate
  candidate_id: str
  raw_text: str
  normalized_value: Decimal
  metric: str | None
  entity: str | None
  period: str | None
  fiscal_year: int | None
  unit: FinancialUnit
  scale: FinancialScale
  sign: -1 | 0 | 1
  source_id: str
  evidence_id: str
  table_id: str | None
  row_header: str | None
  column_header: str | None
  provenance_span: ProvenanceSpan
  role: operand | period_label | ordinal | page_number
  extraction_version: Literal["finqa_numeric_candidate_v1"]
```

`ProvenanceSpan` contains:

```text
start: non-negative character offset
end: exclusive offset greater than start
text_sha256: SHA-256 of the exact source substring
```

### 5.1 Normalization semantics

- `normalized_value` is the signed value in a canonical base unit.
- `$2.5 million` becomes `2500000`, while retaining `scale=million`.
- `(120)` becomes `-120`, with `sign=-1`.
- `12%` becomes the ratio `0.12`, with `unit=ratio` and `scale=percent`.
- `35 bps` becomes `0.0035`, with `unit=ratio` and `scale=basis_point`.
- commas and currency glyphs do not affect the numeric identity.
- unknown unit/scale stays `unknown`; the extractor must not invent one.

Known, compatible scales may be normalized deterministically. Unknown or
contradictory scale evidence fails closed.

### 5.2 Stable candidate identity

Candidate identity is derived from canonical JSON containing:

- extraction version;
- source/evidence identity;
- table coordinates when present;
- provenance offsets and substring hash;
- normalized value;
- unit, scale, sign, and role.

The ID is `num-` followed by a fixed-length lowercase SHA-256 prefix. The ID is
not derived from list position. Equal values at different sources must have
different IDs.

### 5.3 Extraction restrictions

- extraction is deterministic and model-free;
- text numbers and table cells are separate candidates;
- row and column headers are inherited only from explicit table structure;
- years are retained as period metadata or `period_label` candidates, not
  silently treated as financial operands;
- ordinals, page numbers, footnote numbers, and sequence labels are excluded
  from the default operand set;
- uncertain metric/entity/unit/scale fields remain `None` or `unknown`;
- every candidate must have exact source provenance;
- candidates from quarantined or non-admitted evidence may be recorded
  privately for diagnostics but cannot be used by a program.

## 6. Typed financial DSL

Planned version: `finqa_typed_financial_dsl_v1`.

### 6.1 References

Each argument is exactly one of:

```text
CandidateRef(candidate_id)
StepRef(step_id)
```

Raw numeric strings, numeric JSON values, expressions, and host-language code
are forbidden. A step reference must point to a completed earlier step.

### 6.2 Program schema

```text
TypedProgram
  dsl_version: Literal["finqa_typed_financial_dsl_v1"]
  steps: 1..8 TypedProgramStep
  output_step_id: str

TypedProgramStep
  step_id: stable "step-01".."step-08"
  operation: TypedFinancialOperation
  arguments: 2..8 OperandRef
```

Pydantic models use `extra="forbid"`. Unknown operations, fields, IDs, forward
references, duplicate step IDs, and unused output IDs fail closed.

### 6.3 Operation semantics

| Operation | Arity | Compatibility | Result |
| --- | ---: | --- | --- |
| `ADD` | 2 | same entity/metric/unit; compatible periods for aggregation intent | same unit |
| `SUB` | 2 | same entity/metric/unit; ordered periods/categories | same unit |
| `MUL` | 2 | one argument must be dimensionless, or both dimensionless | non-ratio argument's unit, otherwise ratio |
| `DIV` | 2 | denominator nonzero; units must form an admitted ratio | ratio or numerator unit |
| `PERCENT_CHANGE` | 2 | `(new, old)` with compatible entity/metric/unit and ordered periods | ratio `(new-old)/old` |
| `RATIO` | 2 | `(numerator, denominator)` and denominator nonzero | ratio |
| `AVERAGE` | 2..8 | same entity/metric/unit and admitted period/category set | same unit |

V1 intentionally does not expose arbitrary constants. Percentage and average
semantics belong to operators, avoiding model-generated `100` or item-count
literals.

### 6.4 Question intent

The validator receives a bounded `FinancialQuestionIntent` derived only from
the runtime question:

```text
operation_intent
metric/entity
target_period
start_period/end_period
requested_unit/scale
direction: new_over_old | old_over_new | part_over_total | none
```

Unknown fields remain unknown. They are not filled from gold programs or
correctness labels. The intent extractor and its version become part of any
confirmatory protocol.

## 7. Compatibility validator

Planned version: `finqa_typed_program_validator_v1`.

The validator checks, in deterministic order:

1. schema, size, and DSL allowlist;
2. literal absence;
3. candidate existence and unique ID;
4. backward-only step references;
5. exact provenance span integrity;
6. membership in the admitted evidence set;
7. candidate role is usable as an operand;
8. temporal compatibility with the question and operation;
9. metric/entity compatibility;
10. unit and scale compatibility;
11. source sign consistency;
12. numerator/denominator or new/old direction;
13. operation arity;
14. zero denominator;
15. output-unit compatibility.

Validation receives no gold program, `exe_ans`, strict score, retrieval metric,
or paired transition.

## 8. Failure reasons

`TypedProgramValidationError` has a stable `reason` and bounded diagnostic
metadata. V1 reasons are:

```text
missing_candidate
duplicate_candidate
temporal_mismatch
metric_mismatch
unit_mismatch
scale_mismatch
sign_mismatch
direction_mismatch
literal_only_operand
unsupported_operation
invalid_arity
divide_by_zero
missing_provenance
unadmitted_source
invalid_candidate_role
forward_step_reference
duplicate_step_id
missing_output_step
budget_exceeded
ambiguous_intent
```

Diagnostics may contain candidate/step IDs in private artifacts. Public
evidence contains aggregate counts and hashes only.

## 9. Compiler and result contract

The compiler:

- accepts only a validator-approved typed AST;
- uses `Decimal` with a fixed precision and magnitude budget;
- does not call `eval` or `exec`;
- records every intermediate result by stable step ID;
- preserves the contributing candidate IDs for each step;
- emits the final value, unit, source-provenance closure, and diagnostics.

Planned result:

```text
TypedProgramResult
  value: Decimal
  unit: FinancialUnit
  output_step_id: str
  step_values: mapping[step_id, Decimal]
  candidate_ids: ordered unique tuple
  evidence_ids: ordered unique tuple
  program_sha256: str
  validator_version: str
  compiler_version: str
```

### 9.1 Frozen public API expected by the RED tests

Gate B/C may add internal helpers, but the Gate A tests bind these public
symbols in `app.external_datasets.finqa_typed_program`:

```text
NumericCandidate
ProvenanceSpan
FinancialQuestionIntent
TypedProgramValidationError(reason: FailureReason)

extract_numeric_candidates(
  source_id,
  evidence_id,
  text,
  kind,
  table_id=None,
  row_header=None,
  column_header=None,
  unit_hint=None,
) -> tuple[NumericCandidate, ...]

compile_and_execute_typed_program(
  planner_payload,
  candidates,
  admitted_evidence_ids,
  intent,
) -> TypedProgramResult
```

`compile_and_execute_typed_program` is the fail-closed boundary that parses the
`extra="forbid"` planner payload, validates references and compatibility, then
executes the approved typed AST. Schema violations that represent a forbidden
numeric literal are normalized to `literal_only_operand`; they must not leak a
generic Pydantic exception to the orchestration layer.

## 10. Equivalent-program policy

The system does not reject a program merely because its syntax differs from a
gold program.

- `ADD(a, b)` and `ADD(b, a)` may both be valid.
- Non-commutative operations preserve argument order.
- Both programs must independently satisfy type, time, direction, provenance,
  and execution rules.
- Retrospective evaluation may compare final values and diagnostics, but must
  not use exact syntax equality as the correctness definition.
- Canonical fingerprints may sort operands only for explicitly commutative
  operations. V1 does not claim general symbolic algebra equivalence.

## 11. Candidate manifest boundary

Gate B will produce a private candidate manifest with full candidate records.
The public evidence projection contains only:

- extractor/config versions and hashes;
- source artifact hash;
- candidate count;
- candidate-ID-set hash;
- counts by source kind, role, unit, and scale;
- rejected-noise counts;
- missing/unknown metadata counts;
- no raw question, table, evidence text, candidate ID, or case ID.

## 12. Gate A RED test matrix

The RED test file is
`tests/external_datasets/red/test_finqa_typed_program.py`.

| RED test | Required future behavior |
| --- | --- |
| adjacent-year mismatch | reject wrong period as `temporal_mismatch` |
| same-year metric mismatch | reject wrong row/metric as `metric_mismatch` |
| reversed 2019/2020 operands | reject as `direction_mismatch` |
| thousand/million mixture | compute with canonical scale, not raw display values |
| percent/decimal normalization | normalize percent to a ratio deterministically |
| parenthesized negative | preserve negative sign and provenance |
| model-generated constant | reject as `literal_only_operand` |
| non-admitted evidence | reject as `unadmitted_source` |
| same value, different source | produce distinct stable candidate IDs |
| previous-step reference | execute a bounded multi-step program |
| divide by zero | reject as `divide_by_zero` |
| equivalent program | accept valid commutative variants with the same result |

Additional planned Gate B/C tests:

- property-based numeric-format normalization and stable-ID invariants;
- differential execution against an independent `Decimal` reference;
- mutation targets that remove temporal, unit, literal, and provenance checks;
- structured-output integration with a fake model, then a separately labelled
  live local-model test;
- checkpoint contract drift and resume;
- protocol hash freeze and public-evidence schema.

Hypothesis is not currently pinned in `requirements.txt`; Gate B must either
pin it as an explicit test dependency or implement an equivalent deterministic
generated-case contract. Gate A does not modify dependencies.

## 13. Planned later gates

### Gate B: candidate extraction

Implement the deterministic extractor and private/public candidate manifests.
No LLM.

### Gate C: typed planner and compiler

Add a separately versioned typed answerer. Do not mutate historical planner
semantics in place.

### Gate D: multiple programs

Generate at most 2-4 typed programs and rank only with runtime-visible
compatibility, provenance, execution, intent, and complexity signals.

### Gate E: retrospective development

Use disclosed dev sets only. Publish
`RETROSPECTIVE_DEVELOPMENT_ONLY`, including prevented operand failures,
new refusals/regressions, failure reasons, cost, and latency.

### Gate F: confirmatory freeze

Before any result is observed, bind:

- code SHA;
- model digest;
- prompt hash;
- candidate-extraction config;
- DSL/validator/compiler/intent versions;
- exact sample IDs;
- B0/B1/B2/B3 arms;
- metrics, confidence intervals, McNemar, and adoption gates;
- runtime, timeout, checkpoint, failure, and rollback contracts;
- public-evidence projection.

An optional reranker is a separate predeclared B4 arm only if new evidence
shows retrieval remains the dominant bottleneck.

## 14. Gate A exit condition

Gate A is complete only when:

1. this design is reviewed;
2. the RED tests fail because the planned typed-program module is absent;
3. the pre-Gate-A deterministic baseline remains recorded;
4. no Gate B implementation exists;
5. no model run or dataset result is produced;
6. no push occurs before user approval.

## 15. Gate A execution record

Observed after adding only this document and the RED test file:

```text
targeted RED tests       12 failed as expected
RED failure boundary     missing finqa_typed_program module
existing FinQA tests     74 passed / 35 deselected / 3 warnings
full suite excluding RED 2610 passed / 29 skipped / 3 warnings
public audit             996 candidates / 0 findings
RED compileall           PASS
git diff check           PASS
```

All 12 RED cases fail at the same explicit Gate A boundary:

```text
Gate A RED: app.external_datasets.finqa_typed_program
does not exist until Gate B/C is approved
```

This is intentional TDD red state. It is not an implementation regression and
must not be pushed into normal CI before Gate B is approved and the missing
module starts turning these contracts green.
