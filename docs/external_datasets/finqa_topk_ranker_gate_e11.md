# FinQA Gate E11: Top-4 Boundary Ranker with Nested Company CV

## Decision

```text
outer train-development gate   PASSED
one-shot internal gate         PASSED
serving                        DISABLED
frozen test                    UNTOUCHED
next stage                     SHADOW_ONLY_INTEGRATION
```

E11 is the first learned descriptor challenger in this sequence to pass both
its frozen train-development gate and a separate one-shot internal cohort. It
does not establish answer accuracy, statistical significance, production
financial reliability or serving authorization.

## Problem carried forward from E10

E10 fixed E9's gold-forced evidence and unbounded pointwise ranking. Its five
company folds all improved, but aggregate Descriptor Recall@4 increased only
`0.9455pp`, below the frozen `1pp` gate. E10 also trained every positive against
many hard negatives even when those pairs could not change the Top-4 hit.

E11 focuses training on swaps that can change the actual metric:

```text
E8 misses the role:
    highest E8-ranked positive below Top-4
        versus each negative currently inside Top-4

E8 has exactly one positive inside Top-4:
    that positive
        versus up to four nearest negatives below Top-4

E8 has at least two positives inside Top-4:
    no single swap can lose role Recall@4, so add no pair
```

Each role contributes a fixed total miss or preservation weight, divided over
its pairs. Reports with many descriptors therefore cannot dominate merely by
creating more pairs.

## Relationship to established learning-to-rank work

The design is inspired by LambdaRank's principle of weighting score changes by
their effect on a non-smooth ranking metric. LightGBM's LambdaRank documentation
likewise connects training truncation to the target cutoff `k`.

- [LambdaRank paper, Microsoft Research](https://www.microsoft.com/en-us/research/publication/learning-to-rank-with-non-smooth-cost-functions/)
- [LightGBM LambdaRank parameters](https://lightgbm.readthedocs.io/en/v4.5.0/Parameters.html)

E11 does not claim to implement LambdaRank or LambdaMART. It is a deterministic
linear weighted-pair surrogate implemented with the repository's existing
NumPy dependency. No LightGBM, XGBoost or sklearn dependency was added.

## Code map

- `finqa_topk_ranker_protocol_v1.py` validates source hashes, five company
  folds, the exact 18-configuration grid, nested selection rules, holdout
  budget, gates and non-claims.
- `finqa_topk_ranker_v1.py` builds Top-4 miss/preservation pairs, solves weighted
  L2 ridge, validates the self-hashing artifact and implements the bounded
  runtime selector.
- `finqa_topk_ranker_training_v1.py` executes inner configuration selection,
  outer evaluation, transition accounting and final configuration selection.
- `train_finqa_topk_ranker_v1.py` rebuilds E10's exact retrieval-realistic
  inputs, verifies all upstream hashes and writes immutable artifact/CV ledgers.
- `audit_finqa_topk_internal_v1.py` validates authorization and runs E8/E11 on
  the same one-shot internal inputs, Guard, catalog and candidate reranker.
- `test_finqa_topk_ranker_evidence.py` recomputes the public SHA chain and
  prevents a passing result from being represented as serving authorization.

## Weighted linear fit

For every selected positive/negative descriptor pair, E11 computes the same 21
value-free feature difference used by E10:

```text
d_i = z(x_positive) - z(x_negative)
```

If `a_i` is the per-pair weight, the fitted coefficients solve:

```text
minimize sum_i a_i * (w dot d_i - 1)^2 + lambda * ||w||^2
```

The implementation forms:

```text
(D.T A D + lambda I) w = D.T A 1
```

and uses `numpy.linalg.solve()`. Runtime score remains:

```text
E8 score + clip(w dot z(x), -1, 1) * max_adjustment
```

The candidate grid freezes `max_adjustment={2,4,8}`, `L2={1,10,100}` and
`preservation_weight={0.25,1.0}`: 18 configurations. Every configuration keeps
the same features, Top-4 cutoff, miss weight, tie rule and maximum pair depth.

## Why nested company CV is required

Choosing the best configuration and reporting its score on the same folds is
optimistically biased. For each outer fold, E11 performs:

```text
outer held companies: never used for this round's configuration choice
remaining four folds:
    choose one as inner validation
    train on the other three
    repeat four times for each of 18 configurations
select configuration by:
    inner Recall@4 descending
    then regression count ascending
    then frozen safety order
fit selected configuration on all four outer-train folds
evaluate exactly once on outer held companies
```

The five selected outer configurations vote for the final all-train artifact;
ties use the frozen candidate order. E11 openly marks this as train-development
evidence because E9/E10 previously informed design on the same FinQA train
split. The separate internal cohort is the confirmation layer.

## Outer result

```text
prepared cases                 2925/3068 = 95.34%
labelable cases                2881/3068 = 93.90%
role groups                    5923
final pair count               19864
model calls                    0

metric                         E8           E11          delta
Descriptor Recall@4            84.8894%      86.0881%     +1.1987pp
```

```text
outer fold   chosen configuration       delta       regressed / gained
0            adj08-l2-001-p025         +0.4230pp        5 / 10
1            adj08-l2-100-p025         +2.2298pp        1 / 27
2            adj08-l2-010-p100         +1.6625pp        7 / 27
3            adj08-l2-100-p025         +1.0888pp       10 / 23
4            adj08-l2-010-p025         +0.5942pp        5 / 12
```

Across all 5,923 roles: 5,000 retained, 28 regressed, 99 gained and 796 missed
by both. Every outer fold improved. Fold-recall population standard deviation
was `1.2289pp`; minimum coefficient cosine was `0.9157`. All frozen gates
passed. The modal final configuration was `adj08-l2-100-p025`.

## One-shot internal result

The authorized cohort contains 40 cases and a frozen SHA for the exact ten
selected units per case. Only `case_id` and `selected_unit_ids` were projected
from the old private retrospective ledger into the evaluator.

Three cases hit a common typed capability boundary: one produced no typed
skeleton and two failed strict semantic skeleton validation. Both arms took the
same fail-closed fallback. The other 37 cases contain 76 evaluated roles.

```text
metric                              E8            E11           delta
Descriptor Recall@4                 84.21%         86.84%        +2.63pp
Descriptor complete case@4          75.68%         81.08%        +5.41pp
Candidate Recall@8                  84.21%         86.84%        +2.63pp
Candidate complete case@8           75.68%         81.08%        +5.41pp
Conditional candidate retention    100.00%        100.00%         0.00pp
```

Descriptor and Candidate transitions were identical: 64 retained, zero
regressed, two gained and ten missed by both. Catalog SHA, candidate identity,
input-order invariance, Guard-before-projection, zero model calls and common
input identity all passed.

## Internal execution incident

The first internal command stopped on the first case before writing any result.
The reused E8 audit helper constructed its typed oracle before its local
exception boundary, and the internal cohort exposed a repeated-reference
contract absent from E8's 60-case calibration.

The repair added a shared pre-selector capability boundary. Unsupported typed
contracts now become identical `FALLBACK_ROUTED` rows for both arms; exceptions
after the selector split remain failures. The incident file records that no
artifact or result existed before the repair. The completed run remains ordinal
one, not a second observation of model quality.

## Statistical and product interpretation

The internal result passes the preregistered non-regression gate, but has only
two discordant improvements. Its exact two-sided McNemar p-value is `0.5`, so
it is not statistically significant evidence of a general efficacy gain. The
outer train-development evidence also contained 28 regressions despite a
positive net result.

Therefore:

- E11 may proceed to shadow-only engineering and observability;
- the E11 artifact cannot replace E8 in serving;
- the internal 40 cases are consumed for E11 and cannot be tuning data;
- the frozen test remains untouched;
- no answer-accuracy or production claim is allowed.

## Reproduction and verification

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.train_finqa_topk_ranker_v1
& '.\.venv\Scripts\python.exe' -m scripts.audit_finqa_topk_internal_v1
& '.\.venv\Scripts\python.exe' -m pytest tests\external_datasets\test_finqa_topk_ranker_evidence.py -q
```

The first two commands reproduce immutable outputs. They must not be used to
tune and overwrite E11; different bytes are rejected.

