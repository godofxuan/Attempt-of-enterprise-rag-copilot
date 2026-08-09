# Final Evidence Closure Report

Date: 2026-08-10

Decision: `PORTFOLIO_READY_STOP_DEVELOPMENT`. Production remains `NOT_CLAIMED`.

## 1. Final HEAD SHA

Verified release payload SHA:
`dad6336a3fb0094b625a4371bfbd716f2e67f93e`. This report is added by a following
metadata-only commit, so the final branch HEAD is reported separately in the
delivery message; metric artifacts and runtime code are unchanged.

## 2. Final GitHub Actions

Release payload GitHub Actions Run
[`31325310671`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/31325310671)
completed `success` for exact SHA `dad6336a...`: Ubuntu, Windows, and
`linux-container-contract` all passed. The metadata-only final HEAD run is
reported in the delivery message to avoid a self-referential commit loop.

## 3. Evidence consistency

Passed. `tests/test_final_closeout_evidence.py` reads source JSON rather than
copying rounded prose. It verifies 63 clean-replay comparisons, WixQA headline
values, Enterprise official/sensitivity metrics, current evidence links, 35
interview questions, and demo/teaching handoffs.

## 4. RESUME_SAFE_METRICS pointer

Fixed. `docs/enterprise_eval/RESUME_SAFE_METRICS.md` points to
`wixqa_retrieval_baseline_public_v2.json`; a regression test rejects the old v1
pointer.

## 5. Reused Source ID impact

The full 511,962-row corpus has 511,958 unique IDs: four reused-ID groups and
eight physical records. Only `qst_0413` among 470 retrieval-scored questions is
affected. Strict record identity changes that case Recall@5 from 1.0 to 0.5 and
Macro Recall@5 from 60.3741% to 60.2677%, a 0.1064 percentage-point reduction.
The latter is sensitivity, not a replacement benchmark score.

## 6. FTS5 single-writer contract

`SINGLE_WRITER_OFFLINE_BUILDER` plus `ATOMIC_ACTIVATION`. It supports metadata-
bound resume, verified staging, integrity/count/hash checks, immutable versions,
fail-fast second writer, and atomic active pointer. It does not claim distributed
locking, online concurrent writes, HA, or a production multi-writer service.

## 7. WixQA clean reproduction

Succeeded. Official data was downloaded into a previously absent root. A new
BGE-M3 cache and index were built for 6,221 articles / 11,975 chunks, followed
by Synthetic 6,221, Simulated 200, and ExpertWritten 200 evaluations. Historical
private artifacts were not inputs.

## 8. Before/after metric comparison

All three arms, three cohorts, and seven frozen quality metrics matched exactly
at absolute tolerance 0. ExpertWritten Dense remained Recall@5 66.4167% and
nDCG@5 52.1583%. Historical versus candidate Dense p95 was 157.406 versus
153.559 ms; latency is machine-specific and is not claimed as an optimization.

## 9. Reproduction gap

No quality gap. Attempt 1 is retained as a transport-identity failure: historical
question JSONL used CRLF while official direct files used LF. Canonical JSON rows
and derived IDs matched. Protocol v2 changed only the bound official transport
manifest before quality was observed; model, data semantics, retrieval settings,
metrics, and zero tolerance remained frozen.

## 10. New Agent experiment

Not run.

## 11. Why no Agent rerun

Neither allowed trigger existed: no genuinely new unconsumed multi-document
enterprise validation set and no recurring real-user failure pattern. Reusing
consumed labels would not produce independent evidence. The sprint goal was
evidence closure, not another feature or retrospective tuning cycle.

## 12. Agent effect status

`REJECTED`. The existing external paired route used one search, zero find/open,
did not improve retrieval, had zero multi-article citation completeness, and
added latency. A separate 27-case retrospective candidate remains HOLD because
completeness improved while precision regressed and no fresh validation exists.

## 13. Full Dense status

`FULL_DENSE_NO_GO / QUALITY_NOT_RUN`. The 50k capacity qualification projects
12.87 hours, but resumable sharding and a fresh independent quality protocol are
absent. No persistent full Dense artifact was built.

## 14. Security status

`VERIFIED_LIMITED`. Guard OFF/ON on the pinned garak subset changed ASR 4/12 to
0/12 and context exposure 12/12 to 0/12 at 1.42 ms mean scan. This is narrow
external-probe evidence, not full garak, universal safety, or production red team.

## 15. Production status

`NOT_CLAIMED`. Missing evidence includes real IdP/KMS, production data owners,
online index operations, traffic/SLO/alerts, HA/backup restore, independent
security assessment, privacy/compliance sign-off, and human answer/citation
acceptance.

## 16. README changes

The first screen now leads with three measured results and boundaries, links the
clean replay and reused-ID sensitivity, states the stop-development posture, and
keeps rejected Agent/RRF evidence visible. Retrieval remains clearly separated
from answer accuracy.

## 17. PROJECT_STATUS changes

The root status gained the 2026-08-10 closeout timeline. The older
`docs/PROJECT_STATUS.md` remains explicitly labeled a historical snapshot and
links to the root, preserving the repository's single-current-status contract.

## 18. Demo readiness

Interview ready. `docs/demo/INTERVIEW_DEMO_RUNBOOK.md` provides 10-minute and
20-minute flows plus an offline failure-safe path using screenshots, public JSON,
focused tests, and audit results. It does not depend on the 511k corpus.

## 19. Resume Codex sync

`RESUME_CODEX_UPDATE.md` now includes release identity, top claims with metric,
dataset, denominator, class, execution SHA, evidence and limitation; rejected,
historical, NOT_RUN, and forbidden claims are retained for generation safety.
`RAG_RESUME_BULLET_POOL.md` contains 5 AI/RAG, 4 backend, and 4 bank/SOE bilingual
candidates.

## 20. Actual three resume versions

Synchronized without overwriting old finals. New Markdown sources were created
in the existing private resume workspace: AI/RAG V1.4, Python Backend V1.5, and
Bank/SOE IT V1.5, plus a changelog. Only this project's bullets, supported skills,
and GitHub link changed. DOCX/PDF rendering and owner review remain user-owned.

## 21. Teaching handoff

Added a full final-evidence lesson covering clean roots, identity binding,
quality versus latency, CRLF/LF transport semantics, business versus physical ID,
source/tests/experiment, design alternatives, trade-offs, mistakes, interview
questions, and five exercises.

## 22. Interview handoff

Expanded from 28 to 35 fact-based questions with category index. New coverage
includes MCP, JWT/RS256/JWKS, clean reproduction, transport failure, reused-ID
sensitivity, production gap, and exact-SHA CI semantics.

## 23. Public repository audit

Final configured audit: `1539 candidates / 0 findings`. One initial absolute-
path finding in public replay metadata was fixed by allowlisted projection and
repository-local root classes.

## 24. Secret audit

Passed under `scripts.audit_public_repo`: no tracked private keys, JWT/credential
tokens, `.env`, private run paths, or non-example organization email. This is a
configured static audit, not a formal legal or secret-scanner certification.

## 25. Large-file audit

Passed. Largest tracked file observed: 1,914,251 bytes. Large raw datasets,
indexes, embedding/model caches, detailed runs, keys, and private resume outputs
remain untracked/ignored.

## 26. Strongest three resume metrics

1. WixQA ExpertWritten Dense Recall@5 66.42% versus BM25 42.75%; nDCG@5 52.16%
   versus 32.15%; 200 questions.
2. EnterpriseRAG FTS5: 511,962 rows / 9 sources / 1.37 GiB / 231.35 s / about
   1.83 GiB peak RSS.
3. Pinned garak subset: Guard ASR 4/12 to 0/12 and exposure 12/12 to 0/12;
   1.42 ms mean scan.

## 27. Strongest three AI/RAG bullets

1. WixQA Dense versus BM25 external retrieval with quality and latency.
2. Hash-bound clean replay with 11,975 rebuilt chunks and 63/63 exact metrics.
3. Host-owned bounded Agent/ACL/Guard/evidence/citation system, using the limited
   garak positive result but not claiming Agent quality uplift.

## 28. Strongest two backend bullets

1. Replace 36.60 GiB estimated in-memory BM25 with measured 1.37 GiB resumable
   FTS5 over 511,962 rows at about 1.83 GiB peak RSS.
2. Single-writer verified staging and atomic activation with interruption,
   verification-failure, concurrency, path, and active-version tests.

## 29. Forbidden claims

RAG/system/answer accuracy 60.37% or 66.42%; blind WixQA; independent third-party
reproduction; Agent quality improvement; full Enterprise Dense/RRF/Agent;
production-ready/SLO/QPS; real IdP; distributed multi-writer FTS; full garak;
100% safe; SOTA; GraphRAG; MCP capability; or any NOT_RUN feature.

## 30. Continue feature development?

No. Stop feature development. Resume Agent work only with new unconsumed
multi-document validation or recurring real-user failures. Resume full Dense
only when hardware, resumable sharding, and fresh quality protocol all exist.
Otherwise spend effort on code study, demo practice, interview explanation, and
job-specific resume selection.

## Local validation record

- Dependency check: no broken requirements
- Compileall: passed
- Focused closeout: 26 passed
- First full run: 3182 passed / 29 skipped, plus two document-contract failures
- Repairs: restore root-only current status contract; preserve exact legacy
  `检索 Recall@5` phrase in evidence map
- Final full run: 3184 passed / 29 skipped / 3 known SWIG warnings in 202.82 s
- Public audit: 1539 candidates / 0 findings
- Release payload CI: Run 31325310671, Ubuntu/Windows/Linux-container success

See `04_FINAL_SCORECARD.md` for the 13-dimension assessment.
