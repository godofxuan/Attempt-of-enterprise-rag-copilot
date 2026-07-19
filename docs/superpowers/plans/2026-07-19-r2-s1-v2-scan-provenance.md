# R2-S1 V2 Guard Scan Provenance Implementation Plan

Date: 2026-07-19

Status: approved for implementation; V3-V5 remain out of scope.

## Goal

Replace the live evaluator's category-based inference of Guard reach with an
immutable, content-free record of the scan operations that actually happened in
`RetrievedContentAdmission`.

The evaluator must derive reached attack units only from those scan records. A
case being labelled `split_payload` must never by itself make a fragment count as
reached.

## Frozen boundaries

- Do not modify `RetrievedContentGuard` rules, keywords, thresholds, scan budgets,
  or detector version.
- Do not modify the frozen security dataset, fixture manifest, freeze manifest,
  formal D7 run, or V1 public evidence package.
- Do not change candidate ordering, split-window eligibility, top-k behavior, or
  OFF/ON arm inputs.
- Do not persist retrieved text, prompts, canaries, source paths, local paths, or
  model output in scan provenance.
- Do not begin V3 socket-boundary, V4 metric-semantic, or V5 arm-order work.
- Do not commit, push, merge, or tag without separate approval.

## Design

Add a strict frozen `ScannedContentUnit` domain contract. Each record describes
one actual call to the retrieved-content Guard with:

- operation: `search`, `find`, or `open`;
- surface: `matched`, `parent`, `find_preview`, `open`, `metadata`, or
  `aggregate`;
- internal item key and exact member IDs, excluded from serialization;
- whether the scan was an aggregate window;
- the actual Guard disposition and rule IDs.

`GuardedAdmissionOutcome.scan_provenance` will carry the records in scan order.
The outcome validator will require one provenance record per counted scan, so a
future caller cannot silently update counters without recording provenance.

Only eligible split windows produce aggregate scan events. Therefore adjacent
short fragments are represented, while oversized, non-adjacent, and
cross-document combinations are absent without requiring evaluator-side logic.

The live evaluator will map the internal IDs in those events back to the frozen
fixture's unit bindings. It will not inspect case category, admitted output, or
quarantine summaries to decide reach.

## TDD sequence

1. Add domain/admission tests for immutable content-free provenance and the
   search, parent, metadata, find, open, and aggregate surfaces.
2. Add tests proving eligible adjacent windows are recorded and oversized,
   non-adjacent, and cross-document windows are not recorded as aggregates.
3. Add evaluator tests proving category alone cannot create reach and exact
   member IDs from provenance do create reach.
4. Run focused tests and retain their expected failures as RED evidence.
5. Implement the smallest domain and admission changes needed to turn the tests
   GREEN without touching Guard detection code or eligibility limits.
6. Replace `_reached_attack_unit_ids()` inference with provenance-only mapping.
7. Verify the frozen test fixture still yields reached `15/28`, conditional
   quarantine `15/15`, and equal OFF/ON scan eligibility.
8. Run focused, security/agent/evaluation, and full repository test suites; then
   recheck frozen hashes, the V1 standalone verifier, public-repository audit,
   compile checks, and Git diff/status.

## Acceptance criteria

- Every counted Guard scan has exactly one content-free provenance record.
- Eligible adjacent split windows list their exact contributing chunk IDs.
- No ineligible aggregate window is reported as scanned.
- Parent, metadata, find preview, open content, and open metadata reach come from
  actual scan records.
- The evaluator contains no `split_payload` category reach special case.
- OFF and ON have identical scan eligibility for each frozen case.
- The historical D7/V1 package remains immutable at reached/unreached `15/28`
  and `13/28`.
- The hash-embedding test workload records its own evidence-based baseline
  (`17/28`, `11/28`) because its candidate order is not the formal BGE-M3 order;
  OFF and ON must still have identical per-case reach eligibility.
- Existing formal D7 artifacts and the V1 public evidence package remain
  byte-for-byte unchanged.
