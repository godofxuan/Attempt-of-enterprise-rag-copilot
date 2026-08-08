# Enterprise Evaluation Negative Results

## Equal-weight RRF is rejected on WixQA E1

The project began with a legitimate hypothesis: BM25 may add lexical support to
BGE-M3 Dense, and reciprocal-rank fusion may combine complementary evidence.
The paired result did not support adopting equal RRF.

On all 6,221 Synthetic development questions, Dense Recall@5 was 97.88% and RRF
was 94.41%. Pairwise analysis found 831 Dense-only successes versus 66 BM25-only
successes. RRF rescued 67 Dense misses but regressed 283 Dense successes.

On the 200 fixed external ExpertWritten questions, Dense versus RRF was:

- Recall@5: 66.42% versus 59.25%;
- nDCG@5: 52.16% versus 47.16%;
- multi-article completeness@5: 30.77% versus 19.23%;
- p95 latency: 157.4 ms versus 304.6 ms.

Decision: `EQUAL_RRF_REJECTED`. BM25 and fusion code remain available for
benchmarking, but Dense is the E1 champion. This is dataset-specific and does not
erase prior synthetic-corpus evidence where lexical retrieval was useful.

## Dense-dominant fusion exploration is not an external result

A development-only offline analysis of stored Synthetic Top-5 rankings found:

- increasing Dense RRF weight preserved Dense Recall@5 but reduced MRR/nDCG;
- replacing Dense rank 5 with the first BM25 result not already in Dense top 4
  moved Recall@5 from 97.88% to 98.18%, with 35 gains and 16 regressions.

This is only a candidate-generation observation. It was not frozen before the
Simulated and ExpertWritten baseline aggregates were observed, so neither public
cohort may be called an independent candidate holdout. No improvement claim is
made from this exploration.

## Transient Ollama index-build incident

The first BGE-M3 build stopped after 5,738/11,975 chunks when Ollama returned one
HTTP 400 for batch 180. The exact 32-input batch was replayed unchanged and
returned HTTP 200; two 16-input halves also succeeded. This falsified a stable
length, content, and batch-size violation. The second build reused all 180
hash-bound shards and completed the remaining 196 batches.

No global HTTP-400 retry was added because 400 normally indicates a caller error
and retrying it indiscriminately would hide invalid requests. The incident is
recorded as a non-reproducible local service-state failure. Resumable shards
prevented lost computation.

## Long-run progress observation correction

During the first full Synthetic invocation, the orchestration layer buffered
child stdout. Lack of visible progress was initially mistaken for cold-start
work. Stage instrumentation later measured source verification at 0.12 seconds,
index loading at 1.14 seconds, BM25 construction at 0.48 seconds, and model probe
at 0.25 seconds. The run was stopped before artifact publication and produced no
partial result. The successful rerun took 1,297.4 seconds.

Decision: no index-load optimization was justified. Future monitoring must use
process/resource signals or direct terminal streaming rather than assuming a
buffered tool call is stalled.

## Full-corpus lexical retrieval is not sufficient

The full EnterpriseRAG-Bench FTS5 arm solved the previous in-memory capacity
failure but did not solve enterprise retrieval. Overall Recall@5 was 60.37% and
multi-document completeness@5 was 28.26%. Semantic Recall@5 was only 36.00%, and
completeness questions retrieved every required source in only 5.00% of cases.

Mean query latency was 1,101.3 ms and p95 was 1,821.0 ms; constrained questions
reached 2,662.3 ms p95. The frozen OR query compiler computes BM25 over broad
posting unions and is not an acceptable interactive endpoint as-is.

Decision: `BM25_FTS5_BASELINE_ONLY`. Keep it as the reproducible lexical B0 and
as evidence that disk-backed indexing controls memory. Do not present its 60.37%
Recall@5 as a final system accuracy or claim it proves Agent, answer, citation,
or refusal quality. The next candidate must target semantic and multi-document
failures while reporting latency cost.

## Current bounded Agent does not improve WixQA retrieval

The production V2 Runner/Registry/Guard path was evaluated as the missing B3 arm
on both fixed 200-question WixQA cohorts. It preserved the same B2 RRF ranking,
but every case made exactly one search and no case called `find` or `open`.
Therefore Agent searched-evidence recall was identical to B2: 52.92% on
Simulated and 59.25% on ExpertWritten.

The extractive response selected one source for the single rule-derived required
aspect. Citation recall fell to 23.25% and 30.92%, and multi-article citation
completeness was 0% on both cohorts. p95 latency rose from 299.3 to 476.7 ms on
Simulated and from 342.5 to 502.7 ms on ExpertWritten.

This was not a crash or Guard rejection: all 400 cases had no tool error. The
rule analyzer produced one required aspect, and the controller's open branch is
limited to explicit `completeness` intent. Real support wording did not trigger
that route. Decision: `AGENTIC_ROUTE_REJECTED`. The code remains an audited
bounded mechanism, but must not be presented as measured Agent quality gain.
