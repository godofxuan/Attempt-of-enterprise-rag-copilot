# WixQA BGE Reranker V2 Protocol

## Objective

Test whether a domain-strong multilingual reranker can convert the previously
measured WixQA dense candidate headroom into better final Top-5 article ranking.
This is a model-family follow-up after the registered MiniLM arms were rejected;
it does not rewrite or invalidate that negative result.

## Pre-freeze knowledge

- The 200-case simulated cohort and its dense/MiniLM aggregate results are known.
- Dense candidate Recall was 61.42% at 5, 72.00% at 10, and 84.58% at 20.
- A two-case BGE quality smoke was observed only to validate runtime wiring; it is
  too small to support model selection or a quality claim.
- A dataset-free batch smoke established that batch size 4 fits the local GPU.
- No full-cohort BGE result was observed before this protocol was frozen.

## Frozen identities

- Candidate generator: the existing `bge-m3` WixQA flat index.
- Reranker: `BAAI/bge-reranker-v2-m3` at exact revision
  `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.
- Reranker weight SHA-256:
  `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286`.
- Runtime: RTX 5060, CUDA 12.8 PyTorch wheel, batch size 4.
- Candidate chunk budget: 200; final article budget: 5.

## Registered development arms

1. reranker Top-10, no dense-head protection;
2. reranker Top-10, preserve dense rank 1;
3. reranker Top-20, preserve dense rank 1.

All arms run on the same ordered 200-case simulated cohort. The selection order
is nDCG@5, Recall@5, MRR@5, then p95 latency. No thresholds or arms may change
after a full arm result is observed.

## Admission gate

Against the dense arm from the same run, an arm must satisfy all of:

- Recall@5 delta >= 0;
- nDCG@5 delta >= 0.02;
- p95 end-to-end latency multiplier <= 5.0.

Passing this gate permits only a retrospective ExpertWritten confirmation run.
It does not authorize default-runtime promotion or an independent-blind claim.
The historically consumed ExpertWritten cohort must not be run if every
development arm fails.

## Evidence boundary

- This experiment evaluates article retrieval/ranking, not answer correctness.
- The simulated cohort is configuration selection, not a blind holdout.
- ExpertWritten is historically consumed and can only be labelled retrospective.
- A quality gain without the latency gate is not a deployable Pareto improvement.

