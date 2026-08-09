# Correctness and Evidence Re-audit

## Frozen entry

- branch: `codex/rag-eval-system`;
- entry SHA: `cea80722191d20efa063cfbda972339c60324e5e`;
- worktree: clean at entry;
- product position: Enterprise Knowledge RAG / bounded Agent Copilot;
- CI at entry: `UNKNOWN_REMOTE_QUERY_UNAVAILABLE`;
- no reset and no user changes overwritten.

## Citation correctness

The citation verifier had a real asymmetric-negation bug. Plain affirmative
claims were assigned neutral polarity, so a claim/evidence pair differing only
by an explicit negation could pass the mismatch gate. The fix now compares
explicit negation only on relevant evidence sentences with compatible numeric
or date anchors, and supports English plus Chinese negative markers.

- implementation: `app/agent/citation_verifier.py`;
- tests: `tests/agent_v2/test_citation_verifier.py`;
- execution commit: `0848fc0`;
- result: 22 focused citation tests passed; layered Agent, FinQA, Guard/ACL, and
  domain/retrieval regressions passed.

This remains deterministic consistency checking, not semantic entailment.

## WixQA public evidence completeness

The frozen protocol required BM25, Dense, and equal RRF for all three cohorts.
The v1 public aggregate omitted BM25 and several metrics even though the private
summaries contained them. `scripts/publish_wixqa_retrieval_eval.py` now validates
the exact arm set, cohort identities, protocol hash, detail/summary hashes, and
complete metric fields before publishing v2.

- public evidence: `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json`;
- reproduction orchestrator: `scripts/reproduce_wixqa_retrieval.py`;
- tests: `tests/external_datasets/test_wixqa_public_evidence.py`;
- execution commit: `86b1844`;
- result: all protocol arms and fields are public; 16 focused tests passed.

The v2 aggregate is a deterministic republication of real historical private
summaries. A new clean-machine full live source/index/model replay was not run in
this sprint; it must not be claimed as completed.

## FTS activation correctness

The old builder verified staging and used atomic replacements, but two builders
could enter the same staging SQLite database. The second failed late on Windows
instead of being rejected before state mutation. A root-level exclusive build
lock now enforces one offline writer and records run/PID/token ownership. Only
the token owner releases the lock.

- implementation: `app/external_datasets/enterprise_rag_bench_fts.py`;
- tests: `tests/external_datasets/test_enterprise_rag_bench_fts.py`;
- contract: `docs/rapid_upgrade/02_FTS_ACTIVATION_CONTRACT.md`;
- execution commit: `7b1d3b3`;
- result: interruption, verification failure, path traversal, and concurrent
  second-writer contracts passed; indexing regression suite passed 124 tests.

## Claim matrix after re-audit

| Claim | Status |
|---|---|
| WixQA three-arm aggregate is complete and hash-bound | VERIFIED |
| Negation contradiction is rejected deterministically | VERIFIED |
| Enterprise FTS build/activation is single-writer and atomic | VERIFIED |
| New Agent external quality uplift | NOT VERIFIED / candidate held |
| Full Enterprise Dense retrieval quality | NOT RUN |
| Production traffic, SLO, or identity certification | NOT CLAIMED |
| Current exact-HEAD GitHub Actions | pending final push at this checkpoint |
