# R2-S6 Corpus Expansion Results and Interview Guide

## 1. One-minute project explanation

The original project had a deterministic 72-document demo and a 600-document
benchmark, but both were derived from only 32 atomic facts. I did not simply
increase the document count. I versioned the truth model, expanded it to 20
policies, 40 versions, and 104 facts across 12 departments, then generated a
240-document default corpus and a 2,000-document scale profile.

I added deterministic coverage guarantees, a corpus quality CLI, CI gates, and
a public evidence package. I built and activated a real local BGE-M3 index:
240 source documents became 216 canonical documents and 216 indexed chunks
after duplicate governance. Supporting documents and evaluation cases each
cover 100% of active facts. The 48-case dev and 56-case frozen test retrieval
runs both had zero failed cases and zero ACL leakage, with hit@1 and
document-recall@3 equal to 1.0. The old index remains an immutable rollback
target.

## 2. Why this is more than data padding

Document count and knowledge breadth are different:

- More documents around the same facts test scale and noise tolerance.
- More policies, versions, facts, departments, and ACL groups increase the
  answerable domain.
- Supporting coverage ensures active facts are not available only in one
  perfect authoritative document.
- Retired/current conflicts test authority and temporal ranking.
- Duplicate, near-duplicate, stale, and misfiled variants test governance.

The new default increases both breadth and realistic retrieval noise. The
2,000-document profile increases only the second dimension and is therefore
kept as a benchmark.

## 3. Why not generate gold data with an LLM

An LLM can improve linguistic variety, but arbitrary generation weakens the
evaluation oracle. This project needs to know exactly:

- which version is active;
- which fact IDs are required;
- which users can see which documents;
- which document is authoritative;
- which values are stale or conflicting.

The checked-in fact model is therefore the authority. A future LLM paraphrase
layer should be derived from those facts, validated for preservation, and
labeled separately.

## 4. Why precision@3 and precision@5 look low

The frozen test result has:

```text
precision@3 = 0.4103
precision@5 = 0.2462
hit@1       = 1.0
recall@3    = 1.0
```

This is not contradictory. Many questions have one gold document. If the
retriever returns that gold document first plus four useful but non-gold
supporting documents, precision@5 is `1/5 = 0.2` even though hit@1 and recall
are perfect. Comparison questions have two gold documents and therefore score
differently.

For this workload:

- `hit@1` answers “was at least one gold document ranked first?”;
- `document_recall@3` answers “were all required gold documents present by
  rank 3?”;
- precision measures the fraction of the fixed top-k list marked as gold.

Low fixed-k precision is still a cost signal: extra context can increase token
usage or distraction. It should not be described as irrelevant, but it is not
the same as a retrieval miss.

## 5. Why fixed chunking remained selected

This stage changes the corpus, so it keeps the previously active fixed
chunking strategy. Changing corpus and chunking together would make causality
unclear. The parser dry run showed one compact chunk per canonical generated
document, and frozen retrieval met the release thresholds.

Heading or parent-child chunking should be admitted only through a separate
ablation on longer, structurally varied documents.

## 6. How rollback works

Each index lives under an immutable run ID. Build occurs in staging and the
active pointer moves only after artifact, hash, model, and dimension checks
pass.

Current:

```text
20260724T024653Z_expanded_bge_m3_fixed
```

Rollback:

```text
20260716T135632Z_7aec4b9_live_bge_m3_fixed
```

Activation of an existing version does not call the embedding model or rewrite
the old artifacts.

## 7. Likely interview questions

### How did you prevent train/test leakage?

The test split is serialized with a SHA-256 manifest and verified before a
test run. Dev is used for implementation feedback. Test is executed as a
frozen regression and is not repeatedly used to tune ranking parameters. The
new generated profile has its own dev/test files and hash.

The deeper limitation is that both splits are generated from the same
synthetic fact model. They are useful for contract regression, not
independent-domain generalization. Human and external-domain evaluation remain
required.

### How do you know every new fact is retrievable?

The generator first creates deterministic supporting assignments that cover
every active fact, then fills remaining supporting capacity randomly. The
quality gate computes the union of supporting fact IDs and requires 100%
coverage. Live retrieval separately proves the index/ranker can recover gold
documents for the frozen questions.

### Why have authoritative and supporting documents?

Authoritative documents define the correct current policy. Supporting
documents create realistic evidence redundancy and noise. The ranker must
retrieve useful content while authority logic prevents an email, ticket, stale
copy, or retired policy from overriding the current policy.

### What does deduplication do here?

It groups exact and near-identical generated variants before indexing. In the
240-document profile, 24 documents were removed and 216 canonical documents
were indexed. In the 2,000-document profile, 775 were removed and 1,225
remained. This reduces redundant context and indexing cost while retaining the
manifest-level source record.

### Why use a local FAISS index instead of a vector database?

At 216 active chunks and 1,225 benchmark chunks, local FAISS plus immutable
version directories meets the measured need and is easy to reproduce. A
vector service is deferred until document count, QPS, multi-tenant operations,
or update SLA creates a measurable failure. Migration would need the same
retrieval, ACL, backup, cost, and rollback gates.

### Is zero ACL leakage enough to call the system secure?

No. It means these synthetic evaluation cases returned no forbidden documents
through the tested path. It does not prove production IAM, connector ACL
correctness, side-channel resistance, or universal authorization safety. The
trusted identity and retrieved-content Guard have separate threat models and
evidence.

### Why is the quality gate rule-based rather than LLM judged?

Counts, uniqueness, schema, fact coverage, split disjointness, and source
diversity are deterministic properties. Using an LLM for them would add cost
and variance without improving correctness. Human or calibrated model review
is appropriate for prose naturalness and semantic usefulness, which this gate
does not claim to measure.

### What was the most important bug found during expansion?

The completeness question template hard-coded “two requirements.” New active
policies have three facts, so the evaluation question contradicted its own
required fact IDs. A RED test exposed it; the generator now derives the
Chinese count label from the actual fact count while preserving v1 bytes.

### What would you do next for real industrial use?

1. collect an approved, de-identified sample of real document structures;
2. add connector and deletion/freshness contracts;
3. run blind human semantic review and an independent-domain holdout;
4. measure update frequency and rebuild SLA before designing incremental
   indexing;
5. deploy the existing immutable build/activate/rollback path in a minimal
   non-root Linux environment with durable privacy-bounded telemetry.

## 8. Honest limitations to state

- All knowledge is synthetic and Chinese-heavy.
- Supporting prose is templated and shares a source fact model with eval.
- The live result is from one local BGE-M3 model and one machine.
- No real connector, OCR-heavy corpus, production traffic, or freshness SLA
  was tested.
- Human semantic review is not complete.
- Checksums protect evidence integrity but are not a third-party signature.
