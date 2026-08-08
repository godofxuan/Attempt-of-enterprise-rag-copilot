# RAG Failure Analysis

## Scope

This analysis uses the 49-case FinanceBench development split and the dense
retrieval arm at Git SHA
`19be1ba9e1b07efb98a1af4d3e722c4d8e8e4495`. It is diagnostic evidence, not a
final test result.

## Typed failures

Dense retrieval missed at least one gold page in 31/49 cases:

| Primary class | Count | Meaning |
|---|---:|---|
| Page-ranking miss | 20 | The company/document was available, but the correct page was outside top 5. |
| Partial multi-page recall | 4 | Some, but not all, required pages were retrieved. |
| Document-ranking miss | 4 | The correct document existed in candidates but ranked outside the usable document window. |
| Document miss@5 | 3 | The correct document did not enter the first five documents. |

Twenty-six failures involved numeric or table-style questions and eleven
required multiple pages. These tags describe the question/evidence shape; they
do **not** prove that table extraction caused the failure.

## Parser decision

Only 1/31 failures had a deterministic parser-risk signal. No gold page was
missing from the chunk index, no case met the low-extraction-recall condition,
and no table-extraction-risk case was deterministically identified. The frozen
20% trigger for a parser ablation was not met, so Docling/MinerU was not added.

This is an important engineering result: adding a layout parser would increase
complexity without evidence that parsing is the dominant bottleneck. The current
bottleneck is page ranking and multi-page localization.

## Adaptive retrieval diagnostic

Development case comparison showed that BM25 and RRF each rescued one dense
miss while regressing many dense successes. The cross-encoder path rescued four
dense misses but regressed three successes; a perfect hindsight selector would
reach 26/49 Page Hit@5 (53.06%), versus dense 22/49 (44.90%). No reliable online
selector was demonstrated, so automatic rewrite/retry remains disabled.

The 53.06% value is an oracle upper bound computed after seeing labels. It is
not a model result and is forbidden in a resume claim.

## Root cause conclusion

1. Retrieval quality is benchmark-specific: lexical fusion harmed this
   FinanceBench split despite being useful in the enterprise corpus.
2. Candidate recall alone is not enough; ordering exact pages is the dominant
   issue.
3. The tested generic MS MARCO cross-encoder does not understand the financial
   page-ranking objective well enough to justify its CPU cost.
4. The answer model also limits end-to-end quality: FinQA oracle evidence reaches
   only 52% strict accuracy, so retrieval alone cannot close the gap.

Evidence:
`evidence/financebench_failure_analysis_v1.json` and
`evidence/financebench_dev_ablation_v1.json`.

## UDA FinHybrid fixed-test diagnosis

The separately frozen UDA experiment evaluates page localization within a known
financial report. Dense hit the gold page in the first five results for 71/96
cases (`73.96%`), leaving 25 misses. All returned hits had valid page locators,
so locator loss is not the explanation.

Of the 25 misses, the nearest retrieved page was adjacent to gold in seven
cases, two to three pages away in one, four to ten pages away in seven, and more
than ten pages away in ten. This supports two failure modes: page/table boundary
localization for the nearby misses, and semantic page ranking for the distant
misses. One report, EOG 2017, contributed five misses; no parser replacement was
selected from this test because the test is now consumed and cannot become a
development set.

Rank distribution was 45 at rank 1, 10 at rank 2, 10 at rank 3, five at rank 4,
one at rank 5, and 25 misses. The content-free evidence is
`../external_datasets/evidence/uda_finance_test_v1.json`.
