# R2-S8 Learning Guide

## 1. Why deterministic 56/56 was not enough

The old retrieval gate asks whether required documents were found, whether the
authoritative version was selected, and whether ACL-forbidden documents leaked.
Those are important invariants. They do not answer whether the remaining
documents are useful.

In the expanded synthetic test:

- retrieval pass rate was 56/56;
- answerable `document_recall@5` was 1.0;
- `precision@5` was about 0.246;
- mean invalid extra documents at five was about 3.62.

That means the correct document was usually present, but the context could
still contain several distractors. An interview-safe explanation is:

> Recall answers “did I retrieve the needed evidence?” Precision answers “how
> much of what I retrieved was useful?” A RAG system needs both because noisy
> context increases cost and can mislead generation.

## 2. Why two reviewers are required

A single human score has no measurement of reviewer reliability. With two
independent reviewers, raw agreement shows how often labels match and Cohen's
kappa discounts agreement expected from each reviewer's label distribution.
For ordinal relevance labels, weighted kappa penalizes a `0` versus `2`
disagreement more than a `1` versus `2` disagreement.

R2-S8 does not mix every label into one kappa. Raw agreement is macro-averaged
across dimensions, Cohen's kappa applies to overall answer acceptability, and
retrieval uses weighted kappa. This prevents a large candidate pool from
hiding an answer-level disagreement.

Low agreement means the evidence is inconclusive or the rubric is ambiguous. It
does not automatically mean the system failed.

## 3. Why expected mode can be visible while machine verdict stays hidden

This workflow is reference-based outcome grading. Reviewers may use the frozen
reference answer, expected response mode, and authorized source evidence to
apply the same rubric. They must not see which model produced the answer,
whether the automatic evaluator passed it, or which failure stage the machine
assigned. The purpose is to prevent model/score anchoring while retaining a
consistent grading reference.

This is not a verdict-blind study. Seeing the expected mode can anchor refusal
judgements, so project claims must call it reference-guided review. A future
verdict-blind arm would need a separate frozen protocol.

## 4. Why uncertain cannot remove a difficult query

If one uncertain candidate caused the entire query to disappear from retrieval
metrics, reviewers could unintentionally inflate results by being uncertain on
hard cases. The evaluator now keeps the query and computes a conservative
bound: uncertain returned evidence receives grade 0, while uncertain candidate
evidence receives grade 2 in the ideal pool. The uncertainty rate is still
reported and gated separately.

## 5. Why `NOT_RUN` is a useful result

`NOT_RUN` distinguishes an implemented evaluation system from completed
evidence. Without it, an empty template or a test fixture can accidentally
appear as a successful human evaluation. In this project:

- blank reviewer packet: `NOT_RUN`;
- synthetic software labels: `FIXTURE_ONLY`;
- completed dev pilot: `CALIBRATION_COMPLETE`;
- insufficient or unreliable held-out evidence: `INCONCLUSIVE`;
- reliable held-out evidence below threshold: `FAILED`;
- reliable held-out evidence meeting every gate: `SUPPORTED`.

## 6. Why an LLM judge is not the next source of truth

An LLM judge can scale semantic diagnostics, but it can drift with model
versions, prefer certain styles, share errors with the answer model, or obey an
instruction embedded in retrieved content. Therefore G4 will bind the exact
judge model, prompt, configuration, and output, and compare it with human
consensus. It cannot replace ACL, secret-leak, or unsafe-action hard gates.

## 7. The Windows hash bug

Windows text files often use CRLF bytes. Python text reading may normalize them
to LF. One hash cannot honestly mean both “the original source file” and “the
exact text shown to a reviewer.” R2-S8 stores:

- `source_artifact_sha256`: original bytes;
- `content_sha256`: displayed UTF-8 text.

This is provenance modeling, not a platform workaround.
