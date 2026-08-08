# R3 UDA Company-Disjoint Cohort

## Frozen before evaluation

The protocol at `docs/r3/evidence/uda_finance_r3_protocol_v1.json` was created
before any R3 retrieval or answer experiment. It binds the accepted baseline,
upstream revisions, QA file hash, selection seed, consumed-company exclusions,
case quotas, selection hash and reserve-company hash.

## Population accounting

- upstream FinHybrid: `788` reports / `8190` questions;
- documents with at least eight questions: `378`;
- eligible companies: `96`;
- consumed v1 companies excluded: `20`;
- unused eligible companies: `76`;
- R3 development: `24` companies / `192` questions;
- R3 validation: `12` companies / `96` questions;
- R3 fixed test: `12` companies / `96` questions;
- untouched reserve: `28` companies.

One deterministically selected report and eight deterministically selected
questions are used per company. Company, document and question identities are
disjoint across all three active splits. The reserve-company IDs are hash-bound
but are not extracted, indexed or inspected during R3.

## Access policy

- development labels may drive implementation and diagnosis;
- validation may execute once for model/strategy selection;
- fixed test may execute once after all candidate bytes are frozen;
- validation and test details remain private;
- only aggregate content-free metrics may be committed;
- test failures may define a future hypothesis but may not repair and re-score
  the same R3 candidate.

## Why this fixes the previous limitation

The first UDA result used 20 reports and produced a useful external baseline,
but its 96 test questions are consumed. R3 does not recycle them. It selects
entirely different companies and keeps 28 further companies untouched, allowing
the repository to make a legitimate same-population baseline/candidate
comparison and still retain data for a later round.

## S2 development selection

The four fixed page strategies were executed on all 192 development questions
at code revision `95d4163`. `dense_page_max` and `dense_page_neighbor` tied on
nDCG@5 (`64.59%`) and Hit@5 (`81.77%`), while page max had lower p95 latency.
It was therefore selected for paired validation. Against the unchanged Dense
chunk baseline, its development deltas were only `+2.60` Hit@5 points and
`+1.55` nDCG points, below the final promotion gates. Validation remains the
required confirmatory check; no success claim is made from development.

The fixed structure score was a negative result: it reduced Hit@1 from `44.27%`
to `39.58%` and nDCG@5 from `63.05%` to `62.20%`. It is rejected rather than
retuned after observing the development results.
