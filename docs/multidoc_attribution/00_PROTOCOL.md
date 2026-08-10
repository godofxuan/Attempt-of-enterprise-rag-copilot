# WixQA Multi-document Failure Attribution Protocol

## Decision boundary

This stage diagnoses the frozen 20 multi-document cases from the existing
60-case WixQA ExpertWritten retrospective. It does not optimize retrieval,
planning, prompting, generation, grounding, or serving defaults.

Final status is limited to:

- `ATTRIBUTION_COMPLETE_NO_OPTIMIZATION`
- `ATTRIBUTION_BLOCKED`

The cohort is `RETROSPECTIVE_DEVELOPMENT_ONLY_CONSUMED`. Any later change
derived from these cases must be evaluated on a new blind multi-document
cohort.

## Frozen inputs

- Selection protocol:
  `docs/final_evidence_closure/evidence/answer_citation_60_protocol_v1.json`
- Source run details:
  `.private/external/wixqa/agent_eval_runs/wixqa-agent-expertwritten-v1-07b156e/details.jsonl`
- Dataset identity: `data_manifests/WIXQA_MANIFEST.json`
- Retrieval identity: the active immutable WixQA flat-index manifest
- Query embedding identity: must exactly match the index model name and hash

The command rejects anything other than exactly 20 multi-document cases,
unresolvable gold IDs, duplicate gold IDs, changed question/answer hashes, a
non-zero source completeness row, or an embedding/index identity mismatch.

## Public and private evidence

Public artifacts contain only identifiers, hashes, counts, stage coverage,
and classifications. Question text and controller query text remain under
`.private/external/wixqa/multidoc_attribution_runs/` and are hash-bound from
the public protocol/aggregate.

## Reproduction

After committing the instrumentation, run:

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.diagnose_wixqa_multidoc_failure `
  --run-id wixqa-multidoc-attribution-v1
```

The run records the committed Git SHA, source/protocol/index hashes, model
identity, command, runtime, case count, case-matrix hash, and private-details
hash. It exits non-zero unless all 20 cases replay and `UNKNOWN <= 2`.

## Diagnostic oracles

The Gold Retrieval Oracle puts every gold article first in the same ranked
navigation boundary, then keeps Guard, Controller, Ledger, extractive response
builder, and grounding behavior unchanged. It is `DIAGNOSTIC_ONLY` and is not
a production quality result.

The source run used `ExtractiveResponseBuilder`; it made no LLM generation
call. A same-model Gold Prompt Oracle is therefore
`NOT_APPLICABLE_SOURCE_RUN_EXTRACTIVE`, not silently replaced with a different
pipeline.

The gate diagnostic compares response-builder selections before deterministic
verification with final response sources. It never bypasses the gate in the
returned answer.

## Success gates

1. All 20 frozen cases replay.
2. At least 18 cases have a finite first-loss stage (`UNKNOWN <= 2`).
3. Aggregate counts recompute exactly from the case matrix.
4. Recording wrappers preserve answer, claims, citations, sources, search
   budget, and retrieved-content security trace.
5. Gold Retrieval, Gold Prompt applicability, and grounding-gate diagnostics
   all have explicit outcomes.

