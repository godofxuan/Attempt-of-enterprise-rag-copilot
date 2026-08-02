# FinQA Gate E9: Company-Disjoint Learned Descriptor Ranker

## Decision

`E9_DEVELOPMENT_GATE_FAILED_KEEP_E8_CHAMPION`

E9 is a scientifically useful negative result. The train-only grouped
cross-validation gate passed, but the single authorized disclosed-development
run regressed. The deterministic E8 retriever therefore remains the champion,
the E9 challenger remains disabled, internal validation is `NOT_RUN`, and the
frozen test is `UNTOUCHED`.

## What changed

E9 added a trainable but interpretable descriptor-ranking path without changing
the hash-bound E8 catalog or candidate reranker:

```text
question + typed role + safe descriptor
                  |
                  v
        23 value-free features
                  |
                  v
 balanced L2 ridge linear score
                  |
                  v
 Top-4 descriptor IDs only
                  |
                  v
 unchanged E8 host mapping and candidate reranker
```

The implementation is split by responsibility:

- `finqa_learned_ranker_protocol_v1.py` validates the frozen data, feature,
  fold, gate and fallback contract.
- `finqa_learned_descriptor_ranker_v1.py` extracts runtime-safe features,
  fits the deterministic linear model, validates the hash-sealed artifact and
  implements the challenger plus E8 fallback.
- `finqa_learned_ranker_training_v1.py` applies company isolation, deterministic
  grouped folds, train-only label construction and OOF evaluation.
- `train_finqa_learned_descriptor_ranker_v1.py` produces the model artifact,
  private case ledger and aggregate CV evidence.
- `audit_finqa_learned_descriptor_ranker_v1.py` performs the single formal
  disclosed-development comparison while reusing E8 inputs and reranking.
- `audit_finqa_learned_descriptor_postmortem_v1.py` derives paired failure
  evidence from the already persisted E8/E9 rows; it does not rerun evaluation.

## Leakage boundary

The pinned train split has 6,251 cases and 135 companies. The disclosed
60-case development cohort contains 35 companies, and all 35 also occur in the
train split. A random case split would therefore allow the model to see the
same companies during training and evaluation.

E9 excludes every train case from those 35 companies. It also excludes exact
normalized development-question duplicates. The resulting cohort is:

```text
company-disjoint rows before capability filtering     3,289
supported add/subtract/multiply/divide rows            3,068
eligible companies                                        99
fold row counts                          614/615/613/613/613
fold company counts                         18/21/20/20/20
```

Each company belongs to exactly one fold. Fold assignment sorts companies by
case count and a seeded SHA-256 rank, then greedily places each company into
the currently smallest fold. This keeps groups disjoint while balancing rows.

The official `qa.model_input` is used only to choose train evidence IDs. Every
one of the 3,068 eligible rows contains its gold evidence in that field. This
is disclosed as a limitation: train CV measures ranking conditional on this
evidence contract, not end-to-end retrieval.

## Feature and model contract

The feature vector contains 23 values. It includes the E8 score, bounded token
overlap counts/ratios, period match/conflict, exact phrase presence, descriptor
field-presence flags, source kind, role period flags and `log1p(candidate_count)`.

It explicitly excludes case/company/file identities, answers, gold programs,
gold evidence IDs, descriptor/candidate IDs, numeric values and raw numeric
text. Gold programs create offline binary labels only. The runtime feature
function cannot accept a gold program or answer argument.

The fixed model minimizes weighted squared error with L2 regularization:

```text
sum_i class_weight(y_i) * (y_i - intercept - w*x_i)^2
    + 10 * sum_j w_j^2
```

Features are standardized from each training fold only. Positive and negative
classes receive inverse-frequency weights. There is no random initialization,
hyperparameter search or LLM call; NumPy solves the linear system directly.
The artifact stores only feature names, means, scales, coefficients, intercept,
counts and source hashes. Its internal SHA-256 validator rejects coefficient
tampering.

## Data incidents and fixes

The training run attempted all 3,068 frozen eligible cases:

```text
prepared cases                         2,932  (95.57%)
labelable cases                        2,891  (94.23%)
role groups                            5,952
descriptor examples                   54,936
positive examples                      7,365
preparation failures                     136
normalized empty table cells           1,213
```

Three important issues were found:

1. The official train split contains one `text_-1` gold evidence key. It belongs
   to an already excluded development company. Selection was changed to apply
   the frozen minimal metadata boundary before full `FinQACase` validation;
   selected rows still receive full validation.
2. Empty table cells caused the existing E8 numeric source model to reject an
   empty string. E8 is hash-bound and was not edited. E9 normalizes empty cells
   to the nonnumeric placeholder `N/A`, preserves table shape and records all
   1,213 replacements.
3. 136 rows still failed preparation. The public ledger preserves aggregate
   reasons including unsupported constants, repeated semantic references,
   contradictory suffix/scale data, duplicate candidate identities and source
   candidate budget overflow. These rows are not silently counted as success.

## Train-only grouped CV

```text
metric                                  E8 score     E9 learned
OOF Descriptor Recall@4                   88.76%         90.84%
absolute delta                                            +2.08pp
E9 fold Recall@4             89.00/92.41/91.79/89.89/91.14%
E9 fold population stddev                                1.24pp
```

All frozen CV and integrity gates passed. This authorized one formal run on
the already disclosed 60-case development cohort. It did not authorize serving,
internal validation or frozen-test access.

## Single development result

```text
metric                                  E8 champion      E9 challenger    delta
Descriptor Recall@4                         84.55%            78.86%     -5.69pp
Descriptor complete case@4                  82.76%            77.59%     -5.17pp
Candidate Recall@4                          66.67%            60.98%     -5.69pp
Candidate Recall@8                          78.86%            75.61%     -3.25pp
Candidate complete case@8                   74.14%            72.41%     -1.72pp
Conditional candidate retention@8           93.27%            95.88%     +2.61pp
Candidate edge reduction                    75.10%            74.01%     -1.09pp
```

The learned selector improved the second-stage conditional retention but lost
too many first-stage descriptors. It failed every frozen development quality
gate except conditional retention. Security, identity, order invariance, Guard,
zero-model-call and serving-disabled checks all passed.

## Paired postmortem

Across 123 roles:

```text
E8 hit -> E9 hit       93
E8 hit -> E9 miss      11
E8 miss -> E9 hit       4
both miss              15
net role change        -7
```

The 11 descriptor regressions include four `total`, three `comparison_right`,
two `part` and two `comparison_left` roles. Eight of those 11 cases had at most
32 source candidates, so the issue is not only catalog size.

The strongest absolute learned coefficients were question-primary overlap
ratio, candidate-count log, E8 score and local-question overlap. The learned
model gave candidate count a larger standardized coefficient than E8 score;
question-primary overlap count and ratio also received opposite signs. These
are warning signs of correlated pointwise features, not causal explanations.

The best-supported diagnosis is a combination of:

1. train/serving evidence-distribution mismatch because train `model_input`
   forces gold evidence coverage;
2. pointwise binary regression does not directly optimize role-level Top-4
   recall;
3. an unbounded learned score can overturn a strong deterministic ordering;
4. correlated features produce unstable coefficient signs across domains.

## Engineering decision

E9 is not promoted. E8 remains the serving champion and serving remains
disabled for the FinQA typed route. The formal E9 development budget is
consumed and must not be reused after tuning.

A future E10 may use train-only work, but it must freeze a new protocol that:

- builds retrieval-realistic evidence without forced gold injection;
- uses pairwise/listwise Top-4 training and company-grouped evaluation;
- learns only a bounded residual around E8;
- measures coefficient stability and feature ablations;
- does not rerun E9's 60 development cases;
- does not consume internal validation or frozen test.

## Reproduction

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.train_finqa_learned_descriptor_ranker_v1
& '.\.venv\Scripts\python.exe' -m scripts.audit_finqa_learned_descriptor_ranker_v1
& '.\.venv\Scripts\python.exe' -m scripts.audit_finqa_learned_descriptor_postmortem_v1
& '.\.venv\Scripts\python.exe' -m pytest tests\external_datasets\test_finqa_learned_ranker_evidence.py -q
```

The second command is retained for reproducibility, not for tuning repetitions.
Its output is write-once and the formal ordinal is fixed at one.

