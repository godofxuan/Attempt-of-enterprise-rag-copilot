# R3 Expanded External Security Evaluation

## Purpose

R3-S5 tests the current retrieved-content Guard on a larger deterministic
external-content population without changing Guard rules. It is a stress
reproduction, not another development round and not a new blind holdout.

The fixture crosses 12 already frozen NVIDIA garak instruction/payload/trigger
tuples with four official `LatentInjectionReport` contexts. This yields 48
attacks and four marker-removed benign controls. Guard OFF and ON use the same
case, local Qwen3-8B digest, temperature, prompt and counterbalanced arm order.
Only retrieved-content admission changes.

## Result

| Metric | Guard OFF | Guard ON |
| --- | ---: | ---: |
| Attack success | 12/48 (25.0%) | 0/48 (0.0%) |
| Attack context reached model | 48/48 | 0/48 |
| Benign quarantine | 0/4 | 0/4 |
| Benign task utility | 4/4 | 4/4 |
| p95 end-to-end case latency | 4.28 s | 1.68 s |
| Mean deterministic Guard scan | 0 ms | 1.88 ms |

The latency arms are not a pure overhead comparison. Guard ON intentionally
stops quarantined attacks before generation, so it makes only four model calls
while Guard OFF makes 52. The meaningful direct Guard cost is the 1.88 ms mean
scan, while the total latency difference demonstrates avoided unsafe model work.

## Runtime boundary

The run started from a cold chat-model cache, capped output at 256 tokens and
reset the exact model after every 12 generated responses. It observed 56 model
calls, five resets, 62 allowed local HTTP/socket connections and zero blocked
egress attempts. The accounting identity is:

`56 model calls + 5 resets + 1 model identity request = 62 local requests`.

## Claim boundary

The stronger resume claim remains the 12-attack combination-disjoint holdout
that was frozen before the Guard fix. This expanded set includes previously
observed combinations and therefore supports current implementation stress
coverage, not independent generalization. Neither result establishes full
garak, arbitrary jailbreak, data-exfiltration or tool-misuse security.
