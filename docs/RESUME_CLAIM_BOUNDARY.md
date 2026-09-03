# Resume Claim Boundary

This is the final claim boundary for the portfolio release. Every numeric claim
must retain its stated dataset and metric scope.

## SAFE_TO_WRITE

- Built an enterprise-oriented Agentic RAG runtime with server-owned identity and
  ACL enforcement, bounded tool execution, retrieved-content prompt-injection
  filtering, Evidence Ledger tracking, citation/grounding gates, and auditable
  trajectories. Implementation evidence is mapped in
  [PROJECT_EVIDENCE_MAP.md](handoffs/PROJECT_EVIDENCE_MAP.md).
- Designed an evidence-driven retrieval and Agent evaluation workflow that keeps
  positive, neutral, and negative results, and separates candidate retrieval,
  ranking, evidence sufficiency, query rewriting, and answer/citation failures.

## SAFE_WITH_DATASET_QUALIFIER

- On 200 fixed public-label WixQA ExpertWritten retrieval questions, BGE-M3
  Dense improved Recall@5 from 42.75% to 66.42% and nDCG@5 from 32.15% to
  52.16%. This is retrieval quality, not answer accuracy. Evidence:
  [F3 aggregate](adaptive_retrieval_v3/evidence/f3-simple-baselines-7d08d84.json).
- On 192 previously unused UDA company-disjoint known-report page-localization
  questions, page fusion improved Hit@5 from 80.21% to 88.02% and nDCG@5 from
  70.95% to 77.60% at 1.058x local p95. It is known-report page retrieval, not
  open-corpus or answer-quality evidence. Evidence:
  [R5 aggregate](r5/evidence/uda_finance_r5_public_v1.json).
- On a pinned 12-attack garak subset, the retrieved-content Guard changed attack
  success from 4/12 to 0/12 and context exposure from 12/12 to 0/12, with two
  benign controls preserved. It is a narrow local paired security observation,
  not universal safety. Evidence:
  [Guard aggregate](resume_metrics/evidence/garak_latent_report_holdout_v1.json).

## INTERVIEW_ONLY

- The corrected V3 Oracle comparison shows corrective rewrite can repair some
  known first-pass retrieval misses, but it does not validate a real router.
- Clean-root replay reproduced 63 frozen retrieval values at zero tolerance.
- Historical BGE reranking and multi-query profiles illustrate quality/latency
  trade-offs but are consumed-data experiments.

## NOT_SUPPORTED

- Do not call retrieval Recall@5 or nDCG@5 answer accuracy, answer relevance,
  production quality, or a production SLA.
- Do not describe consumed WixQA as blind, independent, or fresh validation.
- Do not claim that the adaptive V3 runtime improved quality: its Oracle result
  requires gold labels to select misses, while its executable assessor
  over-triggered.
- Do not call the Guard result complete benchmark coverage or universal security.
- Do not call this repository a production deployment or production-certified
  platform.

The numeric authority remains [RESUME_METRIC_LEDGER.md](handoffs/RESUME_METRIC_LEDGER.md).
