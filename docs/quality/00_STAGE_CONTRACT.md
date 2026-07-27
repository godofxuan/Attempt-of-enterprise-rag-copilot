# R2-S8 Independent Quality Evidence Contract

## 1. Objective

R2-S8 establishes evidence for retrieval and answer quality that is independent
of the deterministic evaluator which produced the answer. It does not add
another retrieval or generation feature. It makes quality claims traceable,
reviewable, and falsifiable.

The stage covers:

- model/verdict-blinded, reference-guided review packets bound to an immutable
  source run and dataset;
- two independent human judgements per selected item;
- explicit disagreement and adjudication records;
- agreement and uncertainty reporting;
- optional LLM-judge calibration against human consensus;
- a release gate that fails closed when required evidence is incomplete.

## 2. Baseline finding frozen at G0

The repository already has deterministic retrieval, answer, agent, and security
checks and an older blank `human_review.csv` export. That export is useful for
finding examples, but it is not independent quality evidence because it:

- combines development and frozen-test examples;
- prioritizes machine failures, so its pass rate is not an unbiased population
  estimate;
- exposes case metadata but has no immutable rubric or packet hash;
- accepts free-form cells without a validated label domain;
- has no reviewer identity separation, double review, adjudication, or
  agreement calculation;
- has no mechanism that prevents blank cells from being treated as completed;
- contains no completed human judgements.

Accordingly, the following remain `NOT RUN`: human double review, semantic judge
calibration, and independent held-out quality acceptance.

## 3. Threats to validity

| ID | Threat | Required control |
|---|---|---|
| QTV-01 | Reviewer sees model identity or machine pass/fail | Reviewer packet excludes model, variant, machine labels, failure stages, and source case IDs |
| QTV-02 | Development feedback contaminates held-out acceptance | Calibration and held-out purposes are distinct; held-out results cannot be used for tuning |
| QTV-03 | Error-enriched sampling is reported as overall accuracy | Sampling strategy is manifest-bound; only eligible probability samples may estimate aggregate quality |
| QTV-04 | One reviewer is mistaken or inconsistent | At least two distinct reviewer identities per item |
| QTV-05 | Disagreement is silently converted to pass | Disagreement remains unresolved until a distinct adjudicator records a decision |
| QTV-06 | Empty or malformed labels count as success | Strict schemas reject blanks and labels outside the frozen domain |
| QTV-07 | Review artifacts are edited after scoring | SHA-256 bindings and no-overwrite publication |
| QTV-08 | LLM judge agrees with itself rather than people | Judge is optional and cannot be admitted before calibration against human consensus |
| QTV-09 | Deterministic ACL checks are replaced by subjective grading | Authorization and secret-leak gates remain code-based hard gates |
| QTV-10 | Public synthetic review is described as production validation | Claim status and evidence population are explicit in every summary |
| QTV-11 | One person changes salts to appear as two reviewers | One coordinator-held identity pepper defines a shared identity domain; cross-domain submissions cannot aggregate |
| QTV-12 | A returned-only set is renamed `pooled_variants` | Every pooled item binds at least two unique run-manifest hashes including the evaluated run |
| QTV-13 | `uncertain` removes a difficult retrieval query from metrics | Returned uncertainty scores as grade 0 and candidate-pool uncertainty as grade 2 for conservative metric bounds |
| QTV-14 | Candidate count dominates agreement statistics | Raw agreement is a dimension macro-average; overall Cohen's kappa and retrieval weighted kappa are separate |
| QTV-15 | Unweighted stratified sample is reported as population quality | Held-out acceptance requires `all_cases` until inclusion weights are schema-bound |

## 4. Gate sequence

| Gate | Status | Deliverable | Exit condition |
|---|---|---|---|
| G0 | COMPLETE | Baseline, threats, requirements, non-claims | Contract and traceability frozen |
| G1 | COMPLETE (tooling) | Immutable blinded review packet | Publish/verify round trip, no overwrite, provenance hashes |
| G2 | COMPLETE (tooling) | Strict independent submission ingestion | Two distinct reviewers, complete labels, attestation checks |
| G3 | COMPLETE (tooling) | Consensus, disagreement, adjudication, agreement | Deterministic summary and fail-closed incomplete status |
| G4 | COMPLETE (tooling); real calibration NOT RUN | Optional LLM-judge calibration | Human-bound agreement/error report; never an ACL substitute |
| G5 | READY FOR TWO HUMANS; NOT RUN | Real human execution | Required independent labels actually collected |
| G6 | NOT RUN | Public evidence and release decision | Sanitized package verifies and claims match evidence |

G0-G4 tooling may proceed without a human. G5 cannot be marked complete by
Codex and must not use fabricated labels.

## 5. Requirements

| ID | Requirement |
|---|---|
| QR-01 | Every reviewer-visible item has an opaque ID and excludes source case ID, model identity, machine verdict, and machine failure labels |
| QR-02 | Every packet binds source run, source manifest, dataset, rubric, item set, and sampling policy by hash |
| QR-03 | Publication is atomic and refuses overwrite |
| QR-04 | Calibration and held-out acceptance are distinct purposes |
| QR-05 | Held-out aggregate claims require the complete frozen `all_cases` population and complete review coverage |
| QR-06 | Every item requires two distinct independent reviewers |
| QR-07 | Reviewer IDs are shared-domain HMAC pseudonyms; raw personal identity and the coordinator pepper are not published |
| QR-08 | Labels are strict enums with applicability rules and a bounded rationale |
| QR-09 | Unresolved disagreement cannot become pass |
| QR-10 | Adjudicator must be distinct from both original reviewers |
| QR-11 | Summary reports counts, rates, disagreement, agreement, adjudication, and incomplete/uncertain cases |
| QR-12 | LLM-judge results are admitted only after calibration against human consensus with prompt/model/run provenance |
| QR-13 | Security/ACL release decisions remain deterministic hard gates |
| QR-14 | No real quality claim is emitted from fixture-only or blank review data |
| QR-15 | Every document in the declared retrieval candidate pool receives an ordinal `0/1/2/uncertain` relevance label |
| QR-16 | The evidence verifier recomputes metrics and the decision from source labels |
| QR-17 | Reviewer-visible content hash and source-file byte hash remain distinct |
| QR-18 | Pooled candidate claims bind at least two unique run manifests including the evaluated source run |
| QR-19 | One source ID cannot carry conflicting content across returned, candidate, and reference lists |
| QR-20 | Every allowed candidate can receive a label; packet and judgement capacities cannot drift |
| QR-21 | Retrieval uncertainty contributes a conservative bound and cannot remove a query from metric denominators |
| QR-22 | Agreement reports dimension-macro raw agreement, overall-answer Cohen's kappa, and ordinal retrieval weighted kappa separately |
| QR-23 | Packet/control partial publication is recoverable only when existing artifacts exactly match the current source/spec |
| QR-24 | Judge stability compares every pair of repeated trials |
| QR-25 | Reference-guided mode visibility is disclosed and is not called verdict-blind review |

## 6. Frozen label dimensions

Human review covers:

- factual correctness;
- completeness;
- citation/evidence support;
- refusal appropriateness;
- access safety;
- overall acceptability;
- primary failure stage;
- bounded rationale.

Dimension labels are `pass`, `fail`, `uncertain`, or `not_applicable`.
`overall_acceptability` is limited to `pass`, `fail`, or `uncertain`.
Retrieved-document relevance is `0` (irrelevant), `1` (partially relevant), `2`
(directly relevant), or `uncertain`.

## 7. Preregistered held-out thresholds

The packet manifest freezes these defaults before labels exist:

| Metric | Threshold |
|---|---:|
| Held-out item count | at least 60 |
| Raw structured-label agreement | at least 0.80 |
| Overall-answer Cohen's kappa | at least 0.70 |
| Retrieval weighted kappa | at least 0.70 |
| Overall answer acceptance | at least 0.80 |
| Human relevance precision@5 | at least 0.60 |
| Human relevance recall@5 | at least 0.85 |
| Human nDCG@5 | at least 0.80 |
| Uncertain-label rate | at most 0.10 |
| Access-safety failures | exactly 0 |

Insufficient sample size, unresolved disagreement, undefined/low agreement, or
excess uncertainty yields `INCONCLUSIVE`. Once evidence reliability passes,
quality below threshold yields `FAILED`; all thresholds passing yields
`SUPPORTED`.

A final held-out packet must declare `candidate_pool_strategy=pooled_variants`.
The pool must include the frozen returned ranking plus independently generated
retrieval variants, so relevant documents missed by the evaluated ranking can
still receive a human grade. `returned_only` and `returned_plus_reference` are
allowed for development/calibration but force a held-out decision to
`INCONCLUSIVE`.

`raw_label_agreement` is the macro-average of equally weighted label
dimensions. `cohens_kappa` applies only to `overall_acceptability`; ordinal
document relevance has its own weighted kappa. Candidate-document volume
therefore cannot dominate answer-level reliability.

The current protocol is reference-guided: expected response mode, reference
answer, and authorized reference evidence are visible. It is blind to model
identity and machine verdicts, not blind to the grading reference. Any future
verdict-blind study must use a separately versioned packet/rubric.

## 8. Non-claims

Until G5 and G6 complete on an eligible independent population, this project
must not claim:

- human-verified factual accuracy;
- calibrated LLM-as-a-judge quality;
- independent held-out answer quality;
- production quality or production traffic validation.

## 9. External design basis

The protocol follows the evaluation separation described in Anthropic's
agent-evaluation guidance: combine deterministic, model-based, and human
graders; distinguish capability evaluation from regression; and inspect
outcomes and trajectories. NIST AI RMF guidance motivates documented,
transparent TEVV and explicit human oversight.

- https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- https://airc.nist.gov/airmf-resources/airmf/5-sec-core/
