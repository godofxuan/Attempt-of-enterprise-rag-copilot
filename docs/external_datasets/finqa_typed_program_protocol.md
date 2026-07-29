# FinQA Temporal Operand Alignment and Typed Financial Program Protocol

Status: `GATE_C_TYPED_PLANNER_VALIDATOR_COMPILER_IMPLEMENTED_LOCAL_UNPUSHED`

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

## 16. Gate B implementation record

Gate B was approved after Gate A commit `904c129`. This stage implements only
deterministic numeric-candidate extraction and redacted candidate evidence. It
does not implement a typed planner, compatibility validator, compiler,
multi-program ranking, or any model-backed experiment.

### 16.1 Files and responsibilities

| File | Gate B responsibility |
| --- | --- |
| `app/external_datasets/finqa_typed_program.py` | Strict candidate/source/provenance models, Decimal normalization, stable IDs, FinQA cell adapter, corpus aggregation, redacted manifest projection |
| `tests/external_datasets/test_finqa_numeric_candidates.py` | Format matrix, table-header inheritance, temporal ambiguity, noise roles, stable identity, admitted evidence, and deterministic generated cases |
| `scripts/build_finqa_numeric_candidate_manifest.py` | Duplicate-key-safe fixture loading, exact source-byte hashing, atomic no-overwrite publication, and byte-for-byte verification |
| `data/v2/public/finqa_numeric_candidates/source_fixture.json` | Synthetic public mechanism fixture; it is not a FinQA development or test result |
| `docs/external_datasets/evidence/finqa_numeric_candidate_manifest_v1.json` | Redacted, independently recomputable candidate manifest |
| `tests/external_datasets/test_finqa_numeric_candidate_manifest.py` | Checked-in evidence recomputation and CLI behavior |
| `tests/external_datasets/red/test_finqa_typed_program.py` | Two Gate B extraction contracts are green; ten Gate C contracts are strict expected failures |

### 16.2 Implemented data flow

```text
FinQA structured JSON table
  -> inspect only admitted evidence row IDs
  -> keep each data cell separate
  -> attach explicit table ID, row header, and column header
  -> deterministic lexical extraction
  -> Decimal base-unit normalization
  -> exact character-span provenance
  -> source-bound stable candidate ID
  -> private in-memory candidate corpus
  -> aggregate-only public manifest
```

The FinQA adapter intentionally bypasses the historical row-to-sentence
flattening for candidate extraction. For example, the two values in:

```text
["Revenue", "$120 million", "$100 million"]
```

remain separate candidates bound to `Revenue/2020` and `Revenue/2019`.
The model is not asked to recover those coordinates from prose.

### 16.3 Normalization and uncertainty semantics

- currency glyphs/codes, comma grouping, explicit scale suffixes, percent,
  basis points, leading minus, and parenthesized negatives are normalized with
  `Decimal`;
- table cells inherit period and metric only from explicit row/column headers;
- text operands inherit a period only when their bounded clause contains one
  unique explicit year;
- ambiguous multi-year text keeps period and fiscal year unknown;
- page numbers, ordinals, and year labels receive non-operand roles;
- unknown entity, metric, period, or unit values remain unknown;
- contradictory unit or scale evidence fails closed;
- candidate identity binds extraction version, source/evidence identity,
  table coordinates, exact span/hash, normalized value, unit, scale, sign, and
  role. It never depends on list position.

The deterministic generated-case contract is used instead of adding an
unpinned Hypothesis dependency. It checks repeated extraction, formatting,
normalization, provenance, and stable-ID invariants over a fixed format
matrix.

### 16.4 Failures found while implementing Gate B

The first format test run produced two failures:

1. The numeric boundary rejected `42.` at normal sentence end because the
   decimal-safety check treated every trailing period as part of a malformed
   decimal.
2. The generic number matcher did not find the year in `FY2020` because the
   preceding `Y` correctly blocked an ordinary word-adjacent number.

The fix did not globally relax boundaries. A trailing period/comma is now
rejected only when it is followed by another digit, and explicit years have a
separate bounded period-label scan. The focused suite changed from
`14 passed / 2 failed` to `16 passed`, then to `20 passed` after the FinQA cell
adapter and manifest tests were added.

### 16.5 Public evidence

The synthetic manifest reports:

```text
source records        6
numeric candidates    9
roles                 operand 6 / ordinal 1 / page_number 1 / period_label 1
source kinds          table_cell 3 / text 6
units                 usd 2 / ratio 2 / shares 1 / unknown 4
audit                 1002 candidates / 0 findings
```

It contains no source text, case ID, evidence ID, candidate ID, question,
answer, or gold program. `candidate_id_set_sha256` permits set-level integrity
checking without publishing individual identifiers.

### 16.6 Verification

```text
Gate B focused tests        20 passed
external-dataset tests      119 passed / 10 xfailed
full repository tests       2632 passed / 29 skipped / 10 xfailed / 3 warnings
manifest byte check         PASS
compileall                  PASS
git diff --check            PASS
public repository audit     1002 candidates / 0 findings
```

The three warnings are pre-existing SWIG deprecation warnings. The ten strict
expected failures are the unimplemented Gate C planner/compiler contracts.
They are strict so an unexpected pass fails CI until Gate C is formally
implemented and the pending marker is removed.

### 16.7 Claim and parser boundary

Gate B proves deterministic extraction behavior on unit tests and a synthetic
public fixture. It does not show that FinQA answer accuracy improved. No model,
disclosed dev result, frozen test result, or confirmatory cohort was run.

It also does not solve raw-document layout recovery. The current PDF parser
keeps page locators but has no OCR, table detector, merged-cell reconstruction,
multi-column layout model, repeated-header removal, or cross-page table
stitching. DOCX/HTML/CSV/JSONL tables retain explicit rows and headers, and the
chunker repeats table headers, but raw PDF cross-page tables require a separate
layout-aware ingestion stage and cell-level evaluation.

## 17. Gate C implementation record

Gate C was approved after Gate B commit `b63c87e`. This stage implements the
typed planner boundary, compatibility validator, and deterministic Decimal
compiler. It does not run a real model, tune prompts on disclosed cases,
implement multiple-program ranking, or publish an answer-quality result.

### 17.1 New files and changed contracts

| File | Gate C responsibility |
| --- | --- |
| `app/external_datasets/finqa_typed_program.py` | Candidate/step reference schemas, typed DSL, stable validation errors, compatibility validation, Decimal execution, immutable result/provenance/diagnostics |
| `app/external_datasets/finqa_typed_planner.py` | Deterministic minimal intent extraction, reference-only prompt/schema, bounded retry, fake/live-compatible chat boundary |
| `tests/external_datasets/test_finqa_typed_program.py` | Schema, literal, provenance, admission, temporal, metric, unit, scale, sign, direction, step, budget, differential, immutability, and no-eval contracts |
| `tests/external_datasets/test_finqa_typed_planner.py` | Intent, prompt/schema, retry/exhaustion, allowlist, context budget, parser, and full structured-table fake-model integration |
| `tests/external_datasets/red/test_finqa_typed_program.py` | All 12 Gate A RED contracts are now normal green tests |
| `docs/external_datasets/evidence/finqa_numeric_candidate_manifest_v2.json` | Current source binding without overwriting the historical Gate B manifest |

The historical `LocalFinQAProgramAnswerer` and its literal-expression protocol
remain unchanged. The new planner is a separate class and can therefore be
compared against the old answerer instead of silently changing a frozen
baseline.

### 17.2 Runtime path

```text
runtime question
  -> deterministic FinancialQuestionIntent (unknown fields remain unknown)
  -> admitted NumericCandidate allowlist
  -> typed-planner prompt + JSON Schema
  -> model emits candidate/previous-step references only
  -> host parses duplicate-key-safe JSON
  -> host parses extra=forbid TypedProgram
  -> host validates candidate and evidence closure
  -> host validates financial compatibility
  -> host executes approved AST with Decimal
  -> immutable result + step values + provenance + diagnostics
```

The JSON Schema improves model reliability but is not trusted as the security
boundary. A fake or non-conforming model can return any bytes; the host repeats
all schema, identity, admission, compatibility, and resource checks.

### 17.3 Fixed validation order

The fail-closed boundary checks:

1. canonical JSON size, step/argument budgets, operation allowlist, and strict
   DSL schema;
2. absence of raw numeric values, `literal`, `value`, `number`, `expression`,
   and extra fields;
3. unique candidates, contiguous step IDs, backward-only step references, and
   final output-step identity;
4. exact raw-text span/hash and deterministic reconstruction of normalized
   value, unit, scale, and sign;
5. candidate membership in the admitted evidence set and `role=operand`;
6. target/start/end period compatibility;
7. requested and cross-operand metric/entity compatibility;
8. unit and scale compatibility;
9. directional operand order and operation arity;
10. zero denominator, Decimal precision/magnitude budget, and output unit/scale.

Errors expose only a stable `reason` and bounded message. The validator never
reads gold programs, answers, strict correctness, retrieval labels, or paired
transitions.

### 17.4 DSL and execution behavior

V1 permits only:

```text
ADD SUB MUL DIV PERCENT_CHANGE RATIO AVERAGE
```

All steps are `step-01` through `step-08`. Arguments are exactly one
`CandidateRef` or one earlier `StepRef`. `PERCENT_CHANGE(new, old)` calculates
`(new-old)/old`; division checks zero before execution. ADD/SUB/AVERAGE require
compatible units and metrics. Multiplication requires at least one
dimensionless ratio. Division admits equal units or a ratio denominator.

Execution uses a local Decimal context with precision 50 and a magnitude
budget of `1e30`. Every intermediate result is retained in an immutable mapping.
The final result includes ordered candidate/evidence closure, program hash,
validation hash, counts, precision, and compiler/validator versions.

### 17.5 Typed Planner boundary

`LocalFinQATypedProgramPlanner` receives only:

- the runtime question;
- admitted operand candidates;
- an optional bounded map of already-admitted evidence text;
- a runtime-only `FinancialQuestionIntent`.

Its response schema has no literal or expression field. A failed host
validation may trigger at most two attempts by default and three by hard
limit. The repair message contains the stable reason and candidate allowlist,
not gold data or the correct program.

The deterministic intent extractor is intentionally conservative. It
recognizes explicit signals for percent change, average, ratio, difference,
sum, multiplication, and division. It derives percent-change direction from
two explicit periods. It does not invent metric/entity labels from free text.
An unrecognized operation fails as `ambiguous_intent`.

### 17.6 Additional failures found during Gate C

Six review and verification findings changed the implementation or the
acceptance procedure:

1. A valid raw-text hash did not by itself prove that `normalized_value` came
   from that text. The validator now reruns the deterministic extractor over
   the exact span and compares value, unit, scale, and sign before execution.
2. Pydantic `frozen=True` did not make the nested `step_values` dictionary
   immutable. The result now uses the repository's frozen-mapping pattern with
   a JSON serializer.
3. Adding validator/compiler code changed the source hash recorded by the Gate
   B candidate manifest. Gate B v1 was not overwritten. Its byte SHA remains
   `b24813f5310ba132fa68e9da7502398750ec06d36d0747750971357abc450b01`;
   v2 binds the current source while tests require the candidate-ID-set,
   extraction-config, and fixture hashes to remain unchanged.
4. A syntactically valid but substituted `candidate_id` was not recomputed at
   the execution boundary. The validator now derives the ID again from the
   canonical source identity and rejects a mismatch before program execution.
5. `MUL(amount, ratio)` and `DIV(amount, ratio)` originally lost the
   value-carrying operand's metric/entity metadata. A following compatible
   `ADD` could therefore fail closed. The compiler now propagates metadata from
   the value-carrying state and a valid two-step regression proves the behavior.
6. Moving pytest's base directory to `.tmp` caused four trusted-identity tests
   to reject temporary JWKS/HMAC paths outside `.private`. The security rule was
   not weakened; final D-drive verification used a `.private` temporary root.

### 17.7 Deterministic evidence

The focused Gate C contracts include:

- all 12 original Gate A RED cases;
- four forbidden literal shapes and extra-field/unknown-operation rejection;
- candidate ID, provenance, normalized-value, sign, and admission tampering;
- non-operand, unknown-period, unknown-metric, unit, and scale failures;
- forward/duplicate/missing steps, arity, payload, prompt, context, and
  magnitude budgets;
- independent Decimal reference comparisons over generated value pairs;
- stable program/validation hashes and immutable intermediate values;
- AST inspection proving no direct `eval` or `exec` call;
- fake-model success, bounded repair, bounded exhaustion, allowlist filtering,
  an end-to-end structured FinQA table path, and a valid two-step
  amount-ratio-addition path.

No real Ollama call, disclosed dev evaluation, frozen test run, or accuracy
comparison occurred in Gate C.

### 17.8 Current limitations

- intent extraction is a narrow deterministic heuristic, not a complete
  financial semantic parser;
- text candidates without explicit metric/period metadata may fail closed;
- V1 emits canonical base-unit results only;
- dimensional algebra is intentionally limited and does not represent compound
  units such as USD/share;
- `part_over_total` semantic roles are not independently typed yet;
- one typed program is attempted at a time; multiple-program verification is
  Gate D;
- planner retry state is in-process and is not yet an immutable resumable model
  run;
- raw PDF layout and cross-page table recovery remain outside this layer.

### 17.9 Gate C verification

```text
Gate C focused tests       43 passed
external-dataset tests     162 passed
full repository tests      2674 passed / 30 skipped / 0 xfailed / 3 warnings
manifest byte check        PASS
Gate B v1 immutability     PASS
Gate B/C candidate parity PASS
compileall                 PASS
git diff --check           PASS
public repository audit    1006 candidates / 0 findings
```

The three warnings are the pre-existing SWIG deprecation warnings. Gate C adds
no dependency and leaves the worktree free of private model or dataset output.
