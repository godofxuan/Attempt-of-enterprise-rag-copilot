# Final Evidence Closure Index

| Artifact | Purpose | Status |
|---|---|---|
| `00_ENVIRONMENT_AND_BASELINE.md` | exact baseline and raw command outcomes | verified record |
| `01_GAP_AND_FIX_JOURNAL.md` | root causes, minimal repairs and limits | verified record |
| `02_LEARNING_GUIDE.md` | beginner-to-interview explanation | learning material |
| `evidence/fts_hard_crash_matrix_v1.json` | 10 kill points x 3 repetitions | PASSED, power loss NOT_RUN |
| `evidence/active_pointer_crash_matrix_v1.json` | 4 process-exit stages x 3 | PASSED, power loss NOT_RUN |
| `evidence/answer_citation_60_protocol_v1.json` | deterministic 40 single / 20 multi subset | FROZEN |
| `evidence/answer_citation_60_automated_v1.json` | retrospective retrieval/citation metrics | PARTIAL_AUTOMATED_ONLY |
| `evidence/guard_60_30_holdout_status_v1.json` | requested new security holdout gate | NOT_RUN |
| `evidence/rejected_experiments_v1.json` | machine-readable NO-GO registry | VERIFIED |
| `evidence/claim_audit_v1.json` | claim-to-evidence status | VERIFIED |
| `FINAL_EVIDENCE_CLOSURE_REPORT.md` | final A-L decision report | closeout |

Private raw logs are under `.private/final_evidence_closure/reproduction/` and
are intentionally excluded from Git because they include local absolute paths.
The public JSON files contain no prompts, answers, secrets or local paths.
