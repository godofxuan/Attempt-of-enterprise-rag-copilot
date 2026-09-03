# Final Interview Guide

## 30-Second Pitch

I built an enterprise-oriented Agentic RAG system where the LLM performs bounded
semantic tasks, while the server owns identity, ACL, retrieval execution, tool
budgets, retrieved-content safety, evidence tracking, and answer publication.
Retrieved material passes permission and prompt-injection checks before entering
an Evidence Ledger, and the response must pass citation and grounding gates. I
also evaluated retrieval and adaptive strategies experimentally, preserving
negative results instead of treating every additional Agent step as an upgrade.

## 90-Second Pitch

The project started as a knowledge-base RAG Copilot and was developed into an
evidence-governed Agent runtime. An authenticated request receives a server-side
identity and ACL context. The bounded controller can call typed search, find,
and open tools through a ToolGateway, which enforces permissions, deadlines, and
budgets. Search output is treated as untrusted: the Guard filters indirect prompt
injection before admitted material is recorded in the Evidence Ledger. The model
then drafts structured claims, while host code validates citations and removes
unsupported claims before publication. Trajectories are hash-chained for replay.

For retrieval, I compared BM25, BGE-M3 Dense, Hybrid RRF, reranking, and bounded
multi-query strategies with fixed artifacts and explicit data-consumption labels.
Dense was strongest in one same-harness consumed WixQA comparison, but I did not
silently switch the global runtime without fresh validation. I also repaired an
Oracle evaluation bug: the old cohort had been selected from a corrective arm's
outcome, so I rebuilt it from first-pass misses only. The corrected result showed
rewrite capacity, while the executable LLM assessor retried too often; therefore
the adaptive path remained experimental. The lesson is that bounded authority
and evidence-based selection matter more than adding Agent complexity.

## Questions and Answers

### Why not let the LLM call arbitrary tools?

Tool execution can expose data or create side effects. The LLM proposes bounded
semantic actions, but `ToolGateway` owns allowed tool names, request context,
ACL, budgets, deadlines, and result admission. That means a prompt or retrieved
document cannot grant itself authority.

### How does ACL enforcement work?

Identity is verified server-side, then tenant, group, role, region, and security
constraints are applied before source content is exposed. The model receives
only already-authorized, admitted evidence, not an unrestricted corpus handle.

### What happens if retrieved content contains malicious instructions?

Retrieved text is data, not instruction. The retrieved-content Guard scans it
before it enters the model-visible evidence set. Suspicious content is
quarantined or excluded; clean alternatives can still be used. This boundary is
independent of what the model chooses to follow.

### What is the Evidence Ledger?

It is the host-side record of admitted evidence, required aspects, source
visibility, and coverage. It helps distinguish “no authorized evidence”,
“evidence is incomplete”, and “the generated claim is unsupported”, and it
feeds citation and grounding checks.

### How do you know a citation is supported?

The response uses structured claims linked to visible source references. Host
validation checks citation shape and evidence availability, then grounding logic
rejects or removes claims that lack support. This is contract coverage, not a
claim of perfect semantic entailment.

### Why use Hybrid retrieval if Dense was the strongest simple benchmark arm?

Dense was strongest on a consumed 200-question WixQA experiment. The deployed
Hybrid path is already integrated with the project’s bounded control plane; a
single consumed benchmark is insufficient evidence for a global serving-policy
change. Dense is retained as an explicit experimental profile, not hidden.

### What failed during adaptive retrieval?

The LLM evidence assessor had high retry recall but triggered retries for 72.38%
of already-complete cases. Separately, after repairing the Oracle cohort, rewrite
could recover some true first-pass misses. These are different questions: a
correction can have value even when the runnable trigger is too imprecise. I kept
the simpler default rather than promoting incomplete evidence.

### How did you avoid benchmark overfitting?

I record whether each dataset is consumed, use exact revisions and hashes in
artifacts, avoid post-result tuning on consumed labels, preserve negative results,
and distinguish an Oracle diagnostic from a deployable policy. No V3 result is
called fresh validation because no unused compatible cohort was verified.

### What is still not production-verified?

Production traffic, organization-specific relevance judgments, real IdP/OAuth
deployment, production latency/SLOs, blind end-to-end answer accuracy, and
universal adversarial robustness are outside the evidence in this repository.
