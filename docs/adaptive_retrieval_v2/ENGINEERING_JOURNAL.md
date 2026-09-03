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
- **Known limit:** The diagnostic uses a consumed cohort and, at this point, the original local-model protocol did not establish a reproducible GO decision.
- **Next Gate:** Repair the assessor experiment before reconsidering implementation.

## Stage D: Assessor Reproducibility Repair

- **Files changed:** `app/ollama_chat.py`, `scripts/diagnose_adaptive_retrieval_recoverability.py`, `tests/test_ollama_chat.py`, and public evidence below. No V2 serving files changed.
- **Problem found:** The original diagnostic used `temperature=0`, but did not send an Ollama `seed`; its 12-second per-case timeout also mixed local-service latency into an assessor decision. The first two unseeded runs therefore differed: 3 then 2 fully recovered cases.
- **Change:** The diagnostic derives one stable integer seed from each question ID, sends it to the Ollama chat API, records the hash of every exact assessor input, and allows a 30-second diagnostic-only timeout. The shared chat wrapper accepts an optional seed; callers that do not pass one retain exactly the previous request payload and serving behavior.
- **Verification:** Two seeded reruns each assessed all 17 baseline failures. For every assessed case, the two runs had identical input hash, seed, raw JSON response, parsed proposal, and recovery outcome: `17 / 17` on every comparison. The detailed question text and raw outputs stay under `.private`; the public aggregate is `evidence/seeded_reproducibility_v1.json`.
- **Final result:** The stable result is only 2 fully recovered cases out of 17 baseline failures (`11.76%`). It satisfies the percentage condition but fails the predeclared absolute condition of at least 3. `ADAPTIVE_RETRIEVAL_NOT_YET_JUSTIFIED` remains the final decision.
- **Engineering conclusion:** The reproducibility defect is fixed. The product hypothesis is not validated: the dominant next bottleneck is initial candidate retrieval and Top-5 selection, not safe bounded LLM query rewriting.

## G0: Post-082b15b Reproducibility Closure

- **Hypothesis:** Same-environment, fixed-seed requests reproduce exactly.
- **Exact Git SHA:** `b159a98eae87ad204be8de064695cb9b1867830c`; both diagnostics recorded `git_dirty: false`.
- **Files changed:** Diagnostic provenance and a public-only repeat-comparison verifier. No serving files changed.
- **Dataset:** Consumed WixQA ExpertWritten 20-case multi-document cohort; 17 baseline failures evaluated by the assessor.
- **Arms:** Two identical local executions using `qwen3:8b` digest `a3de86...e686f`, Q4_K_M, Ollama 0.33.2, RTX 5060, fixed per-question seed, and identical request hashes.
- **Primary metric:** Exact equality of raw-output hash, parsed-proposal hash, and recovery classification.
- **Frozen success gate:** All 17 assessor-evaluated failures match across both executions.
- **Observed result:** Input request and seed each matched `17/17`; raw output matched `12/17`, parsed proposal `13/17`, and recovery classification `16/17`.
- **Decision:** `REPRODUCIBILITY_NOT_CLOSED_ADAPTIVE_EVALUATION_BLOCKED`.
- **Known limitation:** This establishes neither cross-hardware behavior nor a root cause inside the local inference backend. It does establish that the tested model/runtime combination cannot support an exact-repeat promotion gate.
- **Next action:** Run deterministic G1 failure attribution only. Do not conduct G2 adaptive-retry causality experiments or prompt tuning on the consumed cohort.

## G1: Current Failure Attribution

- **Hypothesis:** Earliest-loss attribution identifies the actual priority without introducing an LLM intervention.
- **Exact Git SHA:** `b3fd3dda997d8a1d3bc96926ffabce6d45d61533`; `git_dirty: false`.
- **Files changed:** Public evidence package only; serving is unchanged.
- **Dataset:** Consumed WixQA ExpertWritten 20-case multi-document cohort.
- **Arms:** Current BM25 + BGE-M3 dense + RRF Top-5 replay.
- **Primary metric:** Earliest loss category per case.
- **Frozen success gate:** 20 cases with zero unknown attribution rows.
- **Observed result:** `TOP5_SELECTION_MISS: 10`, `CANDIDATE_TOP20_MISS: 7`, `RESPONSE_SELECTION_LOSS: 3`, all other earliest-loss classes `0`. The replay also observed 17 ledger false-completeness signals, but each has an earlier retrieval loss.
- **Decision:** `ATTRIBUTION_COMPLETE_NO_OPTIMIZATION`; Top-5 selection is the next deterministic hypothesis, not an LLM rewrite.
- **Known limitation:** This is a consumed cohort and cannot select a production default.
- **Next action:** `GLOBAL_ADAPTIVE_STOPPED` because G0 blocks the required fair-budget G2 experiment. A future deterministic fixed-budget selector must use a separately frozen protocol.
