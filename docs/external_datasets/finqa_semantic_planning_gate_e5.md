# FinQA Gate E5: Semantic Planning Ablation

## Decision

`CALIBRATION_REJECTED`.

Gate E5 ran three new planning interventions on the same disclosed 60-case
development calibration cohort. It reused the byte-sealed Gate E4 B0 and v2.3
rows, used the pinned FinQA train split only for value-free structural
demonstrations, and left the 40-case internal-validation cohort and frozen test
untouched.

| Arm | Coverage | Strict | Grounded | Protocol errors | Mean / p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 stored | 98.33% | 51.67% | 43.33% | 1/60 | 1.07s / 1.46s |
| v2.3 stored | 73.33% | 20.00% | 18.33% | 16/60 | 2.90s / 4.78s |
| Direct multi-step | 8.33% | 1.67% | 1.67% | 55/60 | 8.49s / 11.72s |
| Role decomposition | 3.33% | 0.00% | 0.00% | 58/60 | 17.58s / 29.58s |
| Roles + dynamic demos | 73.33% | 21.67% | 20.00% | 16/60 | 6.86s / 12.82s |

The dynamic-demo arm was the only plausible intervention. Relative to v2.3 it
gained one strict-correct and one grounded-correct case, changed two correct
cases to wrong, changed three wrong cases to correct, and kept coverage and
protocol errors unchanged. The gain was only 1.67 percentage points, below the
frozen +10 strict and +8 grounded thresholds. It also remained 30 strict
points and 23.33 grounded points below B0.

No intervention passed every progress and shadow gate. No arm was selected,
internal validation remains `NOT_RUN`, the frozen test remains `UNTOUCHED`,
and all typed routes remain disabled.

## Frozen experiment

The protocol was committed before implementation:

- protocol commit: `5a5f474`
- protocol SHA-256:
  `30f5ad86a4ef9cfdf3e0304c71b939fe5de10d4b048f06a0c00880f04f4b42a1`
- execution implementation commit:
  `df53f7ba83fb423f9fa361bff1770fe07dee8004`
- model: `qwen3:8b`
- model digest:
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`
- temperature: `0`
- maximum program steps / roles / candidates: `3 / 6 / 24`
- attempts per stage: `2`
- demonstrations per case: `3`

The three new arms were executed in a cyclic Latin-square order. Each arm
appeared in each position exactly 20 times. This controls simple warm-up,
cache, and order effects.

## Implementation

### Value-free program contracts

`app/external_datasets/finqa_semantic_program.py` defines:

- one-to-three sequential program steps;
- backward-only step references;
- two-to-six semantic roles;
- exact role coverage;
- operation arity checks;
- allowlisted candidate binding;
- compilation into the existing typed DSL.

The model cannot provide arithmetic literals. Only an allowlisted candidate ID
or a prior step reference can reach the v2.3 host compiler and `Decimal`
execution.

### Train-only demonstrations

`app/external_datasets/finqa_semantic_demos.py`:

- verifies the exact 78,216,616-byte FinQA train file;
- parses only case ID, question, and gold program for demo construction;
- converts supported gold programs into value-free operation skeletons;
- removes numeric text from demo questions;
- excludes all FinQA dev case IDs from the demo index;
- retrieves three examples with deterministic IDF token overlap;
- records both index and per-case demo-payload hashes.

The resulting index contains 5,704 supported structural demos. All 60
calibration cases received three demos; there were 59 unique payload hashes.
No answer, operand value, evidence text, candidate ID, or document ID entered a
demonstration payload.

### Planning and execution

`app/external_datasets/finqa_semantic_planner.py` implements:

1. direct generation of a one-to-three-step candidate-bound program;
2. value-free role/skeleton generation followed by candidate binding;
3. the same two-stage route with train-only structural demonstrations.

Every response uses a strict JSON schema. The host reparses the response,
checks all graph and allowlist invariants, compiles it with the existing v2.3
validator, reconstructs numeric values from source provenance, and executes
with `Decimal`.

`app/external_datasets/finqa_semantic_runtime.py` performs the common guarded
closure, candidate extraction, and shortlist once per case, then executes all
three interventions in the frozen order. It records stage-qualified failures,
calls, latency, program hash, demo count, and demo-payload hash.

### Reproducible evaluation

`scripts/eval_finqa_semantic_planning.py` validates:

- protocol, Gate E4 public/private, train, and dev hashes;
- exact model digest;
- ordered calibration case hash;
- implementation file hashes;
- demo source isolation and index identity.

The live run uses an append-only hash-chained checkpoint and a process-local
Ollama evaluation lock. Final details, summary, and manifest are written to a
staging directory, verified, atomically activated, and sealed back into the
checkpoint.

## What the ablation proved

The direct arm produced 55 protocol errors. Forty-two were schema failures,
11 were unit mismatches, and two were metric mismatches.

The no-demo role arm produced 58 protocol errors. Twenty-eight failed at
skeleton schema generation and 29 at binding schema generation. Its mean
latency was 6.05 times v2.3.

Dynamic examples changed the role route substantially:

- coverage: `3.33% -> 73.33%`;
- protocol errors: `58 -> 16`;
- strict accuracy: `0.00% -> 21.67%`;
- grounded accuracy: `0.00% -> 20.00%`;
- mean latency: `17.58s -> 6.86s`.

This proves that structural examples help the local 8B model satisfy the
program contract. It does not prove adequate semantics. The demo arm emitted
44 valid answers, but 31 were wrong. Conditional strict accuracy among answered
cases was only `13/44 = 29.55%`, versus `12/44 = 27.27%` for v2.3.

The measured next bottleneck is role-to-candidate compatibility and operation
semantics, not missing demonstrations, arithmetic execution, or simple
multi-step syntax.

## Engineering incident

Initial Gate E5 train support modified shared `finqa.py` and
`prepare_finqa.py`. The external-dataset suite then failed three historical
source-hash tests because those files were intentionally bound by old frozen
protocols.

The fix was to restore both historical files byte-for-byte and move the train
hash, 128 MiB budget, downloader, and minimal demo loader into the new E5
module. The final external-dataset suite passed `260` tests, and the
pre-execution full suite passed `2773` tests with `29` skips and zero failures.
Historical evidence was not rewritten.

## Evidence

Private run:

`.private/external_datasets/finqa/semantic_planning_calibration_runs/finqa-semantic-planning-calibration-v1`

Private hashes:

- manifest:
  `348635d1c7d49c9082c57889fbd2764e2efce97120ade36db78f5a85edcb9bbb`
- details:
  `19d0c2ae47d9a91aaa6f5f02c1bcb99be4df66ab84ac0c36e4544f31ba12348b`
- summary:
  `866575f641d16b01a19060d0a1487221c73cd2a3fb2cc356098314c90abbd69c`

Public aggregate evidence:

`docs/external_datasets/evidence/finqa_semantic_planning_calibration_public_v1.json`

Public SHA-256:

`af46c19b688a8836f7092704c14ef684b35553cbc692d7755f3fe34e30a18271`

```powershell
.\.venv\Scripts\python.exe `
  -m scripts.verify_finqa_semantic_planning_public --public-only

.\.venv\Scripts\python.exe `
  -m scripts.verify_finqa_semantic_planning_public
```

The first command validates canonical JSON, privacy exclusions, protocol
bindings, internal consistency, and claim boundaries without private data. The
second reconstructs the complete public projection from the private run and
pinned FinQA dev split.

## Next admissible experiment

Gate E6 should not add more examples or relax validation. It should test a
host-visible compatibility layer between semantic roles and candidate facts:

1. derive deterministic role requirements for metric, entity, period, unit,
   scale, sign, and table coordinates;
2. construct a bounded compatibility matrix before model binding;
3. let the model choose only among role-compatible candidate IDs;
4. reject or deterministically resolve ambiguous bindings;
5. compare B4 with compatibility-filtered and compatibility-ranked variants
   on the same disclosed calibration cohort.

Relevant research directions include FinQA's constrained program vocabulary,
TAT-QA's evidence tagging before symbolic aggregation, candidate-expression
constraints for semantic parsing, and number-aware negative sampling in
APOLLO. These guide the design but are not directly comparable score claims.

