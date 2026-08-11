# Resume Codex Handoff

Any Codex drafting resume content for this project must read this file and every
file under `docs/handoffs/resume_package/`. It must not infer stronger claims
from README prose, test names, or architecture breadth.

## Canonical status

`PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW`

The project is suitable for portfolio and interview use within bounded evidence.
It is not production-proven. Blind answer correctness is not established. The
current multi-document candidate and equal RRF were rejected. Feature development
is stopped.

## Drafting algorithm

1. Read the target job description before selecting bullets.
2. Choose exactly one positioning from `ROLE_POSITIONING.md`.
3. Use at most three primary and two backup bullets from
   `BULLET_CANDIDATES.md`.
4. Resolve every number through `SAFE_METRICS.md` and `EVIDENCE_MAP.md`.
5. Keep each bullet to one or two resume lines and use
   `action -> project problem -> scale -> measured result`.
6. Prefer evidence to adjectives. Do not use "enterprise-grade", "production-
   grade", "high accuracy", "high reliability", "leading", or "secure".
7. Do not list a technology merely because it appears in a job description.
8. Keep this RAG project focused on retrieval, evidence control, evaluation,
   security, and indexing. Do not import distributed scheduler/lease/fencing
   claims from a separate EvalOps project.
9. If a requested number has no evidence mapping, write `NO_EVIDENCE` and omit it.
10. Generate a proposed project section only. Do not overwrite the user's real
    resume without its layout, other experience, and target JD.

## Evidence hierarchy

Use the levels precisely:

```text
implemented < tested < measured < reproduced < externally validated < production proven
```

This repository has examples in the first five categories under bounded scopes;
it does not claim production proof. A public external benchmark is not
automatically blind. A local clean replay is not third-party reproduction.

## Mandatory exclusions

- Do not call Recall@5 or nDCG@5 "accuracy".
- Do not claim Agent quality improved.
- Do not use oracle, consumed development, or synthetic same-fact scores as blind
  quality.
- Do not claim full garak coverage, universal prompt-injection defense, or a
  precise benign false-positive rate from two controls.
- Do not claim production traffic, SLO, HA, real enterprise IdP, distributed
  indexing, or power-loss durability.
- Do not add LangGraph, GraphRAG, MCP, Redis, Kafka, or another model/vector
  database to the project description; they are not evidence-backed needs.

## Package contents

- `PROJECT_SUMMARY.md`: facts and boundaries.
- `ROLE_POSITIONING.md`: three genuinely different role angles.
- `SAFE_METRICS.md`: permitted numbers and classes.
- `BULLET_CANDIDATES.md`: bounded bullet pool.
- `EVIDENCE_MAP.md`: bullet-to-artifact traceability.
- `FORBIDDEN_CLAIMS.md`: fail-closed wording list.
- `INTERVIEW_STORIES.md`: negative and positive story references.
- `JD_KEYWORD_MAP.md`: dated official-career-site market snapshot.
