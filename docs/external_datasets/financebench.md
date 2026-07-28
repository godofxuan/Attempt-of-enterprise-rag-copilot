# FinanceBench External Evaluation Track

## Purpose

FinanceBench is an external, real-document evaluation track. It does not
replace the synthetic enterprise corpus:

- the synthetic corpus remains the deterministic regression, ACL, lifecycle,
  and fault-injection fixture;
- FinanceBench measures generalization on public financial filings;
- results from the two tracks must be reported separately.

The adapter is pinned to upstream commit
`cc39aeb4afdf33909ee1412188bf89035950c2eb`. The upstream repository does not
contain an explicit license file at that revision, so downloaded JSONL and PDF
files remain under `.private/` and are not committed to this repository.

The adapter also preserves upstream nullability instead of inventing labels:
50 open-source cases have no `justification`, and 50 have no declared
`question_reasoning`. Those values remain explicit `null` in the evidence
sidecar and are not silently converted into human annotations.

The upstream document-information file also contains one conflicting duplicate
for an unreferenced Foot Locker document. The adapter ignores that unused row
but fails closed if conflicting metadata ever affects a document referenced by
an evaluation question.

## Data flow

```text
Pinned GitHub revision
  -> bounded HTTPS download
  -> JSONL schema and SHA-256 validation
  -> referenced-PDF completeness and PDF-magic validation
  -> Enterprise CorpusManifest + page-level evidence sidecar
  -> company-grouped dev/test split
  -> parser/chunker/index pipeline
  -> retrieval evaluation
```

The company-grouped split is stricter than a random question split. All
questions for one company stay in one partition, preventing filings for the
same company from appearing in both development and frozen test data.

Each filing receives its own governance `policy_id`. Company is retained as
dataset metadata, not represented as a policy-version chain: annual and
quarterly filings are independent active records, so treating all filings from
one company as competing versions would violate the one-active-authority
invariant.

## Prepare

All defaults resolve under the repository's D-drive `.private` directory:

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.prepare_financebench
```

The command downloads only the 84 PDFs referenced by the 150 open questions,
not all PDFs in the upstream repository. It writes:

- `upstream/<revision>/manifest.json`: compatible corpus manifest;
- `prepared/<revision>/eval/dev.json`: retrieval-compatible dev cases;
- `prepared/<revision>/eval/test.json`: frozen retrieval-compatible test cases;
- `dev_evidence.json` and `test_evidence.json`: exact one-based page evidence;
- `external_dataset_manifest.json`: upstream, split, count, and hash evidence.

Verify without rewriting:

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.prepare_financebench --verify-only
```

## Parse and chunk dry run

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.build_financebench_index --dry-run
```

This invokes the project's existing PDF parser, normalization, governance,
deduplication, and chunking pipeline without calling Ollama.

The external track deliberately uses page-aware `heading` chunks with a
1,800-character window and 150-character overlap. The project's generic
parent-child defaults were designed for short policy documents; on the 84
FinanceBench filings they produced 289,326 total chunks and 242,946 indexable
chunks. Calling BGE-M3 once per child at that scale is not an acceptable
baseline. External chunking parameters remain explicit CLI options so this
decision can be measured rather than hidden.

## Build an isolated live index

Ollama and `bge-m3` must be available:

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.build_financebench_index
```

The index is stored under `.private/external_datasets/financebench/indexes`.
It never replaces the active synthetic-corpus index.

The live builder uses bounded batches (`32` items and `48,000` characters by
default) and resumable `.npy` shards under
`.private/external_datasets/financebench/embedding_cache`. Cache identity binds
the exact Ollama model digest, dimension, corpus manifest, parser versions,
chunker configuration, and ordered chunk text hashes. A rerun validates every
shard before reuse and recomputes only missing or corrupt batches.

## Evaluate retrieval

```powershell
$root = '.private\external_datasets\financebench'
$revision = 'cc39aeb4afdf33909ee1412188bf89035950c2eb'

& '.\.venv\Scripts\python.exe' -m scripts.eval_enterprise_v2 `
  --suite retrieval `
  --split dev `
  --mode live `
  --entity-scope financebench `
  --run-id financebench-dev-bge-m3-v1 `
  --corpus-dir "$root\upstream\$revision" `
  --eval-dir "$root\prepared\$revision\eval" `
  --index-root "$root\indexes"
```

Run the frozen test only after the development configuration is fixed.

`--entity-scope financebench` builds an entity catalog from upstream document
metadata, not evaluation gold labels. It resolves public company aliases,
runs exact-year and entity-history scopes, and merges them deterministically.
The two scopes share one query embedding, one full FAISS search, and one BM25
score array. The catalog SHA-256 is recorded in the evaluation manifest.

The fixed document-level development configuration is `heading/1800/150`,
`top_k=5`, `candidate_k=20`, and entity-scope v5. Its observed 49-case dev
result is Recall@3/5 `100%`, MRR `94.56%`, nDCG@5 `95.97%`, mean retrieval
latency `799 ms`, and zero ACL leakage.

## Evaluate exact page localization

The page evaluator separately measures whether retrieved chunks carry the
FinanceBench gold `(doc_id, page_number)` references:

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.eval_financebench_pages `
  --run-id financebench-page-retrieval-dev-bge-m3-dense-topdoc-v1 `
  --page-drilldown `
  --drilldown-mode dense `
  --drilldown-max-documents 1
```

The selected dev variant preserves document Recall@5 `100%` and records Page
Hit@5 `48.98%`, complete Page Recall@5 `38.78%`, macro Page Recall@5 `43.88%`,
98 embedding calls, and `1,108 ms` mean latency. This is page localization,
not answer accuracy or semantic citation correctness.

The exact test configuration is frozen in
`docs/external_datasets/evidence/financebench_page_retrieval_freeze_v1.json`.
The test entry point rejects parameter changes, a dirty tracked worktree, and
missing explicit confirmation:

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.eval_financebench_pages `
  --split test `
  --execute-frozen-test `
  --run-id financebench-page-retrieval-test-bge-m3-frozen-v1 `
  --page-drilldown `
  --drilldown-mode dense `
  --drilldown-max-documents 1
```

The command was executed after the dev protocol was frozen. The immutable test
run reports document Recall@5 `95.05%`, Page Hit@5 `30.69%`, complete Page
Recall@5 `24.75%`, and macro Page Recall@5 `27.72%`. The lower score is retained
as the generalization result; v1 must not be retuned against these 101 cases.

The first execution attempt failed before publishing any artifact because two
test cases contained multiple evidence snippets on the same page. The adapter
was corrected to normalize snippets into unique `(doc_id, page_number)`
identities without changing retrieval configuration. Both the failed
precondition and completed run are recorded in the engineering results.

## Current scoring boundary

`dev.json` and `test.json` use the existing document-level `EvalCase` contract,
so they can measure retrieval immediately. The evidence sidecars preserve the
upstream page number, exact evidence text, full-page text, answer, and
justification for a subsequent FinanceBench-specific answer and citation
scorer.

Do not report document recall or page localization as FinanceBench answer
accuracy. Exact numeric normalization, generation, claim-level citation
entailment, and human review are separate evaluation steps.
