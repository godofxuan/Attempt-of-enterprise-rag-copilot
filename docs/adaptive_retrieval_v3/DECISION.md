# Adaptive Retrieval V3 Decision

## Current State

`NO_RUNTIME_CHANGE`

The V2 default remains unchanged. S4 remains historical `EXPERIMENTAL_KEEP`
evidence under its own bake-off status, while S5 remains historically rejected.
V3 will use its separate maturity labels only after the corresponding gates.

## G1/G2 Outcome

Both available V3 adaptive mechanisms are `REJECTED`: G1's separated LLM
assessor is stable but over-triggers (72.38% false-retry rate), while G2's
Oracle-triggered historical two-query corrective retrieval does not improve the
fixed Top-5 retrieval result. Default routing, ACL, Guard, evidence ledger,
grounding, and response behavior remain unchanged.
