# FinQA Gate E10 Current Handoff

## Authoritative state

- CV decision: `E10_CV_GATE_FAILED_INTERNAL_VALIDATION_PROHIBITED`
- E8 OOF Descriptor Recall@4: `84.8894%`
- E10 OOF Descriptor Recall@4: `85.8349%`
- Delta: `+0.9455pp`; frozen minimum: `+1.0000pp`
- Five fold deltas: all positive
- Serving champion: `finqa_deterministic_descriptor_retriever_v5`
- E10 serving: `DISABLED`
- Internal validation: `NOT_RUN`, budget unconsumed
- Frozen test: `UNTOUCHED`

## Completed work

1. Replaced gold-forced `model_input` training evidence with official
   `retrieved_all` Top-10-or-all-available selection.
2. Preserved Guard, evidence closure, candidate identity and safe descriptor
   boundaries.
3. Replaced pointwise binary regression with pairwise E8-hard-negative fitting.
4. Removed the learned E8 score and candidate-count features and bounded the
   residual adjustment to `[-4, +4]` around E8.
5. Ran deterministic five-fold company-disjoint OOF evaluation over 3,068
   eligible cases, 99 companies and 5,923 role groups.
6. Preserved write-once private details, aggregate public evidence, protocol
   erratum, negative-decision postmortem and SHA-chain tests.

## Incidents

The first full run revealed 66 reports with fewer than 10 official retrieval
units and stopped before evidence writes. The protocol was corrected before a
successful training/outcome run. A first JSON edit targeted the wrong nested
object and was rejected by strict Pydantic validation. An instance-scope bug
and an invalid pair-count guard were caught by focused tests before evidence
generation. Exact details are in the E10 engineering record.

## Next admissible work

Do not lower the E10 threshold, rerun the consumed E9 development cohort, run
the internal 40 cases, or touch frozen test. A future E11 must use new versioned
files and nested company-grouped CV so model/feature/hyperparameter choices
happen only in inner folds. Outer-fold results must remain one-shot and must
authorize any internal-cohort run under a newly frozen protocol.

Recommended model for E11 protocol, leakage and nested-CV design:
**5.6 Sol / Extra High**.
