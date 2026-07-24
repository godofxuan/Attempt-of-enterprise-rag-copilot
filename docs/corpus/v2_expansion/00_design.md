# R2-S6 Versioned Corpus Expansion Design

Status: implemented and locally accepted

Date: 2026-07-24

## 1. Trigger

The original corpus contract was reproducible but narrow:

| Dimension | v1 |
|---|---:|
| Policies | 8 |
| Versions | 16 |
| Atomic facts | 32 |
| Active facts | 16 |
| Departments | 7 |
| Fixture users | 10 |
| Demo documents | 72 |
| Benchmark documents | 600 |
| Dev / test cases | 24 / 28 |

The 600-document profile increased document count mostly by generating more
supporting and noisy variants around the same 32 facts. It was useful for
parser and indexing scale tests, but it did not materially widen the knowledge
domain. A larger number alone would therefore be a misleading improvement.

## 2. Decision

Keep `enterprise_facts_v1` immutable and introduce a separate
`enterprise_facts_v2` source of truth. The expanded profiles use v2; the
historical `demo` and `benchmark` profiles continue to use v1.

This gives four explicit presets:

| Profile | Facts | Documents | Purpose |
|---|---|---:|---|
| `demo` | v1 | 72 | Historical compatibility and fast tests |
| `benchmark` | v1 | 600 | Historical scale baseline |
| `expanded` | v2 | 240 | New default local knowledge base |
| `expanded_benchmark` | v2 | 2,000 | Parser/dedup/index scale exercise |

The production-like local default is `expanded`, not
`expanded_benchmark`. Both contain the same fact breadth. The larger profile
adds noise and supporting-document volume, so activating it by default would
increase build cost without adding new authoritative knowledge.

## 3. Frozen target

The implementation target was frozen before adding content:

```text
20 policies
40 policy versions
104 atomic facts
52 active facts
12 departments
15 fixture users
15 ACL groups
240 expanded documents
2,000 expanded benchmark documents
48 dev + 56 frozen test cases
```

Every active fact must occur in:

1. its authoritative active policy document; and
2. at least one non-authoritative supporting document.

Every policy must have at least three supporting source types. Both profiles
must contain all five formats and all six source types supported by the
generator.

## 4. Added knowledge domains

The v2 fact model adds these policy families while retaining all eight v1
families:

- security access review;
- IT change management;
- data retention;
- privacy requests;
- invoice processing;
- sales discounts;
- customer escalation;
- supplier onboarding;
- engineering on-call;
- visitor management;
- employee leave;
- compliance audit.

Each added family has one retired 2025 version, one active 2026 version, and
three atomic facts per version. Values intentionally change between versions
so retrieval must still prefer current authoritative evidence.

## 5. Alternatives rejected

### Only raise `document_count`

Rejected because it repeats the same facts and inflates the apparent knowledge
base without improving answerable scope.

### Replace v1 in place

Rejected because it would invalidate historical hashes, old evaluation
evidence, and exact-output tests. Versioning is cheaper than rewriting
provenance.

### Ask an LLM to write arbitrary gold documents

Rejected because authority, version conflicts, ACL visibility, and expected
facts would no longer be exactly reproducible. LLM-generated prose can be
added later as a separately labeled realism layer, but it must not silently
become the source of truth.

### Use the 2,000-document profile as the default

Rejected because local FAISS rebuild time and repository setup cost would rise
while fact breadth remains identical to the 240-document profile.

## 6. Release gates

The deterministic corpus gate checks:

- schema version and exact profile document count;
- minimum policy/version/fact/active-fact/department breadth;
- unique fact questions and statements;
- every operational ACL group is used by at least one policy version, except
  the explicit unauthorized-contractor fixture;
- complete supporting coverage of active facts;
- minimum source diversity per policy;
- all required formats and source types;
- exact eval split sizes;
- unique and disjoint case IDs;
- every active fact appears in at least one case's `required_fact_ids`;
- all six task types and all departments in evaluation.

The live acceptance gate checks:

- a real local BGE-M3 index can be built and atomically activated;
- manifest model and vector dimensions match;
- dev and frozen test retrieval contain no failed cases;
- ACL leakage is zero;
- `hit@1` and `document_recall@3` meet the recorded thresholds;
- the old active index remains available as a rollback target.

## 7. Rollback

The previous immutable index remains:

```text
20260716T135632Z_7aec4b9_live_bge_m3_fixed
```

Rollback does not rebuild embeddings:

```powershell
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 `
  --output-dir data\indexes_v2 `
  --activate-existing 20260716T135632Z_7aec4b9_live_bge_m3_fixed
```

Code-level rollback can set `V2_CORPUS_PROFILE=demo` without deleting the v2
facts or profiles. Historical v1 outputs remain byte-for-byte tested.

## 8. Claim boundary

This stage proves deterministic synthetic breadth, local parser/index
lifecycle, and retrieval behavior on generated dev/test cases. It does not
prove correctness on real enterprise documents, production traffic,
multilingual writing, OCR-heavy files, human semantic usefulness, or an
incremental freshness SLA.
