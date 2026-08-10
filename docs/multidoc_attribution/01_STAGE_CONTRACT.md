# Multi-document Stage Contract

## Coverage definition

For gold document set `G` and the document IDs retained at stage `k`, `S_k`:

```text
coverage_k = |G intersect S_k| / |G|
all_gold_recalled_k = G subset-of S_k
```

The first-loss stage is the first incomplete set in the declared causal
sequence. Once a stage loses a required document, later incomplete stages are
still recorded but do not replace the first-loss attribution.

Candidate availability is evaluated before serving selection:

```text
retrieval_top20 -> retrieval_top5 -> controller_search -> post_acl
-> post_guard -> ledger -> response_selection -> post_grounding -> final
```

This order distinguishes "the retriever could not find it in 20" from "it was
available but not selected into top 5".

## Stage meanings

| Stage | Recorded set | Failure label |
| --- | --- | --- |
| `retrieval_top20` | Current BM25 + dense + RRF article candidates 1-20 | `RETRIEVAL_TOP20_MISS` |
| `retrieval_top5` | Current ranking articles 1-5 | `RETRIEVAL_TOP5_MISS` |
| `controller_search` | Raw top-k candidate hits requested by the controller | `CONTROLLER_SEARCH_INSUFFICIENT` |
| `post_acl` | Controller hits visible to the WixQA evaluation identity | `ACL_FILTERED` |
| `post_guard` | Hits admitted by retrieved-content security | `GUARD_FILTERED` |
| `ledger` | Distinct supporting document IDs assembled into the ledger | `LEDGER_ASSEMBLY_LOSS` |
| `response_selection` | Evidence selected by the extractive response builder | `RESPONSE_BUILDER_CITATION_OMISSION` |
| `post_grounding` | Source IDs after deterministic citation verification | `GROUNDING_GATE_REMOVAL` |
| `final` | Source IDs in the returned response | `EVALUATOR_MISMATCH` |

The case schema also records Controller terminal mode/reason separately from
the final response mode/reason. A verifier may downgrade a response because a
claim is unsupported without removing the source object; that response-mode
change is reported independently and does not become a false document-loss
attribution.

WixQA's navigator exposes all benchmark articles to one public tenant, so in
this fixture the raw controller set is also the post-ACL set. The equality is
recorded and tested; ACL is not bypassed or changed.

## Non-document diagnostics

`QUERY_ANALYSIS_UNDERSPECIFIED` is reported as a structural flag when a case
requires multiple gold documents but analysis emits only `['answer']`. It does
not override an earlier document-set loss. The aggregate separately reports
cases where Ledger coverage is `1.0` while benchmark-required gold document
coverage is below `1.0`; this is named a representation gap relative to the
benchmark, not a violation of the Ledger's current contract.

Prompt and generation fields are retained in the schema for explicit causal
boundaries. For this frozen source run they are marked
`NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE`, because the runner used deterministic
extractive response construction rather than `generation_v2` or an LLM.

## Validation rules

- Gold IDs must be distinct and resolve to source articles.
- `gold_document_count` must equal the number of distinct gold IDs.
- Every stage coverage value must recompute from the serialized sets.
- `first_loss_stage` must be a finite enum and match recomputation.
- The representation-gap flag must match Ledger and gold coverage values.
- Diagnostic wrappers must produce the same public response and security trace
  as an unwrapped run.
