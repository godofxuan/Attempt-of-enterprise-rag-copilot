# FinQA Gate E Typed-Program Retrospective

Status: `COMPLETE_REJECTED`

Claim boundary: `RETROSPECTIVE_DEVELOPMENT_ONLY`

This record describes a real local-model evaluation on a previously disclosed
FinQA development cohort. It is not a held-out result, a production benchmark,
or evidence that the typed planner should be adopted.

## 1. Decision

`B1_TYPED_SINGLE` and `B2_TYPED_MULTI` are rejected for adoption.

Both interventions reduced strict accuracy by more than 50 percentage points,
reduced coverage below 12%, introduced at least 88 new non-answers, increased
mean latency by more than 12 times, and prevented none of the 21 historical
operand-selection failures. Gate F must not spend a new independent holdout on
the current implementation.

The next step is a separate disclosed-development contract-calibration gate.
It must repair intent coverage and candidate/operation compatibility before a
new confirmatory protocol is considered.

## 2. Frozen question and comparison

Gate E asked whether reference-only typed programs prevent real operand errors
without unacceptable refusal, regression, or latency costs.

The protocol was frozen before model calls in
`docs/external_datasets/evidence/finqa_typed_retrospective_protocol_v1.json`.
It binds:

- the already disclosed 100-case development cohort and its case-ID hash;
- the historical hybrid Top-10 evidence rows, so retrieval is identical;
- `qwen3:8b` digest
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`;
- source evaluation and diagnostic artifact hashes;
- extraction, intent, DSL, validator, compiler, planner, and selector versions;
- 11 execution-source SHA-256 values;
- two attempts, three B2 programs, a 120-second request timeout, and no
  quality-based early stopping;
- a cyclic B0/B1/B2 execution order;
- the explicit prohibition on accessing the frozen test split.

The runtime implementation and protocol were committed before results as
`9180b7ecd61bbabc1f00edc2929877c471fa769b`.

The arms were:

| Arm | Runtime behavior |
| --- | --- |
| `B0_FREE_LITERAL` | Historical Qwen expression planner plus host AST/Decimal calculator |
| `B1_TYPED_SINGLE` | One reference-only typed program, then Gate C validation and Decimal compilation |
| `B2_TYPED_MULTI` | Three typed candidates, independent Gate C validation, then deterministic Gate D selection/refusal |

## 3. Implemented files

| File | Responsibility |
| --- | --- |
| `app/external_datasets/finqa_typed_retrospective.py` | Strict protocol/private/public schemas, summaries, paired statistics, immutable publication, and aggregate verification |
| `scripts/eval_finqa_typed_retrospective.py` | Source/hash/model checks, exact historical evidence replay, cyclic arms, Guard admission, resumable real-model execution, final seal |
| `scripts/publish_finqa_typed_retrospective.py` | Aggregate-only public projection |
| `scripts/verify_finqa_typed_retrospective_public.py` | Public accounting checks and historical Git-blob source verification |
| `tests/external_datasets/test_finqa_typed_retrospective.py` | Fake-model end-to-end arms, metric accounting, tamper detection, and no-case-content public boundary |
| `docs/external_datasets/evidence/finqa_typed_retrospective_dev_v1_public_v2.json` | Verified aggregate result |

Private case rows and checkpoints remain under
`.private/external_datasets/finqa/` on the D drive and are Git-ignored.

## 4. Execution path

```text
frozen historical case order
  -> load the exact stored Top-10 evidence IDs
  -> scan evidence with RetrievedContentGuard
  -> deterministic numeric-candidate extraction
  -> execute B0/B1/B2 in cyclic order
  -> evaluate strict numeric and grounded citation correctness
  -> append one hash-chained case record
  -> recompute all aggregate metrics from 100 records
  -> atomically publish private manifest/details/summary
  -> verify artifact hashes and write checkpoint seal
  -> derive content-free public v2 evidence
  -> verify public arithmetic and Git source snapshot
```

Transport or Ollama failures abort the run and preserve the checkpoint. They
are not converted into wrong answers. Bounded model-output failures are stored
as `PROTOCOL_ERROR`; deterministic intent or selection failures are stored as
`REFUSED`.

## 5. Final results

| Metric | B0 free literal | B1 typed single | B2 typed multi |
| --- | ---: | ---: | ---: |
| answered / 100 | 99 | 9 | 11 |
| coverage | 99% | 9% | 11% |
| strict accuracy | 57% | 5% | 6% |
| accuracy among answered | 57.58% | 55.56% | 54.55% |
| grounded strict accuracy | 50% | 5% | 6% |
| refusals | 0 | 36 | 89 |
| protocol errors | 1 | 55 | 0 |
| generation calls | 101 | 122 | 118 |
| mean latency | 1.090 s | 13.280 s | 15.897 s |
| p95 latency | 1.390 s | 32.017 s | 33.336 s |

Paired B0-to-intervention outcomes:

| Metric | B1 | B2 |
| --- | ---: | ---: |
| strict delta | -52 pp | -51 pp |
| grounded strict delta | -45 pp | -44 pp |
| wrong to correct | 2 | 1 |
| correct to wrong | 54 | 52 |
| new non-answers | 90 | 88 |
| new refusals | 36 | 88 |
| new protocol errors | 54 | 0 |
| prevented historical operand failures | 0 / 21 | 0 / 21 |
| exact McNemar p-value | `4.43e-14` | `1.20e-14` |
| generation-call multiplier | 1.208x | 1.168x |
| mean-latency multiplier | 12.181x | 14.581x |

The p-values show a strong paired difference on this reused development
cohort, but the direction is harmful. They are exploratory, not confirmatory.

Fresh B0 correctness reproduced the historical B0 correctness label on 98% of
cases. The two differences were historical correct-to-current wrong, so the
current B0 result is 57% instead of the historical 59%.

## 6. Failure attribution

Exactly 36 cases failed deterministic intent extraction before B1/B2 model
generation. The other 64 reached both typed planners.

For B1:

- 9 of 64 model-invoked cases produced an accepted answer;
- the final failure reasons were 13 additional `ambiguous_intent`,
  17 `unsupported_operation`, 7 `metric_mismatch`, 6 `unit_mismatch`,
  6 `temporal_mismatch`, 4 `invalid_arity`, and 2 `direction_mismatch`;
- the 9 answered cases were only 5/9 correct.

For B2:

- 11 of 64 model-invoked cases produced a selected answer;
- 52 ended `NO_VALID_PROGRAM`;
- 1 ended `AMBIGUOUS`;
- the 11 answered cases were only 6/11 correct.

The historical diagnostic-category cross-tab was:

| Historical category | Cases | B0 correct | B1 answered/correct | B2 answered/correct |
| --- | ---: | ---: | ---: | ---: |
| `correct_grounded` | 52 | 50 | 5 / 3 | 7 / 5 |
| `correct_citation_incomplete` | 7 | 7 | 0 / 0 | 0 / 0 |
| `operand_selection_signal` | 21 | 0 | 0 / 0 | 2 / 0 |
| `composition_or_scale_signal` | 6 | 0 | 2 / 1 | 2 / 1 |
| `operation_plan_signal` | 1 | 0 | 1 / 1 | 0 / 0 |
| `retrieval_miss` | 12 | 0 | 1 / 0 | 0 / 0 |
| `unsupported_gold_operation` | 1 | 0 | 0 / 0 | 0 / 0 |

This rejects the original operand-error hypothesis. B1's two fixes came from
composition/scale and operation-plan categories; B2's one fix came from
composition/scale. Neither arm fixed an operand-selection case.

## 7. Why the mechanism failed

The failure is primarily a system-contract mismatch, not enough evidence to
blame only the Qwen model:

1. `extract_financial_question_intent` admits only a narrow lexical operation
   vocabulary. Thirty-six questions are rejected before model generation.
2. The validator requires the output operation to equal one coarse intent.
   Real FinQA programs and language often imply multi-step calculations whose
   final primitive does not match that lexical label.
3. `ADD`, `SUB`, `AVERAGE`, and `PERCENT_CHANGE` require compatible
   metric/entity metadata. Valid financial questions may intentionally combine
   different rows, while text candidates often have incomplete metadata.
4. Unit and scale typing is conservative, but the corpus contains header-level
   units, dimensionless counts, ratios, and implicit units that are not fully
   represented by the v1 type lattice.
5. Generating three candidates cannot repair a shared bad intent or validator
   contract. B2 mostly produces three variants that fail the same host rules.
6. Accepted output was only about 55% correct, so merely weakening fail-closed
   rules would increase coverage without establishing correctness.

## 8. Measurement bugs found and repaired

The model run itself completed without transport failure, but post-run review
found two evaluation-observability defects:

1. Private v1 named a field `new_refusal_count` while it counted every new
   non-answer, including protocol errors. Public v2 recomputes three separate
   fields from immutable case rows: `new_non_answer_count`,
   `new_refusal_count`, and `new_protocol_error_count`.
2. `TypedPlannerProtocolError` did not expose compiler calls from failed B1
   attempts. Future runs now preserve `compiler_calls`; the public v2 result
   omits B1 compiler/program totals because the sealed v1 rows cannot recover
   them exactly.

The private run was not edited or overwritten. Public v2 records these
limitations and binds the original private manifest and details hashes.

## 9. Verification

Pre-run:

```text
focused Gate B/C/D/E tests  52 passed
external-dataset tests      183 passed
compileall                  PASS
public repository audit     1013 candidates / 0 findings
validate-only               VALIDATED_NOT_EXECUTED
```

Public evidence:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_finqa_typed_retrospective_public `
  --evidence docs\external_datasets\evidence\finqa_typed_retrospective_dev_v1_public_v2.json `
  --protocol docs\external_datasets\evidence\finqa_typed_retrospective_protocol_v1.json
```

The verifier reports:

```text
status                  VERIFIED
execution revision      9180b7ecd61bbabc1f00edc2929877c471fa769b
historical source files 11
selected cases          100
private manifest SHA    af0147d358f8ae684867d17d1c0664a1440353a0b536121b889f07000f8db2ae
private details SHA     e5c1ff768b907626f007279e9e1ea02e2a7eadb3cc07b730825bcff63f7078e2
```

It validates public accounting and reads source bytes from the historical Git
commit, so later evaluation-code fixes do not invalidate the old experiment.

Post-result closeout:

```text
external-dataset tests     183 passed
full repository tests      2695 passed / 30 skipped / 3 warnings
compileall                 PASS
pip check                  no broken requirements
public repository audit    1017 candidates / 0 findings
git diff --check           PASS
```

The warnings are the pre-existing SWIG deprecation warnings.

## 10. Next gate

The next gate is `Gate E2: typed contract calibration`, still on disclosed dev
data. It should:

1. create a content-free failure matrix from the 91 B1 and 89 B2 non-answers;
2. expand intent representation beyond one lexical output operation;
3. add explicit composition intent and operation-sequence compatibility;
4. model row metric, entity, header unit, scale, count, and ratio provenance;
5. separate unknown metadata from proven incompatibility;
6. preserve literal/admission/provenance/sign/divide-by-zero fail-closed rules;
7. rerun B1 first and require meaningful coverage before spending on B2;
8. require positive operand-failure fixes, bounded regression, and acceptable
   latency on disclosed dev before Gate F can be proposed.

Gate F remains blocked. No frozen test rerun is authorized.
