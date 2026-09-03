# Adaptive Retrieval V3 Adaptive Policy Results

## G3-G5 Decision: `REJECTED`

G3 is intentionally not executed: its precondition is a useful G2 corrective
candidate. G2 rejected the only available two-query candidate on the Oracle
slice, so changing validation rules or fusion weights now would be unbounded
tuning on consumed labels.

G4 conditional composition is also not executed. A conditional policy can only
improve on its components if at least one corrective arm can recover evidence;
G1 rejects the trigger's operating point and G2 rejects the corrective arm.
Composing two rejected components is not an additional experiment.

G5 deterministic routing versus LLM routing is not executed for the same
reason. The existing deterministic baseline remains ordinary hybrid RRF Top-5;
there is no qualifying retry action for either router to invoke.

This is a `REJECTED` adaptive-policy decision, not a claim that bounded
retrieval policies can never work. It means this repository has no evidence to
enable one on the current consumed cohort, model, index, and latency profile.
The V2 runtime remains unchanged.
