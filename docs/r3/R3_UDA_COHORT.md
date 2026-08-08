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
