# UDA FinHybrid Page-Retrieval Protocol

Status: `DEV COMPLETE; DENSE SELECTED; FROZEN TEST NOT RUN`

## Purpose

FinanceBench development failures showed that page ranking, not document
discovery, is the main retrieval bottleneck. UDA-QA FinHybrid is therefore used
as an external-author page-localization check over long financial-report PDFs.
The benchmark question is conditioned on a known document, matching UDA's
document-question-answer contract. This experiment does not measure open-corpus
document discovery.

## Pinned sources

- UDA-Benchmark Git revision:
  `fca5237ac316e776d8dbccffa55ca29c0efdc185`.
- UDA-QA Hugging Face revision:
  `d4367103fe8fe86b3bb76c66be8eafc4fb4117b2`.
- `dataset/qa/fin_qa.csv` SHA-256:
  `2a0a671027852d6ba7bda429d1a5d62b5a7b440ab7e98779853088b1c3f2e8a5`.
- License: CC-BY-SA-4.0.

Raw labels, PDFs, indexes, and per-question outputs stay under `.private/` on
drive D. The public repository contains only the protocol and aggregate,
content-free evidence.

## Frozen selection

The adapter groups rows by report and company ticker. Reports with fewer than
eight questions are excluded. Companies are ordered by SHA-256 over the fixed
seed and company ID; one report per company and eight questions per report are
selected by separate stable hashes.

- development: 8 companies, 8 reports, 64 questions;
- frozen test: 12 different companies, 12 reports, 96 questions;
- selection SHA-256:
  `cf167cfa4603f6d0877650721b73aec952c5ec4e8ed6d461d4eed33c401b1e4e`.

No retrieval result was produced before this selection was frozen. The labels
are public, so this is an externally authored fixed test, not a hidden or
independently administered blind holdout.

## Decision rule

Run BM25, Dense, and BM25 + Dense + RRF on development using the same PDFs,
chunks, BGE-M3 index, top-k values, and hardware. Select the highest development
Page nDCG@5. Break an exact tie by Page Hit@5, then lower p95 latency. Execute the
selected configuration once on the 96-case test.

Report Page Hit@1/3/5, MRR@5, nDCG@5, Macro Page Recall@5, mean/p50/p95 query
latency, index build time, embedding calls, and artifact hashes. Do not tune on
the test result or compare it numerically with FinanceBench as if the splits were
the same population.

## Development selection

At code revision `eb7b7824ad85c4a16ea119e5adeaccb7e86cd502`, Dense achieved
the highest development Page nDCG@5 (`0.665396`), narrowly above RRF
(`0.661425`) and above BM25 (`0.531742`). The frozen choice is therefore Dense.
RRF's higher Hit@1 and MRR do not change the preregistered primary metric. The
content-free aggregate is stored in `evidence/uda_finance_dev_selection_v1.json`.
