# FinQA Gate E10: Retrieval-Realistic Pairwise Residual Ranker

## Decision

`E10_CV_GATE_FAILED_INTERNAL_VALIDATION_PROHIBITED`

E10 repaired the direction of the E9 learning experiment: all five company-
disjoint folds improved over E8. The aggregate gain was nevertheless
`+0.9455pp`, below the frozen `+1.0000pp` authorization threshold. E8 remains
the champion, E10 is disabled, the internal 40-case budget is unspent, and the
frozen test is untouched.

## Why E10 exists

E9 trained on `qa.model_input`, which contains all gold evidence for every one
of its 3,068 eligible train cases. Runtime retrieval does not receive that
guarantee. E9 also fitted independent positive/negative descriptors and
replaced the E8 score without a bounded adjustment. Its train OOF gain did not
transfer to the disclosed development cohort.

E10 changes exactly those three assumptions:

```text
official retrieved_all rows
  -> deterministic score sort
  -> Top-10 or all available, no gold insertion or padding
  -> unchanged Guard, evidence closure, candidates and safe descriptors
  -> positive descriptor minus E8-hard-negative feature differences
  -> L2 pairwise fit
  -> E8 score + learned adjustment clipped to [-4, +4]
  -> Top-4 evaluation in company-disjoint outer folds
```

It never calls an LLM and does not alter the E8 serving route.

## Code ownership

- `finqa_pairwise_residual_protocol_v1.py` validates hashes, data boundaries,
  features, folds, gates, holdout budget and disabled serving state.
- `finqa_pairwise_residual_training_v1.py` chooses retrieval-realistic units,
  runs the existing Guard/candidate/catalog path, builds role groups and
  performs grouped OOF evaluation.
- `finqa_pairwise_residual_ranker_v1.py` defines the 21-feature pairwise model,
  self-hashing artifact and bounded runtime selector.
- `train_finqa_pairwise_residual_ranker_v1.py` binds source files, produces the
  write-once private ledger, public artifact and aggregate CV evidence.
- `test_finqa_pairwise_residual_evidence.py` verifies the SHA chain and asserts
  that the failed gate cannot be represented as an authorized result.

The successful run binds the implementation files by SHA-256. They must not be
edited in place; a future challenger needs new versioned modules.

## Training evidence boundary

The same 3,068 supported train cases and 99 companies from E9 are retained.
For each case, E10 combines official `text_retrieved_all` and
`table_retrieved_all`, sorts by descending score and ascending source ID, and
takes at most 10 unique units. It never inserts a gold ID.

```text
selected units per case     6: 12 / 7: 21 / 8: 11 / 9: 22 / 10: 3002
full gold coverage          3014/3068 = 98.24%
any gold coverage           3067/3068 = 99.97%
selection SHA-256           4a472b060d6a19a8...ac25579
```

The internal cohort has a different frozen boundary: all 40 stored inputs have
exactly 10 units. The protocol deliberately represents these facts separately.

## Pairwise objective

For each semantic role, the offline gold program identifies one or more
positive descriptors. E10 orders negative descriptors by the existing E8 score
and keeps up to eight hard negatives per positive. For standardized feature
vectors `x+` and `x-`, it fits `w` so that:

```text
w dot (x+ - x-) ~= 1

minimize ||D w - 1||^2 + 10 ||w||^2
```

This objective asks the model to rank the positive above difficult negatives,
instead of predicting an independent binary probability. Gold labels are used
only to build training differences. Runtime features contain no answer, gold
program, gold evidence ID, candidate value, numeric text, case ID or company
ID.

The learned utility cannot replace E8. It is clipped to `[-1, 1]`, rescaled to
`[-4, 4]`, and added to the E8 score. Ties use E8 score and descriptor ID. This
contains the blast radius of a poor artifact.

## Measured result

```text
prepared cases                           2925/3068 = 95.34%
labelable cases                          2881/3068 = 93.90%
role groups                              5923
training pairs                           53457
model calls                              0

metric                                E8 OOF       E10 OOF       delta
Descriptor Recall@4                  84.8894%       85.8349%    +0.9455pp
fold 0                               84.7716%       85.4484%    +0.6768pp
fold 1                               85.4202%       86.6209%    +1.2007pp
fold 2                               85.3699%       86.3674%    +0.9975pp
fold 3                               83.1658%       83.8358%    +0.6700pp
fold 4                               85.7385%       86.9270%    +1.1885pp
```

The E10 fold-recall population standard deviation was `1.1171pp`; the minimum
pairwise coefficient cosine across folds was `0.9884`. Preparation, labelable
rate, stability, no-regressed-fold, leakage, safety, determinism and disabled-
serving checks passed. Only the frozen minimum gain failed.

## Why the gate still fails

The threshold was written before seeing the CV result. Lowering it from 1.0 to
0.94 after observing `0.9455` would convert evaluation into target chasing.
The correct engineering action is to preserve the near miss and avoid spending
the next data layer.

The positive result is limited but real: E10 eliminated E9's directionally
wrong folds under a more realistic input contract. It does not establish an
internal-cohort, answer-accuracy, frozen-test or production improvement.

## Incidents and fixes

1. The first protocol assumed exactly 10 retrieved units for every train case.
   The first full preparation attempt stopped before writing artifacts because
   66 reports expose only 6-9 unique units. The contract was corrected to
   Top-10-or-all-available; no padding or row deletion was introduced.
2. The first JSON correction accidentally changed `internal_validation`
   instead of `training_boundary`. Strict Pydantic `extra="forbid"` validation
   rejected the file before training. The corrected objects now have different
   explicit schemas.
3. The first selector implementation referenced a local `artifact` name from
   instance scope. An end-to-end selector test caught it; the code now uses
   `self._artifact`.
4. An early fit guard required at least as many pairs as features. That is not
   a mathematical requirement here because positive L2 makes `D.T D + lambda I`
   invertible. The invalid guard was removed and the finite-matrix checks kept.

## Evidence and reproduction

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.train_finqa_pairwise_residual_ranker_v1
& '.\.venv\Scripts\python.exe' -m pytest tests\external_datasets\test_finqa_pairwise_residual_evidence.py -q
```

The training command is retained for deterministic reproduction. Its outputs
are write-once: a different rerun is rejected rather than overwriting evidence.

