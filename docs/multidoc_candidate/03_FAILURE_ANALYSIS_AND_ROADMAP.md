# Failure Analysis and Long-term Roadmap

## Where the combined candidate failed

The deterministic failure artifact recomputes:

| Observation | Cases / count |
| --- | ---: |
| Questions that produced multiple query variants | 8/20 |
| Combined Top-5 order changed | 7/20 |
| Retrieval recall improved / regressed | 0 / 0 |
| Combined acquisition still incomplete | 17/20 |
| All gold admitted | 3/20 |
| Admission loss after complete retrieval | 0/20 |
| Selection incomplete after complete admission | 3/20 |
| Citation recall improved / regressed | 1 / 0 |
| Multi-source responses | 6/20 |
| Cited gold / non-gold documents | 10 / 18 |
| Cases with a quarantined candidate | 1/20 |

The one quarantine did not turn a complete retrieved set into an incomplete
admitted set. Guard is therefore not the cause of the zero completeness result.

## Why extra queries did not improve retrieval

The policy recognizes only explicit separators. It triggered on eight cases,
but the clause queries were still lexical fragments of the same user question.
RRF changed order in seven cases without changing how many gold documents were
inside Top-5. Reordering is not the same as recall improvement.

The experiment cannot now add separators, increase variant count, or use gold
titles to create better queries. Doing so after reading the result would be
test-set tuning forbidden by the protocol.

## Why selective evidence still cited noise

Selection used only admitted Top-5 evidence, which preserved Guard and ACL, but
"highest ranked for a clause" is not equivalent to "required supporting
document." Six cases cited multiple sources, yet the combined arm cited 18
non-gold documents and only 10 gold documents in total. In the three cases where
all gold was admitted, the selector still chose only one gold plus either noise
or no second source.

This is the same engineering lesson as the older cite-all candidate, but less
severe: limiting source count controls the precision collapse; it does not make
the ranking signal semantically sufficient.

## Current bottleneck

The ordered bottleneck remains mixed:

1. **Acquisition:** 17/20 cases lack at least one required document in Top-5.
2. **Evidence-role representation:** the Agent models one required aspect, not
   two or three independently required document roles.
3. **Selection:** even when all gold is admitted, clause rank alone cannot tell
   which distinct documents jointly answer the question.

No generation-model problem was measured because no generation model ran.

## Long-term roadmap after NO-GO

### L1 closeout: complete now

- Permanently reject this exact separator/RRF/selector configuration.
- Keep production defaults unchanged.
- Do not run fixed validation or present quality uplift.

### L2 data contract: next eligible work

Create a new multi-document protocol with development, validation, and sealed
test roles before another quality candidate. Each case needs document-level
support plus evidence-role annotations such as prerequisite, exception,
comparison side, or procedure step. The current one-aspect gold mapping is not
enough to train or evaluate a coverage-aware selector.

Entry requires a documented source/license and no overlap with the consumed 20.
Exit requires hash-bound split identities and a reviewer-visible consumption
ledger. No model implementation should precede this data contract.

### L3 candidate-pool rescue study

The old attribution showed all-gold completeness of 3/20 at Top-5 and 13/20 at
Top-20. On new development data, test one bounded Top-20-to-Top-5 coverage-aware
selector before adding a larger stack. It must use runtime-available features
only and compare against the current Dense champion as well as hybrid RRF.

Minimum metrics: all-gold complete@5, macro document recall@5, nDCG@5,
citation precision/recall/completeness, reranker calls, memory, and p95 latency.

### L4 acquisition rescue study

Only if Top-20 analysis still shows a material acquisition-miss subset, compare
one bounded rewrite/decomposition policy with OFF. Maximum one retry, fixed
query count, and fixed model/prompt if an LLM is used. Measure tool steps,
embedding/model calls, tokens, and latency. Do not enable it by default without
an independently validated monotonic gain.

### L5 independent validation and shadow

Freeze exactly one candidate and run validation once. A pass permits only a
default-off typed policy. Then use shadow execution to measure errors, latency,
and drift without changing user answers. Human citation review follows before
any release decision.

## Stop conditions

Stop quality feature development when any is true:

- no fresh, correctly licensed multi-document cohort exists;
- the candidate improves recall but breaches precision or latency gates;
- fewer than three paired complete-case fixes occur;
- the mechanism requires gold/test-only features;
- Guard, ACL, trace, rollback, or evidence verification would be weakened.

Under the current repository state, the first condition applies. The useful
next activity is data/evaluation design and interview preparation, not another
unmeasured Agent feature.
