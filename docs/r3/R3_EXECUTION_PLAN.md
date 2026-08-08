# R3 Execution Plan

## Scope

R3 improves evidence quality and interview reproducibility rather than feature
count. The only excluded activity is real independent double-human review.

## Gates

1. `S0_BASELINE_FROZEN`: bind the accepted SHA and consumed populations.
2. `S1_COHORT_FROZEN`: select unused companies into development, validation,
   fixed test and reserve before evaluating any R3 candidate.
3. `S2_PAGE_RETRIEVAL`: compare the unchanged Dense baseline with bounded page
   continuity candidates. Select on validation nDCG@5; execute test once.
4. `S3_END_TO_END`: evaluate numeric answer correctness, grounding and page
   citations with deterministic UDA scoring. Execute test once only after the
   answer policy is frozen.
5. `S5_SECURITY`: expand the paired retrieved-content attack/benign population;
   Guard mode remains the only experimental variable.
6. `S6_DEMO_CLOSEOUT`: publish a small one-command demo, runbook, evidence index,
   full regression, public audit and resume-safe claims.

## Final status

| Gate | Status | Decision |
|---|---|---|
| S0 baseline | `COMPLETED` | Accepted revision `169e84e` frozen; consumed populations recorded. |
| S1 cohort | `COMPLETED` | 48 unused companies split before candidate evaluation; 28 additional companies reserved. |
| S2 page retrieval | `VALIDATION_REJECTED` | Page-max failed both quality gates; fixed test was not opened. |
| S3 end-to-end answer | `DEVELOPMENT_REJECTED` | Typed numeric route was materially worse than direct generation; validation and test were not opened. |
| S4 human review | `NOT_RUN_HUMAN_REQUIRED` | Two independent human reviewers cannot be simulated by this agent. |
| S5 security | `COMPLETED_STRESS_ONLY` | Expanded current-Guard paired stress passed; fixture is recombined and not a new blind holdout. |
| S6 closeout | `COMPLETED` | Offline tour, reports, evidence index, engineering journal, regression and repository audit published. |

The rejected S2/S3 outcomes are completed experiments, not unfinished
implementation. They preserve the production baseline and prevent a weaker
candidate from being merged for presentation value.

## Promotion rules

### Page retrieval

- validation Page Hit@5 delta at least `+0.05`;
- validation nDCG@5 delta at least `+0.03`;
- candidate p95 no more than `1.5x` baseline;
- no page may be exposed without the same document ACL/Guard boundary.

### End-to-end answer

- validation numeric accuracy delta at least `+0.05`;
- grounded numeric accuracy must not decrease;
- unsupported-answer rate must not increase;
- test policy and prompt/compiler bytes must be frozen before one-shot test.

### Security

- same attacks, benign documents, model, retrieval and seed in OFF/ON arms;
- report ASR, context exposure, benign false-positive rate, task utility and
  deterministic Guard overhead;
- no `100% secure` or benchmark-wide claim.

## Stop rules

- A failed gate is a publishable negative result, not permission to lower the
  threshold or inspect test labels repeatedly.
- The R3 test is not used to repair the selected R3 candidate.
- After S6, further work requires a new unused population or a new product
  requirement. No framework is added merely to make the architecture diagram
  larger.

## Next admissible work

Only two follow-ups remain scientifically justified:

1. complete the existing packet with two genuinely independent human
   reviewers; or
2. design one table/layout-aware evidence representation on development data,
   preserve all 28 reserve companies, and preregister promotion gates before
   any reserve evaluation.

A prompt-only planner, another framework or repeated access to the R3 fixed
test is explicitly out of scope.
