# Benchmark Gap Analysis

## Dataset audit

| Dataset | Domain / data | Questions and gold | Provenance | Consumption | May tune? | Can prove | Cannot prove |
|---|---|---|---|---|---|---|---|
| FinanceBench | Financial reports; PDF pages, prose, tables | Financial QA; answer and source-document/page relationships vary by task representation | External public benchmark | Dev and historical fixed test are consumed | Only on newly frozen, non-overlapping data | Known-corpus financial page retrieval and complex-document failure modes | General enterprise support, hidden-test generalization, open-corpus document discovery, current answer accuracy |
| FinQA | Financial reports; text, tables, numerical programs | Numerical QA with answer, gold program, and evidence | External public benchmark | Fixed 100-case sample, 60-case calibration, 40-case internal validation, and other disclosed dev cohorts are consumed as recorded in historical protocols | Only untouched official rows under a new preregistered protocol | Numerical reasoning, evidence recall, deterministic execution, citation stress | Enterprise knowledge retrieval, full FinQA/SOTA, production quality, blind accuracy |
| UDA-QA FinHybrid | Financial reports; mixed text/table pages | Page-localization questions with source-page gold in a known report | External public benchmark | 64 dev and 96 fixed test consumed; later R3 dev cohorts disclosed | No post-test tuning; only a newly isolated cohort | Page retrieval within a known report, page-level latency | Open-corpus document discovery, answer correctness, hidden holdout, enterprise heterogeneity |
| garak LatentInjectionReport subsets | Retrieved-content prompt injection and benign controls | Attack/benign labels; deterministic exposure and behavior checks | External probe family plus local deterministic fixtures | Original and expanded/recombined sets consumed | New probe-family-disjoint set only | Guard OFF/ON ASR, context exposure, benign false positives under fixed model/config | Benchmark-wide garak robustness, unseen attack families, production security |
| Synthetic enterprise policy corpus | Policies, versions, ACLs, conflicts, lifecycle changes | Generated facts, expected visibility and lifecycle outcomes | Project-generated synthetic | Development and frozen regression cohorts consumed according to v2 manifests | Generator changes require a new version; existing frozen set is regression-only | Determinism, ACL isolation, version semantics, lifecycle and trace contracts | Real-enterprise language, organic user behavior, external generalization |
| Quality-review calibration packet | Selected project outputs for two-reviewer calibration | Human rubric slots and campaign state | Project-generated packet | Calibration packet fixed; human pilot not completed | No relabeling for score optimization | Review workflow integrity | Human quality score or inter-rater agreement until reviews exist |

## Gap by product claim

| Desired claim | Current evidence | Gap |
|---|---|---|
| Real customer-support knowledge RAG | None | Need official KB snapshot, authentic/expert query set, article gold, and answer gold |
| Heterogeneous internal company search | Synthetic policy corpus only | Need external multi-source corpus with source-native identity and category gold |
| Bounded Agent beats single-shot RAG | Mechanism and trace tests | Need same retriever/model/data paired quality-cost comparison |
| Multi-document completeness | Synthetic fact model | Need external multi-article or multi-document gold |
| Conflict handling | Synthetic version/conflict cases | Need official conflict category and paired Ledger experiment |
| Correct refusal | Synthetic and security cases | Need official information-not-found/unanswerable cases |
| Source-aware parsing/chunking helps | PDF/table engineering only | Need flat vs source-aware paired ablation on native enterprise sources |

## Existing architecture gaps exposed before E1

1. The canonical document model is policy-document oriented. It has strong ACL,
   version, and provenance fields but lacks an additive source-native envelope
   for participants, thread IDs, parent IDs, authors, timestamps, ticket state,
   repository, speaker turns, and arbitrary official metadata.
2. Fixed/heading/parent-child chunkers are valid controls, but no source-aware
   thread/ticket/speaker/procedure chunker has benchmark evidence.
3. The default Agent does not select `find`; only search and conditional open
   can be evaluated as the current bounded policy.
4. Historical retrieval conclusions are domain-specific. A weak finance BM25
   arm cannot justify omitting lexical retrieval from enterprise support text.
5. Existing end-to-end answer metrics need benchmark adapters that map official
   answer, article, evidence, unanswerable, and category fields without inventing
   metadata.

## Repositioning decision

FinanceBench, FinQA, and UDA remain maintained as
`COMPLEX_DOCUMENT_TABLE_STRESS`. They do not contribute the headline score for
enterprise-aligned evaluation. The first new primary track is WixQA because it
has a bounded official corpus and authentic/expert support queries, making it
feasible to establish a reproducible baseline before attempting a 500k-document
heterogeneous corpus.

