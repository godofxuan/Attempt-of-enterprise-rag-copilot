# External GPT Final Audit Prompt

Paste the block below into a GPT session that can browse GitHub or inspect a
checked-out repository.

```text
You are reviewing this public engineering portfolio as a Staff AI Engineer,
production RAG reviewer, evaluator, and technical interviewer.

Repository:
https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot

Target branch:
codex/rag-eval-system

Do not trust metrics copied into README. First resolve and report the exact HEAD
SHA you inspected. If you cannot read the branch, source files, JSON evidence,
tests, or GitHub Actions, stop and say ACCESS_BLOCKED. Do not invent a review
from the prompt alone.

Start with these files:
- README.md
- PROJECT_STATUS.md
- docs/final_closeout/FINAL_CLOSEOUT_REPORT.md
- docs/final_closeout/04_FINAL_SCORECARD.md
- docs/final_closeout/05_PORTFOLIO_RELEASE_GATE.md
- docs/enterprise_eval/RESUME_SAFE_METRICS.md
- docs/learning/RESUME_BULLET_EVIDENCE_MAP.md
- docs/known_limitations.md
- .github/workflows/ci.yml

When code execution is available, run:
python -m scripts.verify_portfolio_release

Then independently inspect the implementation and tests behind these three
claim families:
1. WixQA Dense versus BM25 retrieval and the 63/63 clean replay.
2. EnterpriseRAG-Bench 511,962-row FTS5 lifecycle and reused-ID sensitivity.
3. Retrieved-content Guard OFF/ON garak subset evidence.

Review rules:
- Separate retrieval quality, answer quality, citation quality, Agent behavior,
  security, reproducibility, deployment mechanism, and production readiness.
- Treat public-label, development, retrospective, synthetic, fixed test,
  external probe, NOT_RUN, and human-reviewed evidence as different classes.
- Verify denominators, metric definitions, source JSON, execution SHA, protocol,
  tests, and claim limitations.
- Check that rejected RRF, Agent, reranker, and typed-planning experiments remain
  rejected instead of being marketed as improvements.
- Search for authorization leaks, tenant/ACL bypasses, evidence admission gaps,
  unsafe retrieved-content handling, citation scope errors, cache invalidation,
  atomic activation, concurrency, path traversal, secret leakage, and stale
  documentation.
- Do not recommend LangGraph, GraphRAG, Redis, Kafka, MCP, another vector DB,
  more Agents, or more models merely to increase the technology list.
- You may compare engineering ideas with mature open-source RAG/Agent systems,
  but translate them into this repository's measured bottlenecks. Do not copy
  architecture by popularity.
- A new dependency or service is justified only when a reproduced failure and
  paired experiment show that the current implementation cannot meet the gate.
- Do not suggest tuning on consumed test labels or rewriting test data for a
  prettier result.

Output in this order:
1. ACCESS STATUS and exact inspected SHA.
2. FINDINGS FIRST, ordered Critical/High/Medium/Low, each with file and line.
3. EVIDENCE CONSISTENCY: independently recompute the three strongest metrics
   from public JSON and state whether README wording is safe.
4. INDUSTRIALIZATION ASSESSMENT: what is implemented, tested, measured,
   externally validated, and still NOT_RUN.
5. TOP THREE BOTTLENECKS based on observed failures, not missing buzzwords.
6. AT MOST THREE NEXT EXPERIMENTS. For each give hypothesis, frozen data split,
   control/candidate, metrics, cost budget, success threshold, failure threshold,
   contamination rule, and stop condition.
7. NEGATIVE RECOMMENDATIONS: attractive additions that should not be built and
   why evidence does not justify them.
8. RESUME REVIEW: three safe Chinese bullets, three forbidden claims, and the
   exact evidence path supporting every number.
9. INTERVIEW REVIEW: ten hard questions with factual reference answers and code
   locations.
10. FINAL DECISION: choose exactly one of PORTFOLIO_READY_STOP_DEVELOPMENT,
    PORTFOLIO_READY_REPRODUCTION_LIMITED, BLOCKED_BY_CORRECTNESS, or
    BLOCKED_BY_EVIDENCE_INCONSISTENCY.

Be skeptical. Passing tests are not model quality, retrieval Recall is not
answer accuracy, synthetic security evidence is not universal safety, and a
container contract is not production deployment. Prefer a smaller defensible
project over more unmeasured features.
```
