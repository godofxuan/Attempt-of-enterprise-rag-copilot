# R3 Answer and Citation Evaluation

## Pre-run status

- Status: `NOT_RUN`
- Dataset: UDA Finance R3 company-disjoint cohort
- Retrieval: unchanged Dense chunk baseline, document-conditioned through the
  existing ACL boundary
- Answer model: `qwen3:8b`
- Answer model digest:
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`
- Frozen protocol SHA-256:
  `30b4842153eaf3596649c0143e350c502dbc4c14c85ec606dbad50f52e1c38ee`

## Compared strategies

`direct` asks the guarded local model for one final answer, a calculation
description and evidence IDs. It is the unchanged generation baseline.

`typed_candidate` extracts bounded numeric candidates from admitted evidence.
The model can select candidate IDs and one of seven operations, but it cannot
submit raw numeric literals. The host validates candidate membership, operation
arity and citation coverage, then executes the calculation with `Decimal`.

This separates two responsibilities:

1. the model decides which evidence values and operation express the question;
2. deterministic code performs the arithmetic and records the exact operands.

The retrieved text is still untrusted. Every evidence unit passes through the
existing retrieved-content Guard before either strategy sees it.

## Metrics

- Numeric accuracy uses UDA's symmetric relative error below 1 percent.
- Evidence Page Hit@5 asks whether retrieval included the gold page.
- Citation precision and recall compare cited pages with the gold page.
- Grounded numeric accuracy requires both a correct answer and a gold-page
  citation.
- Unsupported-answer rate counts emitted answers without a gold-page citation.
- Generation and calculator calls plus mean and p95 latency record cost.

## Frozen decision rule

The development split selects a candidate only when it improves numeric
accuracy over `direct`; grounded accuracy and p95 latency are tie-breakers. A
selected candidate then needs at least `+0.05` validation numeric accuracy,
non-decreasing grounded accuracy, non-increasing unsupported-answer rate and no
more than `2x` p95 latency. The fixed test remains untouched unless all
validation gates pass.

Validation and test execution markers are created with exclusive file creation.
Re-running either split against the same private evidence root fails closed.
