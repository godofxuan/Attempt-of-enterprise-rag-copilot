# G0-G3 Decision

## G0

`REPRODUCIBILITY_NOT_CLOSED_ADAPTIVE_EVALUATION_BLOCKED`

The fixed-seed local assessor did not meet the exact-repeat gate. Across 17
identical baseline-failure requests, request hash and seed matched for every
case, but raw output matched for 12, parsed proposal for 13, and recovery
classification for 16. See
[`reproducibility_closure_v2.json`](evidence/reproducibility_closure_v2.json).

## G1

`ATTRIBUTION_COMPLETE_NO_OPTIMIZATION`

The exact current replay has 10 Top-5 selection misses, 7 Top-20 candidate
misses, and 3 response-selection losses. Guard and permission filtering are
not observed first-loss causes. See
[`current_failure_attribution_v2.json`](evidence/current_failure_attribution_v2.json).

## G2 and G3

`GLOBAL_ADAPTIVE_STOPPED`

G2 requires frozen, reproducible adaptive proposals in order to distinguish a
rewrite benefit from additional retrieval budget. G0 failed that prerequisite.
Running or tuning the same 17 consumed failures would produce a misleading
causal comparison, so global LLM-driven query rewrite remains disabled and is
not promoted.

The next future experiment, if explicitly authorized, must be deterministic:
one fixed-budget Top-5 selection intervention against the unchanged baseline.
It must be separately pre-registered and cannot rely on the consumed G0 model
proposals.

## G4 Readiness Check

`KEEP_CURRENT_DEFAULT`

G1 makes deterministic Top-5 selection the next hypothesis. The repository
already contains earlier, consumed-cohort BGE raw-chunk reranker evidence: it
improved some Recall/nDCG/MRR measurements but reduced ExpertWritten
multi-document completeness, so it is only an experimental GPU quality mode.
The current project environment reports `torch 2.13.0+cpu` and no CUDA device;
the pinned BGE weights remain available, but the prior CUDA runtime is not a
reproducible project dependency. This program does not replace dependencies or
rerun a consumed cohort merely to obtain a new result. No G4 selector is
promoted.
