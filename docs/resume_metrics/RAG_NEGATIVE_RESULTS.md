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
