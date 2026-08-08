# R3 Engineering Journal

## Objective

R3 was started to improve external credibility and obtain defensible evidence,
not to accumulate frameworks or Agent components. The accepted R2 system was
kept intact unless a preregistered same-population experiment justified a
replacement.

## S0: freeze the accepted baseline

The accepted revision `169e84e` and all consumed evaluation populations were
recorded first. This matters because a result cannot be called independent if
the same labels were previously used to choose prompts, thresholds or code.
The baseline also froze three existing resume-safe results: UDA page retrieval,
FinQA end-to-end execution/citations and a small garak holdout.

Result: baseline frozen at commit `0c62dbe`; old test sets are diagnosis-only.

## S1: construct an unused-company cohort

The UDA source contained 788 documents and 8,190 question rows. Companies used
by earlier experiments were excluded before selection. The remaining population
was deterministically divided into 24 development companies/192 questions,
12 validation companies/96 questions, 12 fixed-test companies/96 questions and
28 reserve companies. The selected 48 reports produced 17,891 BGE-M3 chunks.

Why company-disjoint: questions from one annual report share terminology,
tables and formatting. A row-random split would leak report style between
development and evaluation.

Result: cohort and index contracts frozen in commits `0c62dbe` and `69d37b9`.
Validation/test access is one-shot and fail-closed.

## S2: bounded page-continuity retrieval

Failure analysis suggested that multiple highly similar chunks from one page
could consume Top-K slots. A minimal page-max candidate retained only the best
chunk score per page. It changed ranking aggregation only; embeddings, query,
known-report boundary, ACL and Guard behavior stayed fixed.

Development selected page-max for validation. On 96 validation questions:

- Page Hit@5 changed `81.25% -> 82.29%`;
- nDCG@5 changed `67.58% -> 68.46%`;
- p95 changed `281.16 -> 276.87 ms`.

The gains failed the frozen `+5pp` Hit@5 and `+3pp` nDCG gates. Lowering a gate
after observing the result would be outcome-driven tuning, so page-max was
rejected and the fixed test remained unopened.

Result: candidate developed at `95d4163`, selected at `9c45fbf`, rejected at
`34127a6`.

## S3: end-to-end numeric answer and citation evaluation

A deterministic scorer compared normalized numeric answers, gold-page
grounding, citation precision/recall, unsupported answers and refusal/protocol
behavior. The candidate used a typed numeric contract and deterministic
calculator so schema compliance could be separated from answer correctness.

The first long runs appeared to hang. Stack traces showed the client waiting in
Ollama `/api/chat`, and the Ollama log showed 25 prompt-cache entries occupying
about 8.1 of 8.2 GiB. The runner was hardened with progress output, quiet mode,
per-arm output-token limits and an unload/reload reset every six evaluated
cases. This fixed campaign liveness without changing scoring.

On 192 development questions:

- direct numeric accuracy was `15/192 = 7.81%`;
- typed numeric accuracy was `3/192 = 1.56%`;
- direct/typed grounded accuracy was `7.29% / 1.04%`;
- unsupported-answer rate was `31.25% / 58.85%`;
- p95 was `8.56 / 3.75 s`.

The typed route was faster and always produced valid structure, but it selected
the wrong financial values. A deterministic oracle then showed why: the first
32 extracted candidates contained a gold-equivalent number in only 7/192 cases,
and 190/192 pages reached the 32-value cap. Position-ordered regex extraction
does not preserve table row/column, unit, period or semantic role.

Result: runtime hardening landed in `5dd16ba` through `bfeceff`; oracle analysis
landed in `5a0b8c7`; candidate rejection landed in `a45d5cd`. No validation or
test answer labels were opened.

## S4: independent human review

The existing campaign packet and verifier remain available, but the status is
`NOT_RUN`: two slots must be completed by two genuinely independent humans.
Using this same coding agent, another model invocation or duplicated identities
would invalidate the agreement measurement.

Result: intentionally outstanding; this is the only R3 activity that cannot be
completed autonomously.

## S5: expand retrieved-content injection stress

The existing combination-disjoint 12-attack holdout was too small for broad
claims. A larger 48-attack plus four-benign fixture was deterministically
recombined from pinned external garak material. The runner froze arm order,
model digest and local-only egress, added bounded output/cache resets and
recorded model calls and Guard latency.

Observed current-Guard stress result:

- ASR `12/48 -> 0/48`;
- context exposure `48/48 -> 0/48`;
- benign quarantine `0/4`, benign utility `4/4`;
- mean deterministic Guard scan `1.88 ms`;
- blocked non-local egress `0`, because all 62 allowed requests were local.

This is useful regression stress, but it is not a new blind holdout because its
components were recombined from already available fixtures. The 12-attack
combination-disjoint result remains the stronger resume claim.

Result: fixture/build/run/evidence commits `15ee888`, `e22bd7d`, `837616f`,
`296367a`.

## S6: reproducible closeout

A model-free evidence tour was added so a reviewer can inspect the main
decisions without downloading models or private datasets. Resume metrics now
include the negative R3 trials and strict claim boundaries. The final report
explicitly recommends stopping feature addition.

Result: evidence tour `c771c24`; final reports and registry are part of the R3
closeout commit. The only scientifically valid next quality experiment is a
table/layout-aware evidence representation designed on development data and
evaluated once on reserved companies.

## What an interview candidate should learn

1. Evaluation splits are part of system design, not a final testing detail.
2. A successful implementation can produce a rejected experiment; preserving
   the stronger baseline is good engineering.
3. Schema validity and latency do not imply semantic correctness.
4. Retrieval success and answer success diagnose different layers.
5. External benchmark names do not remove the need to state probe, split,
   sample size and independence limitations.
6. Operational faults such as model-cache saturation must be recorded because
   they affect reproducibility even when metric formulas are correct.
