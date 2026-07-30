# FinQA Gate E4: v2.3 Paired Calibration

## Decision

`CALIBRATION_REJECTED`.

Gate E4 executed the frozen v2.3 intervention on the same disclosed 60-case
calibration cohort used by Gates E2 and E3. It reused the sealed B0 and v2.2
rows, made new model calls only for v2.3, and left the 40-case internal
validation cohort and frozen test untouched.

| Arm | Coverage | Strict execution | Grounded execution | Protocol errors | Mean / p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 stored | 98.33% | 51.67% | 43.33% | 1/60 | 1.07s / 1.46s |
| v2.2 stored | 81.67% | 26.67% | 25.00% | 11/60 | 2.19s / 3.38s |
| v2.3 intervention | 73.33% | 20.00% | 18.33% | 16/60 | 2.90s / 4.78s |

Relative to v2.2, v2.3 lost 6.67 percentage points of strict and grounded
accuracy, changed six correct rows to wrong, and changed two wrong rows to
correct. Relative to B0 it lost 31.67 strict points and 25 grounded points,
with 22 regressions and three fixes.

Only the two latency gates, the Gate E3 input prerequisite, and the fail-closed
regression prerequisite passed. All accuracy, coverage, protocol-error, and
regression gates failed. Internal validation therefore remains `NOT_RUN`.

## What changed

Gate E3's versioned numeric evidence path was connected to a version-aware
v2.3 host validator:

1. bounded table/text closure is proposed;
2. every closure unit is scanned by `RetrievedContentGuard`;
3. v2 numeric candidates are reconstructed from source spans;
4. at most 24 candidates enter the model prompt;
5. `qwen3:8b` returns one operation template and ordered candidate IDs;
6. the host compiles the sketch and executes it with `Decimal`;
7. answer and citation metrics are computed against the same frozen cases.

The old v2.2 validator could not be reused because v2 candidate IDs bind
additional provenance and dual-value fields. It correctly rejected those
candidates as `missing_provenance`. The v2.3 validator reconstructs the v2
identity directly instead of fabricating a v1 identity.

## Why input quality did not become answer quality

Gate E3 established that 58/60 post-shortlist inputs contain all coarse gold
numeric values. Gate E4 found:

- 44 answers were emitted;
- only 12 were strict-correct and 11 were grounded-correct;
- 32 were validly compiled but semantically wrong;
- 16 ended in protocol errors;
- the gold programs contain 32 single-step and 28 multi-step cases;
- the v2.3 sketch compiler emits exactly one host operation.

Gold output-operation slices make the bottleneck visible:

| Gold output operation | Cases | Answered | Strict-correct |
| --- | ---: | ---: | ---: |
| divide | 40 | 29 | 10 |
| subtract | 11 | 8 | 2 |
| add | 7 | 6 | 0 |
| greater | 1 | 0 | 0 |
| table_average | 1 | 1 | 0 |

The protocol errors were six `metric_mismatch`, four
`unsupported_operation`, two `direction_mismatch`, two `invalid_arity`, and
two `unit_mismatch`. This is primarily semantic operation/operand planning,
not missing numeric input and not Decimal arithmetic.

## Evidence and verification

Private per-case artifacts remain under:

`.private/external_datasets/finqa/v23_calibration_runs/finqa-v23-paired-calibration-v1`

Public aggregate evidence:

`docs/external_datasets/evidence/finqa_v23_paired_calibration_public_v1.json`

Its SHA-256 is:

`33ebc048aff192ec5842729366c0e40f054d2391c31afb94ca69ed78d4db12da`

The public projection excludes case IDs, questions, answers, evidence text,
candidate IDs, gold program text, and generated program text. It includes
source hashes, model identity, exact execution revision, gate checks, and
aggregate failure slices.

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_finqa_v23_calibration_public `
  --public-only

.\.venv\Scripts\python.exe -m scripts.verify_finqa_v23_calibration_public
```

The first command validates the public artifact without private data. The
second rebuilds the projection from private details and the pinned FinQA dev
file.

The private verifier now also recomputes all arm summaries and paired
comparisons from the 60 detail rows, checks the ordered case-ID hash, validates
each comparator result, and can recompute the complete decision against the
frozen protocol.

## Literature-driven next step

Gate E5 must change the planning experiment, not weaken validation.

- FinQA separates retrieval and program generation, and its maintainers
  publicly corrected a row-format leakage bug; this supports retaining
  versioned data contracts and end-to-end measurement:
  https://github.com/czyssrs/FinQA
- TAT-QA extracts relevant table/text facts before applying symbolic
  aggregation operators:
  https://aclanthology.org/2021.acl-long.254/
- Program of Thoughts delegates exact computation to an interpreter:
  https://arxiv.org/abs/2211.12588
- FINDER combines generative fact retrieval with dynamically selected
  in-context Program-of-Thought examples:
  https://aclanthology.org/2025.emnlp-main.1577/
- Structure-aware table retrieval explicitly preserves header/value
  relationships:
  https://arxiv.org/abs/2309.10506

The proposed Gate E5 experiment therefore has three separately measurable
stages:

1. predict a bounded operation skeleton, including multi-step step references;
2. assign semantic operand roles using row, column, period, unit, and evidence
   context;
3. retrieve a small set of training-only structural demonstrations before
   model generation, then execute only through the existing host validator.

Before new model calls, Gate E5 must freeze an ablation protocol for:

- v2.3 versus multi-step skeleton only;
- multi-step plus semantic role assignment;
- multi-step plus roles plus dynamic demonstrations;
- strict/grounded accuracy, coverage, protocol errors, regression transitions,
  model calls, and latency;
- no access to the 40-case internal-validation cohort until calibration gates
  pass.

No result in Gate E4 justifies enabling the typed route or adding a resume
accuracy claim.
