# Rapid Quality + Resume Release Final Report

## Executive result

Implementation/evidence base SHA: `49131de5f5b48718c72b06854cb424fcd8784a0c`.
Clean-reproduced release candidate SHA: `a3ef9c8`.
Remote-validated release payload SHA:
`68523e840a8f03b32d02ac78efd14af9889765ec`. Experiment metrics remain bound to
their individual execution SHAs.

Decision: `STOP FEATURE DEVELOPMENT`.

The repository already has three externally supported strengths: enterprise
support retrieval, 511,962-record data/index engineering, and limited external
retrieved-content security evidence. The new Agent candidate traded too much
precision for completeness and lacked fresh validation. Full Dense failed the
pre-registered rapid capacity/protocol gate. Adding a third rescue method would
reduce credibility rather than increase it.

## Required closeout answers

1. **Validated release payload.** Evidence/code base `49131de5...`; pushed
   payload `68523e8...` passed exact-SHA GitHub Actions Run `31316231539`.
2. **Did the P1 citation bug exist?** Yes. Affirmative/negative pairs could evade
   mismatch because affirmative polarity was treated as neutral.
3. **How was it fixed?** Relevant evidence sentences now undergo explicit
   negation comparison with numeric/date compatibility; English and Chinese
   regression cases cover both directions. Commit `0848fc0`.
4. **Is public evidence complete?** WixQA v2 now contains BM25, Dense, and equal
   RRF with the full frozen metric set for Synthetic, Simulated, and
   ExpertWritten, plus protocol/private hashes.
5. **Did clean reproduction succeed?** Yes for the public deterministic path: a
   detached clean worktree at `a3ef9c8` generated 240 source documents, dry-ran
   216 canonical/chunks, passed 214 focused tests, skipped one official-source
   reconstruction because WixQA raw data is not committed, and audited
   `1517/0`. A new
   clean-machine full
   WixQA raw/index/BGE-M3 replay is `NOT_RUN`; v2 is a verified republication of
   historical real private summaries.
6. **FTS activation contract.** `SINGLE_WRITER_OFFLINE_BUILDER` plus verified
   private staging, immutable version promotion, and atomic active-pointer
   replacement. Interrupted/failed builds cannot change active state.
7. **Was Fast Track run?** Yes, on 27 hash-bound WixQA Simulated multi-article
   cases marked retrospective development only.
8. **Multi-doc completeness before/after.** Required evidence and citation
   completeness `0.00% -> 22.22%`.
9. **Agent tool usage before/after.** Both arms used mean search/open/find
   `1/0/0`; candidate changed evidence aggregation only.
10. **Agent latency before/after.** p95 `531.77 -> 591.98 ms`, ratio `1.11x`.
11. **Fast Track decision.** Registered development gates pass, but citation
   precision falls `44.44% -> 18.52%`; status is
   `HOLD_NO_UNCONSUMED_VALIDATION / REVIEW_REQUIRED`, not promoted.
12. **Was Heavy Dense needed?** Capacity qualification was justified because
   Enterprise B0 has 153 zero-recall misses, including 80 semantic misses.
13. **Dense quality before/after.** `NOT_RUN`; no persistent full Dense index was
   built and no quality labels were consumed.
14. **Enterprise scale resource cost.** Existing FTS5: 511,962 records, 1.37 GiB,
   231.35 s build, about 1.83 GiB peak RSS. Dense qualification: 50k chunks in
   1,360.36 s at 36.755/s; full projection 12.87 h and about 12.99 GiB for a raw
   matrix plus flat-index copy before reserve.
15. **Security regression.** Guard/security tests are included in clean focused
   and final full gates; no Guard production logic changed in the quality
   experiment.
16. **ACL regression.** ACL pipeline tests passed in the clean focused gate;
   same ACL was held across Agent arms.
17. **CI.** Local final gate is `3174 passed / 29 skipped / 3 warnings`; public
   audit is `1517/0`. Exact-SHA remote payload gate is GitHub Actions Run
   `31316231539`, conclusion `success`.
18. **GitHub Actions jobs.** Ubuntu `93251819794`, Windows `93251819819`, and
   Linux container contract `93252615946` all concluded `success` for
   `68523e8...`.
19. **Pushed commits in this sprint.** Local milestone commits before final
   release: `0848fc0`, `86b1844`, `7b1d3b3`, `62522f6`, `7e050e4`, `49131de`.
20. **Strongest three resume metrics.** WixQA Dense improvement; EnterpriseRAG
   full lexical scale/build; garak Guard OFF/ON subset.
21. **New resume bullet.** Use the bullet pool; the recommended AI/RAG headline
   is WixQA Dense `42.75% -> 66.42%` Recall@5 and `32.15% -> 52.16%` nDCG@5 on
   200 authentic anonymized support questions.
22. **Forbidden claims.** No RAG accuracy 60.37%, Agent accuracy 99.5%, Agent
   uplift from the 27-case retrospective run, full Dense, full garak, universal
   safety, blind WixQA, production-ready, SOTA, SLA, or production traffic.
23. **Teaching handoff.** Updated
   `docs/learning/RAG_PROJECT_TEACHING_HANDOFF.md` with source/test/evidence links
   and the reasoning behind every sprint decision.
24. **Interview handoff.** Added `docs/learning/RAG_INTERVIEW_UPDATE.md` with 28
   high-probability questions and bounded answers.
25. **Continue or stop?** Stop feature development. Resume only with genuinely
   new business acceptance data or an independently held validation cohort.

## Final gate incident

The first sandboxed full-suite run ended with `3171 passed` plus one Windows
`PermissionError` when four spawned processes wrote the same computation-cache
lock file. The exact isolated test immediately passed in the default environment
and then passed `10/10` with non-sandboxed process permissions. The complete
non-sandboxed suite passed `3172 passed / 30 skipped / 3 warnings` in 177.06 s.
This is recorded as a transient Windows/sandbox handle event; no speculative
production fix was made without a reproducible code defect.

After the incident review, the public-CI compatibility pass removed a mandatory
module-import dependency on optional `pyarrow` and made raw WixQA cohort
reconstruction conditional on the separately downloaded official source. The
committed evidence contract remains mandatory in every clone. The resulting
full suite passed `3174 passed / 29 skipped / 3 warnings` in 191.90 s.

## Positive results and rejected candidates

| Track | Result | Decision |
|---|---|---|
| WixQA ExpertWritten Dense | Recall@5 66.42%, nDCG@5 52.16%, p95 157.4 ms on 200 | VERIFIED headline retrieval |
| Enterprise FTS5 | 511,962 records, 1.37 GiB, 231.35 s, about 1.83 GiB peak | VERIFIED scale/backend |
| garak subset Guard | ASR 4/12 to 0/12; exposure 12/12 to 0/12; 1.42 ms scan | VERIFIED_LIMITED security |
| Multi-source Agent candidate | completeness +22.22pp; precision -25.93pp | HELD / not resume-safe |
| Enterprise full Dense | 12.87 h projected; builder/protocol gates missing | FULL_DENSE_NO_GO |

## Interviewer scorecard

| Dimension | Score / 10 | Reason |
|---|---:|---|
| RAG | 8.5 | Strong external retrieval and failure analysis; answer quality is narrower |
| Agent mechanism | 8.0 | Typed bounded tools, evidence ledger, trace, Guard integration |
| Agent effect | 4.5 | Honest negative external result; no positive fresh validation |
| Data engineering | 9.0 | Full heterogeneous corpus, streaming profile, FTS5, atomic activation |
| Security | 8.0 | Identity/ACL/Guard and external subset; not production certification |
| Evaluation | 9.0 | Frozen protocols, consumption ledger, hashes, negative results, GO/NO-GO |
| Backend engineering | 8.5 | FastAPI, lifecycle, readiness, retries, traces, CI/container contracts |
| Reproducibility | 8.0 | Public aggregate evidence and quick clone gate; full external replay is costly |
| Resume value | 8.5 | Three distinct defensible bullets with exact evidence boundaries |
| Interview value | 9.0 | Rich tradeoffs, failures, correctness bugs, security and capacity reasoning |

## Evidence index

- `docs/rapid_upgrade/01_EVIDENCE_REAUDIT.md`
- `docs/rapid_upgrade/03_AGENT_FAST_TRACK.md`
- `docs/rapid_upgrade/04_DENSE_CAPACITY_RESULT.md`
- `docs/rapid_upgrade/evidence/MULTIDOC_FAST_TRACK_PUBLIC.json`
- `docs/rapid_upgrade/evidence/ENTERPRISE_DENSE_CAPACITY_PUBLIC.json`
- `docs/handoffs/RESUME_CODEX_UPDATE.md`
- `docs/handoffs/RAG_RESUME_BULLET_POOL.md`
- `docs/reproduction/QUICK_REPRODUCTION.md`
