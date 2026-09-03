# V2 Bounded Adaptive Retrieval Engineering Journal

## Stage A: Baseline Reproduction

- **Files changed:** None.
- **Reason:** Freeze the exact pre-change behavior before evaluating a new control loop.
- **Behavior changed:** None.
- **Security contracts preserved:** No code or configuration changed.
- **Tests run/passed:** `tests/agent_v2`: 134 passed at `e904616c9860c19f77fd2cb2ac7decc73dc8f4dd`.
- **Known limit:** This only establishes V2 regression health, not retrieval quality.
- **Next Gate:** Attribute a real retrieval failure cohort.

## Stage B: Current-SHA Failure Attribution

- **Files changed:** `app/evaluation/adaptive_retrieval_recoverability.py`, `scripts/diagnose_adaptive_retrieval_recoverability.py`, and their tests. These are development-only diagnostic artifacts; serving remained unchanged.
- **Reason:** Determine whether one bounded alternate query can recover a meaningful subset of initial retrieval failures.
- **Behavior changed:** None in serving.
- **Security contracts preserved:** The diagnostic obtains assessor input from guarded V2 search captures and stores question text, raw model output, and query text only under `.private`.
- **Result:** At exact baseline SHA `e904616`, 17 of 20 frozen multi-document cases lacked complete Top-5 evidence. The local `qwen3:8b` assessor produced 13 validator-accepted retry candidates; 3 recovered all gold documents in the union of both Top-5 results, 10 had no union gain, and none were worse on retry-only recall.
- **GO decision:** Met. `3 / 17 = 17.65%`, satisfying `>= 3` fully recovered and `>= 10%` of baseline failures.
- **Known limit:** The cohort was already consumed development data, so this is an implementation gate rather than a quality or resume claim.
- **Next Gate:** Add an OFF-by-default, at-most-one-retry runtime.

## Stage C: Serving Proposal Rejected

- **Files changed:** No serving files remain changed. The only retained implementation is the development-only diagnostic harness and its tests.
- **Reason:** A first local-model run met the gate with 3 fully recovered cases, but a same-configuration repeat recovered only 2. The absolute `>= 3` criterion did not reproduce.
- **Behavior changed:** None. The V2 serving path is unchanged by this work.
- **Security contracts preserved:** No assessor call, retry, configuration switch, trace event, or ToolGateway behavior was merged into serving.
- **Tests run/passed:** The diagnostic unit tests pass. The restored Agent V2, runtime, and security suites are re-run as the final verification gate.
- **Known limit:** The diagnostic uses a consumed cohort and local-model output is not sufficiently stable for a GO decision.
- **Next Gate:** Freeze assessor outputs or use a deterministic alternate-query policy before reconsidering implementation.
