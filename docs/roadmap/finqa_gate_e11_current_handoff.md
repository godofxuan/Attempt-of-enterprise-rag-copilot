# FinQA Gate E11 Current Handoff

## Authoritative state

- Outer decision: `E11_OUTER_CV_AUTHORIZED_FOR_SINGLE_INTERNAL_VALIDATION`
- Internal decision: `E11_INTERNAL_GATE_PASSED_ELIGIBLE_FOR_NEXT_STAGE`
- Outer E8/E11 Descriptor Recall@4: `84.8894% / 86.0881%`
- Internal E8/E11 Descriptor Recall@4: `84.21% / 86.84%`
- Internal role transitions: `64 retained / 0 regressed / 2 gained / 10 missed`
- Internal complete cases: `28/37 -> 30/37`
- Internal evaluation ordinal/budget: `1/1`, consumed
- Frozen test: `UNTOUCHED`
- Serving champion: `finqa_deterministic_descriptor_retriever_v5`
- E11 serving: `DISABLED`

## Completed

1. Frozen 18-configuration Top-4 boundary weighted-ridge protocol.
2. Nested company CV with inner-only configuration choice and outer-only score.
3. Retrieval-realistic evidence, Guard, identity and bounded residual preserved.
4. Self-hashing final artifact `adj08-l2-100-p025`.
5. One-shot internal same-input E8/E11 comparison.
6. Shared typed-capability execution incident recorded and repaired before any
   internal result write.
7. Public aggregate CV/internal/postmortem evidence and SHA-chain tests.

## Claim boundary

The two internal gains and zero regressions pass the frozen non-regression gate,
but exact McNemar `p=0.5` is not significant. This is selector/candidate recall,
not answer accuracy. Three of 40 cases used the shared fallback. The artifact is
eligible only for shadow integration; it is not authorized for serving.

## Next stage

E12 should integrate the E11 selector behind an explicit shadow-only route,
compute E8 and E11 decisions on the same request without changing the answer,
emit bounded aggregate comparison telemetry, and prove fallback/circuit-breaker
behavior. It must not log values, raw questions, document text, candidate IDs or
private provenance. It must not access the frozen test.

Recommended model for E12 service boundary and telemetry schema:
**5.6 Sol / Extra High**.
