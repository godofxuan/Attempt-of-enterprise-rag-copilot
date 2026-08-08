# R3 Answer and Citation Evaluation

## Pre-run status

- Status: `NOT_RUN`
- Dataset: UDA Finance R3 company-disjoint cohort
- Retrieval: unchanged Dense chunk baseline, document-conditioned through the
  existing ACL boundary
- Answer model: `qwen3:8b`
- Answer model digest:
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`
- Frozen protocol SHA-256:
  `0eb83d435442fa8d43d275a54b165525a78ea594bb90a16ca9971e99c5921a60`

## Compared strategies

`direct` asks the guarded local model for one final answer, a calculation
description and evidence IDs. It is the unchanged generation baseline.

`typed_candidate` extracts at most 32 numeric candidates from admitted evidence.
The model can select candidate IDs and one of seven operations, but it cannot
submit raw numeric literals. The host validates candidate membership, operation
arity and citation coverage, then executes the calculation with `Decimal`.

This separates two responsibilities:

1. the model decides which evidence values and operation express the question;
2. deterministic code performs the arithmetic and records the exact operands.

The retrieved text is still untrusted. Every evidence unit passes through the
existing retrieved-content Guard before either strategy sees it.

Generation is bounded to 256 output tokens for `direct` and 128 for
`typed_candidate`. This prevents a malformed or unexpectedly verbose local
generation from turning one case into an unbounded latency outlier.

The local `qwen3:8b` process is unloaded after every six completed cases. The
next answer reloads the exact frozen digest, and that load time remains inside
the next case's measured generation latency. The campaign manifest records both
the configured interval and actual reset count.

## Metrics

- Numeric accuracy uses UDA's symmetric relative error below 1 percent.
- Evidence Page Hit@5 asks whether retrieval included the gold page.
- Citation precision and recall compare cited pages with the gold page.
- Grounded numeric accuracy requires both a correct answer and a gold-page
  citation.
- Unsupported-answer rate counts emitted answers without a gold-page citation.
- Generation and calculator calls plus mean and p95 latency record cost.

## Frozen decision rule

The development split selects a candidate only when it improves numeric
accuracy over `direct`; grounded accuracy and p95 latency are tie-breakers. A
selected candidate then needs at least `+0.05` validation numeric accuracy,
non-decreasing grounded accuracy, non-increasing unsupported-answer rate and no
more than `2x` p95 latency. The fixed test remains untouched unless all
validation gates pass.

Validation and test execution markers are created with exclusive file creation.
Re-running either split against the same private evidence root fails closed.

## Pre-run execution incident

The first two development launches produced no campaign artifact. Single-case
diagnostics showed roughly 0.34 seconds for retrieval and 1.5 seconds for each
answer strategy, but the long process later had no network activity or CPU
growth. The host command wrapper buffered child stderr instead of draining it;
per-case progress output filled the Windows pipe and blocked Python in `print`.
The abandoned process trees were stopped by their exact PIDs. A second launch
showed that this host can block on the first native stderr line, so the CLI now
also provides `--quiet` to suppress progress output completely. Normal terminal
runs remain bounded to one line per 16 cases. No model, retrieval, metric or
promotion parameter changed, and validation/test markers were never created.

A later all-thread stack dump found an additional issue inside an active
`/api/chat` response read: the shared Ollama client had a request timeout but no
generation-token ceiling. Some financial prompts could therefore occupy the
whole timeout and transport retry budget. The frozen protocol now binds the
strategy-specific output budgets above. This changes the service cost boundary,
not labels, retrieval evidence or score thresholds.

Ollama's server log then exposed the underlying long-run resource condition:
25 distinct prompt-cache entries occupied about 8.1 of an 8.2 GiB cache budget.
The next request stalled while updating that cache. The six-case reset policy
keeps the long campaign below this observed saturation point even when both
answer strategies need their permitted repair attempt.
