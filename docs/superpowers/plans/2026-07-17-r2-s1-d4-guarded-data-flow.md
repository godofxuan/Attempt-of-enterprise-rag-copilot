# R2-S1 D4 Guarded Data Flow and Capability Constraints Plan

> **For agentic workers:** Execute task by task with strict RED -> GREEN -> REFACTOR. Do not start D5 prompt-boundary or public-trace work in this phase.

**Goal:** Make the D3 retrieved-content Guard mandatory on every V2 `search/find/open` data path, allow only admitted typed evidence into Controller state and the evidence ledger, recover clean lower-ranked candidates with one bounded top-up, and return an explicit source-free `security_filtered/evidence_filtered` outcome when all usable content is quarantined.

**Architecture:** Retrieval exposes one ACL-filtered ranked pool of at most `candidate_k` without rerunning ranking. A dedicated admission service scans all prompt-reachable text and metadata, applies parent fallback and bounded same-document split checks, and returns discriminated admitted payloads or content-free quarantine summaries. `V2ToolRegistry` becomes the mandatory enforcement point and returns only `GuardedV2ToolExecution`; `Controller.observe()` rejects the old raw execution type at runtime. Context budget counts admitted text only, while separate security counters account for scanned/quarantined material.

**Tech Stack:** Python 3.11, Pydantic 2, pytest 9, existing deterministic `RetrievedContentGuard`, existing V2 retrieval/controller stack.

## Global Constraints

- Preserve ACL and metadata filtering before Guard scanning.
- Scan at most the existing `candidate_k` pool once; never re-embed, broaden ACL, or loop retrieval.
- Treat body, parent context, title, version, section/source metadata, find previews, and open content as untrusted.
- Quarantined payloads must never carry original, normalized, decoded, title/path, or preview text downstream.
- A per-item Guard error quarantines that item and continues; an unavailable/invalid Guard fails the execution closed as `system/system_error`.
- Apply diversity limits only to admitted candidates. Quarantine must not consume a `top_k` or per-document slot.
- Split aggregation is same-document, adjacent, at most 3 fragments, within the 20,000-character raw scan bound, and at most 12,000 NFKC/casefold-normalized characters. A risky aggregate quarantines every contributor.
- `search/find/open` remain the complete read-only tool allowlist. `open` accepts only typed index IDs, never URLs or filesystem paths.
- Count only admitted text toward `BudgetState.context_chars`; keep scanned-character accounting separate.
- Do not add D5 nonce delimiters, prompt instructions, API security trace fields, or live-model evaluation.
- Do not edit the frozen R1 evaluation corpus.

---

### Task 1: Guarded Domain Contracts

**Files:**
- Modify: `app/domain/retrieved_security.py`
- Modify: `app/domain/agent.py`
- Modify: `app/domain/evidence.py`
- Create: `tests/domain_v2/test_guarded_retrieval_contracts.py`

- [x] Write schema tests for `AdmittedEvidenceChunk`, admitted find/open payloads, `QuarantineSummary`, `SecurityCounters`, and `GuardedV2ToolExecution`.
- [x] Verify RED because guarded payload types and `security_filtered/evidence_filtered` do not exist.
- [x] Implement strict frozen models whose validators reject raw/quarantined content in admitted slots, content fields in summaries, inconsistent counters, and mismatched tool/payload pairs.
- [x] Add `security_filtered` to `AnswerMode`, `evidence_filtered` to `AgentStopReason`, and enforce source-free answers for this mode.
- [x] Bump detector policy to `rcg-v1.1.0`, add the stable adjacent-split rule, and refresh provenance because split aggregation changes detector behavior.
- [x] Verify the focused contract suite GREEN.

### Task 2: Ranked Candidate Pool Before Top-K Truncation

**Files:**
- Modify: `app/retrieval/pipeline.py`
- Modify: `app/retrieval/navigation.py`
- Modify: `tests/v2_test_support.py`
- Create: `tests/retrieval/test_guarded_candidate_pool.py`

- [x] Write tests proving the internal secure path returns ACL-visible candidates in deterministic rank order up to `candidate_k`, while public `search()` still returns its existing diverse `top_k` result.
- [x] Verify RED because no ranked-pool method exists.
- [x] Extract ranking into a strict internal `RankedSearchPool`; make public `search()` project its existing behavior from that pool.
- [x] Add `DocumentNavigator.search_ranked()` and a deterministic fake implementation for unit tests.
- [x] Verify no second embedding/ranking call occurs during top-up and existing retrieval tests remain GREEN.

### Task 3: Admission, Parent Fallback, Metadata, and Split Payloads

**Files:**
- Create: `app/security/retrieved_admission.py`
- Create: `tests/security/test_retrieved_admission.py`

- [x] Write RED tests for clean admission, body quarantine, poisoned title/metadata, risky parent with clean-child fallback, find preview, open content, per-item Guard error, all-filtered outcome, and clean lower-rank recovery.
- [x] Write RED split tests for two/three adjacent fragments, cross-document non-combination, non-adjacent non-combination, and the 12,000-character bound.
- [x] Implement deterministic field scanning and content-free summaries. A distinct risky parent is dropped while an independently clean child may be admitted child-only.
- [x] Implement one pass through the existing ranked pool. Record `top_up_attempts=1` only when scanning beyond the initial `top_k` ranked positions was needed.
- [x] Run bounded same-document adjacent-window checks before final admission; quarantine all contributors to a risky aggregate and continue through the same pool.
- [x] Verify focused admission tests GREEN and serialized guarded outputs contain no attack canary.

### Task 4: Mandatory Guarded Tool Registry and Capability Boundary

**Files:**
- Modify: `app/agent/tools_v2.py`
- Modify: `tests/agent_v2/test_tools_v2.py`
- Create: `tests/agent_v2/test_guarded_tool_boundary.py`

- [x] Write RED tests showing registry output is guarded for all three tools, context budget counts admitted text only, all-filtered search carries `evidence_filtered`, invalid Guard initialization fails closed, and no raw fallback is used.
- [x] Add bypass tests showing terminal/arbitrary tool names are rejected, attacker URLs remain inert strings, and `open` resolves only typed index identifiers without network/filesystem access.
- [x] Keep `V2ToolExecution` only as an explicitly raw internal/negative-test type; make public `V2ToolRegistry.run()` return `GuardedV2ToolExecution` exclusively.
- [x] Apply Guard before visible/context accounting and preserve existing call/deadline budgets, including post-Guard deadline checks.
- [x] Verify tool suites GREEN with network transports monkeypatched to fail on any attempted egress.

### Task 5: Controller, Ledger, Generation, and Runner Type Boundary

**Files:**
- Modify: `app/agent/controller_v2.py`
- Modify: `app/agent/evidence_ledger.py`
- Modify: `app/agent/evidence_relevance.py`
- Modify: `app/agent/citation_verifier.py`
- Modify: `app/agent/generation_v2.py`
- Modify: `app/agent/runner_v2.py`
- Modify: `tests/agent_v2/test_controller_v2.py`
- Modify: `tests/agent_v2/test_runner_v2.py`
- Modify: `tests/security/test_indirect_injection_red_baseline.py`
- Modify: `tests/retrieval/test_indirect_injection_red_baseline.py`

- [x] Rewrite the D2 red cases as D4 enforcement regressions and first verify that raw executions/state still cross the current boundary or fail for the expected missing guarded types.
- [x] Make `ControllerState`, relevance checks, and `EvidenceLedger` accept admitted wrappers only; unwrap content only inside trusted downstream projection helpers.
- [x] Make `Controller.observe()` perform an explicit runtime guarded-type check and raise `TypeError` for raw `V2ToolExecution`, even if its payload happens to be clean.
- [x] Map candidates-present-but-all-quarantined to source-free `security_filtered/evidence_filtered`; preserve `not_found`, `permission`, budget, partial, and system semantics otherwise.
- [x] Ensure Runner treats a custom raw/bypass registry as a source-free system error and never silently invokes a legacy path.
- [x] Verify all eight D2 boundary/top-rank cases GREEN and all existing V2 API/agent regressions GREEN.

### Task 6: D4 Verification and Evidence Closeout

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/security/r2_s1/03_detailed_design.md`
- Modify: `docs/security/r2_s1/05_results.md`
- Modify: `docs/roadmap/r2_s1_indirect_injection_implementation.md`
- Modify: `docs/architecture.md`
- Modify: `docs/known_limitations.md`
- Modify: `docs/security_threat_model.md`
- Modify: `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`
- Modify: `docs/roadmap/engineering_decision_failure_ledger.md`
- Create: `docs/security/r2_s1/06_d4_engineering_journal.md`

- [x] Run focused contract, retrieval, admission, tool, controller, runner, D2 regression, R1 API, full offline suite, and public-repository audit commands.
- [x] Recheck frozen R1 file hashes, `git diff --check`, no unexpected network/model process, and no raw/canary text in guarded serialization.
- [x] Complete independent read-only security review, reproduce all 2 Critical + 6 Important findings as RED tests, and turn the corrected focused batch GREEN.
- [x] Record exact commands/counts, changed files, design reasoning, problems encountered, fixes, remaining limitations, and interview-ready explanations.
- [x] State accurately: D4 runtime Guard enforcement is implemented and deterministically tested; D5 prompt boundary/public security trace and D6 evaluation remain NOT RUN.
- [x] Commit only D4-owned files locally with `feat: enforce guarded retrieved-content boundary`; do not stage `.superpowers/`, private output, frozen evaluation data, or unrelated files; do not push.
- [x] Stop at the D5 approval gate.
