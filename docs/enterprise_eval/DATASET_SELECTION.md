# Dataset Selection

Research date: `2026-08-09`. Only official paper, repository, or dataset pages
are treated as authoritative. A revision pin records the source inspected; it
does not claim that the dataset has already been downloaded or run.

## Selected primary tracks

### Primary A: WixQA - selected for E1

- Official dataset: <https://huggingface.co/datasets/Wix/WixQA>
- Official paper: <https://arxiv.org/abs/2505.08643>
- Dataset repository revision inspected:
  `d662dc42479c14e202eccd832f8c4b66a035c4cc`
- License shown by the official dataset repository: MIT.
- Official assets expose a 6,221-article Wix knowledge-base snapshot and three
  QA sets: ExpertWritten, Simulated, and Synthetic.
- ExpertWritten contains 200 anonymized authentic support-ticket questions with
  expert answers and review. Simulated contains 200 validated user/expert-style
  conversations. Synthetic is the development-scale question set.

Why selected: it directly measures enterprise customer-support knowledge-base
RAG, provides article relationships and answers, is small enough for fresh-cache
reproduction, and includes multi-article questions.

Local protocol before label use:

- `Synthetic`: `DEVELOPMENT`; pipeline and candidate selection only.
- `Simulated`: `VALIDATION`; one fixed validation use after protocol freeze.
- `ExpertWritten`: `UNTOUCHED` until the baseline and candidate are frozen, then
  `FIXED_CONSUMED`; never called blind because labels are public.

### Primary B: EnterpriseRAG-Bench - selected, capacity-gated E2

- Official repository: <https://github.com/onyx-dot-app/EnterpriseRAG-Bench>
- Official paper: <https://arxiv.org/abs/2605.05253>
- Repository revision inspected:
  `d36685e273713975ee20299bbf1ab64165575b3c`
- Repository license: MIT.
- Official Hugging Face release: 511,962 documents and 500 questions from
  a synthetic company, spanning Slack, Gmail, Linear, Drive, HubSpot,
  Fireflies, GitHub, Jira, and Confluence.
- Categories include basic, semantic, intra-document, project-related,
  constrained, conflicting, completeness, high-level, and information-not-found
  questions.

Why selected: it is the strongest match for heterogeneous internal enterprise
knowledge, conflict, completeness, and refusal. Formal claims are forbidden
until the full official corpus/protocol runs. A subset may only debug the
pipeline and must be labeled `PIPELINE_DEBUG`.

The verified question schema is `question_id`, `question_type`, `source_types`,
`question`, `expected_doc_ids`, `gold_answer`, and `answer_facts`. The document
schema is only `doc_id`, `source_type`, `title`, and `content`; source-native
thread, author, timestamp, project, version, freshness, and ACL fields are not
available and must not be inferred. Four official source IDs are each reused by
two distinct records. One official conflicting-info row, `qst_0413`, repeats one
such expected ID; the adapter preserves both corpus records and the raw
annotation, and exposes an order-preserving set view only for explicitly
set-based retrieval metrics.

### Primary C: HERB - conditionally selected for E3

- Official repository: <https://github.com/SalesforceAIResearch/HERB>
- Official paper: <https://arxiv.org/abs/2506.23139>
- Repository revision inspected:
  `db3bf9b3f911745726c579c9dbf9f7f6b2c05b36`
- Official repository links the Hugging Face data and describes 39,190
  heterogeneous artifacts covering documents, meeting transcripts, Slack,
  GitHub, and URLs, with answerable and unanswerable tasks.

Why conditional: it can test deep search and single-shot versus bounded Agent,
but its generated-data/model-use terms and resource requirements must be
verified before local acquisition. No E3 manifest or result is created until
that qualification passes.

## Researched alternatives

| Candidate | Official source and pinned revision | Decision | Reason |
|---|---|---|---|
| TechQA | <https://github.com/IBM/techqa>, `f0cf8ce11c6ef778c6bc064ee6c1d9b3eca76faf` | Fallback | Real IBM support questions and a large Technote corpus; useful support retrieval, but WixQA has richer current article/answer packaging and multi-article focus |
| MTRAG / MTRAG-UN | <https://github.com/IBM/mt-rag-benchmark>, `cc5b1d481b391181b89f7ced860308482e785463` | Fallback | Strong multi-turn and unanswerable/underspecified evaluation, but not the first heterogeneous enterprise-corpus target |
| DocLayNet | <https://github.com/DS4SD/DocLayNet>, `66947398f04d050fed84e89e5509828f2ee17ecf` | Optional E8 only | Layout annotations for 80,863 pages; measures parser/layout preservation, not enterprise QA or answer quality; full assets exceed current low-risk storage budget |
| EKRAG | <https://aclanthology.org/2025.knowledgenlp-1.13/> | Research-only | Enterprise knowledge benchmark paper is relevant, but this audit did not verify an official public dataset/repository artifact suitable for reproducible ingestion |
| LayerRAG-Bench | <https://arxiv.org/abs/2607.27353> | Research-only | Very recent reliability benchmark; no verified official public code/data artifact was found in this audit |

## Bounded selection decision

The primary set is capped at WixQA, EnterpriseRAG-Bench, and conditional HERB.
TechQA and MTRAG are replacements, not additions. DocLayNet remains an optional
parser stress track. This prevents dataset count from becoming a substitute for
credible evaluation.
