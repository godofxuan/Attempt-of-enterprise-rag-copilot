# Portfolio Archive Report

Date: 2026-08-11

## 1. HEAD / CI status

The closure audit started from clean branch `codex/rag-eval-system` at full SHA
`2ea8f7621cc122fcce53c7f34ceebe900391b834`, equal to the fetched remote at
`0/0` ahead/behind. GitHub Actions Run
[`31417911335`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/31417911335)
reports `Success` for that exact SHA, including deterministic Ubuntu,
deterministic Windows, and Linux container-contract jobs.

Pre-edit local verification used Python 3.11.9: dependency check passed,
compileall passed, and the full suite reported `3226 passed / 30 skipped / 3`
known SWIG deprecation warnings. The exact-SHA portfolio gate passed `5/5`.

The final documentation delivery SHA is intentionally not hard-coded into its
own content. Resolve it with `git rev-parse HEAD` and verify it with:

```powershell
python -m scripts.verify_portfolio_release `
  --expected-branch codex/rag-eval-system `
  --expected-sha (git rev-parse HEAD)
```

## 2. Final portfolio state

`PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW`

Meaning: portfolio/interview usable; engineering evidence credible within its
frozen scopes; current multi-document Agent candidate rejected; blind answer
correctness not established; security claim bounded; production readiness not
claimed; feature development stopped.

Older `PORTFOLIO_READY_*` values remain only in dated historical reports.

## 3. Safe project claims

1. WixQA ExpertWritten fixed retrieval: Dense improved Recall@5
   `42.75% -> 66.42%` and nDCG@5 `32.15% -> 52.16%` on 200 questions.
2. EnterpriseRAG-Bench lexical capacity: 511,962 rows/9 sources, 1.37 GiB FTS5
   index, 231.35-second build, about 1.83 GiB peak RSS on one host.
3. Pinned garak subset: observed ASR `4/12 -> 0/12`, context exposure
   `12/12 -> 0/12`, mean Guard scan 1.42 ms, with only two benign controls.

Every wording boundary is in `PROJECT_EVIDENCE_MAP.md`.

## 4. Negative / rejected claims

- Equal RRF is rejected: lower Recall@5 than Dense and nearly double p95.
- The first external Agent route is rejected: no retrieval gain, find/open zero,
  no multi-document citation completeness, and higher latency.
- The bounded multi-document candidate is rejected: zero complete-case fixes,
  0pp completeness gain, -5.83pp precision, and 1.859x p95.
- Oracle and consumed-cohort metrics are diagnostic only.
- Full Enterprise Dense quality, blind answer correctness, calibrated human/judge
  agreement, production SLO, and universal security are not claimed.

## 5. Teaching Codex update

| File | Module | Purpose |
|---|---|---|
| `TEACHING_CODEX_HANDOFF.md` | Modules 1-8 | Single teaching entry: RAG stages, retrieval metrics, evidence control, Agent controller, multi-doc attribution, security, reliability, evidence engineering |
| `PROJECT_EVIDENCE_MAP.md` | claim traceability | Connects concepts to code, tests, JSON, execution SHA, wording, and interview explanation |
| `../learning/RAG_PROJECT_TEACHING_HANDOFF.md` | detailed historical lessons | Existing deep source walkthrough retained rather than duplicated |
| `../multidoc_candidate/04_LEARNING_AND_INTERVIEW_GUIDE.md` | rejected candidate | Detailed implementation and failure explanation |

## 6. Interview story bank

`INTERVIEW_STORY_BANK.md` contains eight evidence-backed stories: Dense/BM25,
equal RRF, Evidence Ledger, Guard OFF/ON, FTS crash/activation, multi-document
0/20, first-loss attribution, and final candidate rejection. Each uses
Situation, Problem, Hypothesis, Experiment, Result, Decision, Trade-off, and
What I learned.

## 7. Resume Codex update

`RESUME_CODEX_HANDOFF.md` is the fail-closed drafting contract. The
`resume_package/` directory contains the only facts a future resume task needs:
summary, three role positions, safe metrics, bounded bullets, evidence mapping,
forbidden claims, interview stories, and a dated JD map. The real resume was not
modified.

## 8. Current JD research

A 12-role official-career-site snapshot covers:

- AI Application/RAG/Agent: RAG delivery, bounded agents, evaluation, business
  integration;
- AI Evaluation: benchmark/evaluator infrastructure, groundedness, adversarial
  testing, failure analysis, reproducibility, release decisions;
- Python/AI Backend: data/index pipelines, CI/testing, latency/throughput, and
  systems engineering.

The exact roles, links, manual counts, and `NO_EVIDENCE` gaps are in
`resume_package/JD_KEYWORD_MAP.md`. The sample supports emphasizing evaluation
discipline and Python engineering; it does not justify adding another framework.

## 9. Resume bullets

`resume_package/BULLET_CANDIDATES.md` provides three main and two backup bullets
for each of:

1. AI Application / RAG / Agent;
2. AI Evaluation / GenAI Evaluation;
3. Python Backend / AI Platform.

They reorder evidence rather than substituting job-title words.

## 10. Resume metric ledger

`RESUME_METRIC_LEDGER.md` separates resume-primary, interview-supporting,
negative, and forbidden/misleading metrics. It explicitly prevents Recall@5,
oracle, clean replay, and small security denominators from being renamed as
answer accuracy, blind quality, third-party reproduction, or universal safety.

## 11. Forbidden claims

The fail-closed list is `resume_package/FORBIDDEN_CLAIMS.md`. Any requested
claim without an evidence-map row must be marked `NO_EVIDENCE` and omitted.

## 12. Recruiter README changes

The first README section now gives a 30-60 second view of the three capabilities,
three strongest measured results, the rejected candidate, current limitations,
and direct evidence/teaching entry points. The detailed architecture and evidence
remain available below rather than being removed.

## 13. Commits

This phase permits documentation and evidence-verifier changes only. It adds no
production feature commit. Git is the authoritative commit record; use
`git log --oneline -5` after delivery rather than copying a self-referential final
SHA into this file.

## 14. Final verification contract

`tests/test_portfolio_handoff_evidence.py` independently reads frozen JSON and
locks the metric ledger, canonical state, evidence-map fields and real paths,
eight teaching modules, eight stories, eight-file resume package, forbidden
claims, and 12 official JD URLs. It is included in the portfolio verifier's
`final_evidence_consistency` gate.

After implementation, the full local suite reported
`3232 passed / 30 skipped / 3` known SWIG deprecation warnings in 221.47 seconds.
The configured public repository audit scanned `1603` candidates and found `0`
findings. Test temporary files remained under repository-local `.private` on
`D:`.

This gate proves repository/evidence consistency, not model quality or
production readiness.

## 15. Final decision

`PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW`

Do not continue Agent/framework/model work. Resume scientific development only
after obtaining a new legally usable, independently frozen multi-document
cohort or a recurring real-user failure pattern. Then pre-register one bounded
candidate, quality/latency/cost/regression gates, and one held-out validation.
