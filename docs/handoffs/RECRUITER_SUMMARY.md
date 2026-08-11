# Recruiter Summary

Use these as speaking prompts, not scripts to recite word for word. Every number
below is mapped in `PROJECT_EVIDENCE_MAP.md`.

## 15 seconds

I built an evidence-controlled enterprise RAG project that separates retrieval,
authorization, grounding, security, and release evaluation, and I used frozen
gates to reject Agent features that added latency without fixing quality.

## 30 seconds

The project combines hybrid knowledge retrieval with host-owned identity/ACL,
retrieved-content admission, an Evidence Ledger, and citation filtering. On 200
WixQA support questions, BGE-M3 Dense improved retrieval Recall@5 from 42.75% to
66.42%; I also kept the weaker RRF and multi-document Agent candidates disabled
because paired evaluation showed worse quality/latency trade-offs.

## 90 seconds

Enterprise RAG fails in more places than generation: the wrong document may be
retrieved, permissions may be applied too late, poisoned text may enter Agent
state, required evidence may be incomplete, or an unsupported claim may be
published. I built explicit Python boundaries for those stages and a frozen
evaluation/evidence workflow around them. The strongest retrieval result is a
200-question WixQA comparison where Dense improved Recall@5 from 42.75% to
66.42%. For scale, a resumable FTS5 path built and atomically activated a 1.37
GiB index over 511,962 records in 231.35 seconds. For security, one pinned garak
subset changed observed attack success from 4/12 to 0/12, with narrow published
limitations. The project also records failures: equal RRF underperformed Dense,
and a bounded multi-document candidate added 1.86x p95 latency with zero complete-
case fixes, so it was rejected. The repository is portfolio-ready, not production-
ready, and feature development is intentionally stopped until a genuinely new
validation cohort or real-user failure pattern exists.

## Current boundary

- Portfolio/interview usable: yes.
- Engineering evidence credible within frozen scopes: yes.
- Blind answer correctness established: no.
- Universal security or production readiness: no.
- Current multi-document candidate shipped: no, rejected.
- More frameworks needed now: no measured justification.
