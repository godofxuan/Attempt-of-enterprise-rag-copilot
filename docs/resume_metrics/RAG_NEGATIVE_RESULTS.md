# RAG Negative Results

## BM25 and RRF were worse than dense retrieval

On FinanceBench development, Dense Page nDCG@5 was 0.3525. BM25 scored 0.1103
and BM25 + Dense + RRF scored 0.1839. RRF also increased p95 latency from
533.30 ms to 1006.26 ms. Therefore hybrid RRF was not selected for a final
test run.

## Generic cross-encoder was not Pareto-efficient

RRF + `cross-encoder/ms-marco-MiniLM-L6-v2` top-10 increased Page Hit@5 by one
case versus dense (22/49 to 23/49), but Page nDCG@5 fell from 0.3525 to 0.3472
and p95 latency rose from 533.30 ms to 2466.12 ms. Top-20 produced no additional
top-5 hit, reduced nDCG further to 0.3292, and reached 2474.72 ms p95. The
optional implementation remains available for research, but is not enabled or
described as an improvement.

## Layout parser replacement was not justified

Only one of 31 dense failures had a deterministic parser-risk signal. The
pre-registered threshold was 20%, so no Docling/MinerU integration or paired
parser ablation was run. Numeric/table questions were common, but question type
is not proof of extraction failure.

## Adaptive retrieval was not enabled

No tested branch was a monotonic rescue policy. A hindsight union could rescue
four cases, but an online selector was not established and some paths regressed
already-correct cases. Query rewrite/retry/find/open remains bounded and off by
default rather than adding cost without causal evidence.

## FinanceBench has no final improvement number

The 101-case fixed test has historical exposure. Development results were not
promoted to it because no intervention met the quality/latency decision rule.
This prevents repeated test-set tuning but means there is no honest
`FinanceBench baseline -> final` resume bullet from this round.

## End-to-end metric gaps remain

The existing FinQA artifact reports deterministic strict answer accuracy,
grounded accuracy, evidence recall, citation precision, and citation recall.
It does not report claim-level citation coverage, unsupported-claim rate,
refusal precision, or refusal recall. Those metrics must remain `NOT MEASURED`;
they cannot be inferred from citation recall or from heuristic safety labels.

## Security limitation

The external garak result covers one small retrieved-report probe. It does not
establish full AgentDojo, promptfoo, garak, arbitrary jailbreak, data-exfiltration,
or tool-misuse performance. The holdout has only two benign controls, so `0/2`
must not be generalized as a precise 0% benign false-positive rate.

## Historical FinQA protocol drift is intentional

The frozen FinQA holdout and E18 admitted-context protocols bind the pre-v1.2
Guard source hash. The current Guard changed after the garak development run,
so those historical protocols now correctly reject the current source tree.
Their published aggregates remain evidence for their original exact revisions;
reproduction requires checking out that revision. The old protocol/evidence
JSON was not rewritten to make the new tree appear source-identical.

## UDA fixed test is a baseline, not an improvement

UDA development Dense Hit@5 was 84.38%, while the company-disjoint 96-case
fixed test reached 73.96%. This 10.42 percentage-point drop is a generalization
warning, not a regression against a production baseline. No post-test parser,
chunker, fusion, or reranker change was evaluated on an unused population, so
the UDA result must not be written as `baseline -> improved`.

## R3 page continuity failed validation promotion

On 192 newly selected UDA development questions, page-level deduplication moved
Hit@5 from 79.17% to 81.77% and nDCG@5 from 63.05% to 64.59%. The independently
selected 96-question company-disjoint validation result was only 81.25% to
82.29% Hit@5 and 67.58% to 68.46% nDCG@5. The `+1.04` and `+0.88` point quality
deltas failed the preregistered `+5` and `+3` point gates. The fixed test was
not run, and page max was not promoted.

The fixed neighbor policy produced no development Top-5 change relative to page
max. The fixed structure score reduced Hit@1 and nDCG. Neither was retuned after
observing development labels.

The test is conditioned on a known report. It cannot support document-discovery
or answer-accuracy claims, and its public labels make it fixed external evidence
rather than a hidden blind holdout.
