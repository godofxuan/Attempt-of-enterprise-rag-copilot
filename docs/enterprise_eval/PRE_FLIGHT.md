# Enterprise Evaluation Pre-flight

## Frozen repository state

| Field | Value |
|---|---|
| Audit baseline supplied by reviewer | `d9c7294d59b166523febfcfe3b23a23c3c66b9b1` |
| Pre-flight HEAD | `d9c7294d59b166523febfcfe3b23a23c3c66b9b1` |
| Branch | `codex/rag-eval-system` |
| Worktree before E0 | clean |
| Pre-flight date | `2026-08-09` |
| Host | Windows, repository and private data on `D:` |
| GPU | NVIDIA GeForce RTX 5060, 8151 MiB reported memory |
| Free space at pre-flight | 68.93 GiB on `D:` |

Commands used:

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git log -20 --pretty=format:'%h %ad %s' --date=short
```

The HEAD had not advanced beyond the supplied audit baseline. No reset was
performed. Future experiment records bind their own exact SHA rather than
silently inheriting this pre-flight SHA.

## Product position

The primary product is an enterprise knowledge copilot: support knowledge,
internal knowledge, heterogeneous company sources, missing information,
conflicts, and multi-document completeness. FinanceBench, FinQA, and UDA are
retained only as the complex-document/table/numerical stress track.

This new evaluation program does not contradict the R3 recommendation to stop
adding unproven features. It introduces a missing product-aligned measurement
surface. Candidate implementation remains blocked until a measured failure
supports a specific change.

## Existing ingestion and lifecycle capability

- Parsers exist for text/Markdown, PDF, DOCX, and EML, with restricted-file
  validation, safe staging, quarantine, parse warnings, and path controls.
- `DocumentRecord` preserves source type, source path, project, tenant, ACL,
  region, document version, effective interval, authority, checksum, parser,
  structured sections, tables, and provenance-oriented hashes.
- Chunking has fixed, heading, and parent-child controls, plus explicit table
  row chunks. It does not yet preserve native Slack threads, mail threads,
  ticket comments, meeting speakers, or CRM field semantics.
- Revision catalog, source events, tombstones, deterministic change plans,
  immutable target snapshots, atomic activation, deletion verification, and
  rollback mechanisms exist from the lifecycle program.
- Generated corpora, indexes, evaluation runs, and private artifacts are
  excluded from Git. New external data must live under the ignored
  `.private/external/` tree on `D:`.

## Existing retrieval and agent capability

- Retrieval arms support BM25, dense retrieval, and hybrid fusion.
- V2 search supports ACL-aware filters, candidate bounds, parent inclusion,
  evidence admission, retrieved-content guard, and traceable tool execution.
- The bounded V2 controller searches once per required aspect and can
  conditionally open a document for completeness.
- `find` is implemented as a guarded tool and its result is accepted by the
  controller, but the default controller does not emit a `find` action.
  Therefore the current default path is accurately described as bounded
  `search -> conditional open`, not autonomous `search -> find -> open`.
- Evidence Ledger, citation verification, refusal outcomes, identity boundary,
  and prompt-injection guard exist. Their enterprise utility still requires
  benchmark-specific paired experiments.

## Existing evaluation surfaces

| Surface | Existing deterministic metrics | Current role |
|---|---|---|
| Retrieval | Hit/Recall at K, MRR, nDCG, macro page recall, latency | Reusable metric code; old results are finance-specific |
| Answer | strict/execution accuracy, grounded strict, omission/error taxonomy | Reusable where benchmark gold permits |
| Citation | precision, recall, coverage | Reusable after article/evidence mapping |
| Refusal | precision, recall, false refusal | Reusable for official unanswerable cases |
| Agent | route/action/trace completeness, tool counts, budgets | Mechanism evidence; not yet enterprise quality evidence |
| Security | ASR, context exposure, benign false positive, overhead | Strong custom/garak stress evidence with scope limits |
| Lifecycle | immutable evidence, replay, rollback, fault injection | Engineering evidence, not RAG answer quality |

## Existing external and synthetic datasets

- FinanceBench: external financial reports and page retrieval; historically
  visible/consumed evaluation state.
- FinQA: external financial table/text numerical QA; several development and
  fixed cohorts have been consumed.
- UDA-QA FinHybrid: external known-report page localization; development and
  fixed test consumed.
- NVIDIA garak-derived prompt-injection probes: external probe source with local
  deterministic pair/recombination construction; security stress evidence.
- Versioned enterprise policy corpus: synthetic, deterministic, useful for ACL,
  lifecycle, and regression tests; not evidence of real-enterprise accuracy.

## Existing negative results that constrain this phase

- BM25 and RRF harmed ranking on the old FinanceBench development protocol.
  This does not prove they harm WixQA or heterogeneous enterprise retrieval.
- A generic cross-encoder was not Pareto-improving on the old finance task.
  It is not promoted by default on new data.
- Finance parser replacement was not supported by the measured failure mix.
- Automatic adaptive retrieval remained disabled because prior benefit did not
  justify cost and risk.
- Multiple FinQA typed-planning candidates improved intermediate contracts but
  failed end-to-end adoption gates. They remain stress-track experiments.

## E0 gates

- [x] Exact repository identity captured.
- [x] Product positioning corrected.
- [x] Current tools and default agent path distinguished.
- [x] Existing benchmark evidence and consumption limitations inventoried.
- [x] Private data location fixed to `<repository>/.private/external` on the
  local `D:` drive.
- [x] Candidate benchmark research uses official sources and pinned revisions.
- [x] Primary shortlist limited to three.
- [ ] A new enterprise benchmark has been downloaded and evaluated. This is an
  E1 outcome and must not be implied by this pre-flight document.
