# Bounded Multi-document Candidate Implementation

## Scope

This stage implements one evaluation-only four-arm experiment. It does not add
a framework, model, vector database, Agent, or production route. It changes no
default serving behavior.

Execution identity:

- candidate base: `ece1de15438d9a6d403390a11cdb55fd8957debe`;
- implementation SHA: `d29639c8b3f037560385d5c7ad1b847dae4fc4ab`;
- run: `wixqa-multidoc-candidate-v1-d29639c`;
- cohort: 20 already-consumed WixQA ExpertWritten multi-document cases;
- generation model: not used;
- embedding: index-bound local BGE-M3;
- production change: false.

## File map

| File | Responsibility |
| --- | --- |
| `docs/multidoc_candidate/00_LONG_TERM_PLAN_AND_PROTOCOL.md` | pre-run hypothesis, arms, gates, and stop rules |
| `app/evaluation/wixqa_multidoc_candidate.py` | deterministic decomposition, multi-ranking RRF, admitted-only selection, metrics, gate, failure analysis |
| `scripts/eval_wixqa_multidoc_candidate.py` | source/index/model binding and one four-arm execution |
| `scripts/verify_wixqa_multidoc_candidate.py` | public privacy, schema, hash, metric, pairing, and decision verification |
| `tests/evaluation/test_wixqa_multidoc_candidate.py` | mechanism and default-behavior isolation tests |
| `tests/evaluation/test_wixqa_multidoc_candidate_evidence.py` | checked-in evidence and tamper tests |
| `docs/multidoc_candidate/evidence/` | canonical public protocol, rows, aggregate, and derived failure analysis |

## Four-arm factorization

The experiment separates two possible causes instead of changing both and then
guessing which one mattered.

| Arm | Candidate acquisition | Response selection |
| --- | --- | --- |
| A `current` | original query | first admitted evidence |
| B `decompose_only` | original plus up to two clauses, fused by RRF | first admitted evidence |
| C `select_only` | original-query Top-5 | one preferred admitted document per query variant |
| D `combined` | decomposed acquisition | selective admitted evidence |

This is a 2x2 causal design. `B-A` estimates acquisition effects, `C-A`
estimates selection effects, and `D-A` tests the proposed combined mechanism.

## Query decomposition

`decompose_query()` normalizes whitespace, always keeps the original question,
and splits only on the frozen separators `and`, `or`, `versus`, `vs`, comma,
and semicolon. A clause needs at least three alphanumeric tokens. Fewer than two
valid clauses disables decomposition. The output is capped at three queries.

The function cannot read gold documents, answers, article titles, or retrieved
text. It is deterministic and deliberately limited; it is not semantic planning.

## Candidate acquisition

Each query variant independently uses the existing index-bound path:

```text
BM25 top-200 + BGE-M3 dense top-200 -> existing two-way RRF
```

`fuse_query_rankings()` then applies deterministic RRF across all variant
rankings. Duplicate IDs in one source ranking contribute once. Ties use score,
best rank, complete rank vector, and document ID in that order.

The Agent still sees one typed `search` call. Extra internal embeddings are
recorded separately, so the candidate cannot appear cheaper because rankings
were precomputed and shared across arms.

## Admitted-only response selection

`SelectiveExtractiveResponseBuilder` receives variant rankings, but it does not
receive raw documents. At build time it first enumerates only
`ControllerState.evidence_by_aspect`, which contains evidence already admitted
through the normal tool and retrieved-content boundary. For each variant it
selects the highest-ranked surviving document, deduplicates, and caps the set at
three. It then delegates claim construction and citation verification to the
existing `ExtractiveResponseBuilder`.

The final assertion checks that every output source is a member of the selected
admitted set. The candidate cannot reintroduce a denied or quarantined document.

## Cost accounting

All variants are ranked once per case. Reported arm latency is:

```text
required query-ranking compute + arm-specific Agent mechanism time
```

Arm A pays for one embedding. Arms B/C/D pay for every query variant they need.
This avoids the common benchmark error where a cache makes later arms look free.
The experiment remains a single-machine observation, not a production SLO.

## Production isolation

The runner compares the candidate implementation range against eight protected
production paths. The published protocol records an empty changed-path list.
The normal `V2AgentRunner` default remains one evidence item per aspect, and a
regression test proves that importing the candidate module does not change it.

Protected behavior includes query analysis, Controller, Evidence Ledger,
runner, tools, retrieved-content Guard/admission, and the normal retriever.

## Problems encountered

1. An exploratory read assumed a nonexistent `app/retrieval/fusion.py`. Symbol
   search located RRF in `app/external_datasets/wixqa_retrieval.py`; no code was
   changed based on the bad path assumption.
2. One RRF unit test expected the wrong order for equal-score documents. The
   implementation's frozen rank-vector tie break was correct; the test expected
   value was repaired.
3. The first CLI launch used a one-second tool timeout and was killed before a
   run directory existed. Process and output checks proved there was no partial
   run; the same committed SHA and run ID then completed with adequate timeout.
4. The first verifier required insertion order for JSON object keys, but
   canonical JSON sorts keys. The verifier now checks the exact arm set, while
   canonical byte equality owns ordering.

These are recorded because operational and evaluator errors must be separated
from model or retrieval failures.
