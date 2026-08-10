# Next Candidate Decision

```text
STATUS: DO NOT IMPLEMENT IN THIS STAGE
DECISION: NEXT_BOTTLENECK_MIXED
COHORT: RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED
```

## Candidate 1: bounded acquisition comparison

Evidence: 7/20 first lose gold within Top-20 and 10/20 lose it between Top-20
and Top-5.

Minimal future experiment: compare a small pre-registered set of acquisition
policies on development data, such as current Top-5 versus one bounded
multi-query/decomposition policy. Hold embedding, Guard, Ledger, response
builder, and model constant.

Risk: higher latency and additional irrelevant evidence. A larger top-k alone
is not accepted as the answer; Top-20 completeness is only 13/20 and oracle
evidence proves downstream incompleteness remains.

Validation: all-gold@5/10/20, p50/p95 latency, search calls, Guard utility, and
new blind cohort after parameter freeze.

## Candidate 2: explicit multi-evidence contract

Evidence: all 20 cases have one required aspect; 17/20 show Ledger coverage
1.0 with incomplete gold sets; the three retrieval-complete normal cases and
all 20 Gold Retrieval Oracle cases still cite at most one document.

Minimal future experiment: represent a bounded required evidence cardinality
or distinct supporting-document requirement, then let response construction
select the minimum distinct admitted evidence needed to satisfy it.

Risk: over-citation, duplicated evidence, worse precision, and an invalid
assumption that every real question's gold cardinality is known. Do not encode
WixQA labels into serving behavior.

Validation: citation completeness, precision, unsupported-claim rate, context
size, latency, and no-change security/ACL tests on a new blind cohort.

## Candidate 3: two-factor sequential experiment

Evidence: Gold Retrieval Oracle proves that acquisition repair alone cannot
solve the response-selection limitation.

Minimal future experiment: first validate Candidate 1 and Candidate 2 as
separate ablations, then run a pre-registered combination only if each fixes
its intended stage without violating quality/latency gates.

Risk: interaction effects make attribution harder. The combined candidate must
not be the first experiment.

Validation: four arms (`current`, `acquisition only`, `contract only`,
`combined`) on development, followed by one frozen blind test for the selected
configuration. The current 20 cases cannot be reused as final validation.

