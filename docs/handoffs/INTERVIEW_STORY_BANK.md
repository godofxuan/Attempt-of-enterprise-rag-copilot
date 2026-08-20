# Interview Story Bank

Each story is a factual decision narrative. Adapt emphasis to the question, but
do not change the dataset, denominator, evidence class, or decision.

Current state: `RAG_VNEXT_CLOSED` on `codex/agent-runtime-vnext`. Stories 1-8
retain the earlier retrieval/evaluation evidence; stories 9-13 explain the
later runtime mechanisms without converting them into quality claims.

## Story 1: Dense versus BM25

- **Situation:** Natural support questions often paraphrase help-center text.
- **Problem:** It was unclear whether lexical BM25 or semantic Dense retrieval was
  more suitable.
- **Hypothesis:** BGE-M3 Dense would recover paraphrased gold articles more often.
- **Experiment:** Fixed 200 WixQA ExpertWritten questions and compared BM25,
  Dense, and equal RRF under one retrieval protocol.
- **Result:** Recall@5 was 42.75% versus 66.42%; nDCG@5 was 32.15% versus 52.16%.
- **Decision:** Retain Dense as the measured champion for this cohort.
- **Trade-off:** Dense p95 was 157.41 ms versus BM25 151.80 ms and required an
  embedding index.
- **What I learned:** Retrieval choice must match query/document language, and
  quality plus latency matter more than a preferred technique.

## Story 2: why equal RRF was rejected

- **Situation:** Hybrid fusion is commonly recommended for RAG.
- **Problem:** Equal fusion can inject a weak arm's ranking into a stronger arm.
- **Hypothesis:** Equal RRF would combine lexical and semantic strengths.
- **Experiment:** Ran equal RRF on the exact same WixQA protocol.
- **Result:** Recall@5 was 59.25%, below Dense 66.42%; p95 rose to 304.64 ms from
  Dense 157.41 ms.
- **Decision:** Reject equal RRF instead of shipping it for architecture optics.
- **Trade-off:** A calibrated weighted fusion might behave differently, but it
  requires fresh development and held-out data.
- **What I learned:** A popular component is a hypothesis, not an improvement.

## Story 3: Evidence Ledger and grounding

- **Situation:** A model can answer fluently from partial or unauthorized context.
- **Problem:** Prompt instructions alone cannot prove source visibility or claim
  support.
- **Hypothesis:** Host-owned identity, ACL, evidence state, and citation filters
  would make failures explicit and fail closed.
- **Experiment:** Implemented typed controller/evidence transitions and regression
  tests across identity, retrieval ACL, Guard, and citation verification.
- **Result:** The mechanism passes the offline portfolio gate; no external answer-
  accuracy uplift is attached to this result.
- **Decision:** Keep authority in Python and keep semantic-quality claims separate.
- **Trade-off:** Deterministic checks can reject correct paraphrases and are not a
  semantic entailment oracle.
- **What I learned:** Security, completeness, and grounding are separate contracts.

## Story 4: Guard OFF versus ON

- **Situation:** Authorized retrieved documents can still contain indirect prompt
  injection instructions.
- **Problem:** ACL does not distinguish useful text from adversarial text.
- **Hypothesis:** A deterministic admission Guard would reduce attack/exposure
  events before content reached Agent state.
- **Experiment:** Frozen, counterbalanced OFF/ON comparison on a pinned garak
  subset with the same local model and retrieval inputs.
- **Result:** Attack success 4/12 to 0/12; context exposure 12/12 to 0/12; benign
  false positives 0/2; mean scan 1.42 ms.
- **Decision:** Keep Guard, but publish the small-denominator limitation.
- **Trade-off:** Strict patterns may overblock unseen benign content; two controls
  cannot estimate a general FPR.
- **What I learned:** Security claims require attack utility and benign utility.

## Story 5: FTS hard crash and activation

- **Situation:** A 511,962-row benchmark did not fit the planned in-memory BM25
  representation.
- **Problem:** A long build could be interrupted and must not expose partial data.
- **Hypothesis:** Disk-backed FTS5, resumable staging, immutable versions, and an
  atomic active pointer would make one-host operation recoverable.
- **Experiment:** Built the full index and injected 30 FTS process exits plus 12
  active-pointer exits.
- **Result:** 30/30 and 12/12 recovered with no mixed state or restart failure.
- **Decision:** Accept the single-writer offline builder contract.
- **Trade-off:** This is not distributed indexing, HA, or power-loss durability.
- **What I learned:** Atomic activation is a precise contract, not a synonym for
  production reliability.

## Story 6: multi-document 0/20

- **Situation:** The Agent cited no complete gold set on 20 multi-document cases.
- **Problem:** The final zero did not reveal where information was first lost.
- **Hypothesis:** Stage accounting plus oracles could localize acquisition versus
  selection failures.
- **Experiment:** Replayed Top-5/10/20, Guard admission, ledger, grounding, and a
  gold-retrieval oracle on the consumed cohort.
- **Result:** All-gold Top-5/10/20 completeness was 3/9/13; first loss was Top-20
  for 7, Top-5 for 10, and response selection for 3. Gold passed Guard 20/20 but
  final completeness remained 0/20.
- **Decision:** Do not blame the LLM or Guard; separately test acquisition and
  evidence-role selection.
- **Trade-off:** Oracle results diagnose capacity but cannot be resume quality.
- **What I learned:** One aggregate failure rate can hide multiple owners.

## Story 7: failure attribution discipline

- **Situation:** Adding a planner or rewrite looked like an obvious next step.
- **Problem:** Without first-loss evidence, a feature might target the wrong stage.
- **Hypothesis:** A bounded four-arm ablation could isolate decomposition from
  evidence selection.
- **Experiment:** Pre-registered current, decompose-only, select-only, and combined
  arms, fixed cost/security gates, and left production paths unchanged.
- **Result:** Decomposition changed Top-5 order in 7/20 but improved retrieval
  recall in 0 cases; selection improved citation recall in only one case.
- **Decision:** Reject this mechanism and stop tuning the consumed cohort.
- **Trade-off:** The negative result costs development time but avoids a weaker
  production path and preserves scientific credibility.
- **What I learned:** Attribution should determine what to build, not rationalize
  what was already built.

## Story 8: final candidate rejection

- **Situation:** The combined candidate selected more evidence and stayed within
  the 2x latency cap.
- **Problem:** Passing resource limits is insufficient if the quality objective is
  missed.
- **Hypothesis:** Clause decomposition plus selective evidence would produce at
  least three complete-case fixes and a 15pp completeness/recall gain.
- **Experiment:** Applied the frozen gate to 20 consumed development cases.
- **Result:** Complete-case fixes 0; completeness delta 0pp; recall +2.5pp;
  precision -5.83pp; p95 ratio 1.859x.
- **Decision:** `DEVELOPMENT_CANDIDATE_REJECTED`; no fixed validation or serving
  integration.
- **Trade-off:** Stopping leaves a known gap, but continuing on exposed labels
  would manufacture confidence rather than improve evidence.
- **What I learned:** A release gate must be able to say no after implementation.

## Story 9: replaceable runtime without duplicated authority

- **Situation:** The bounded Agent path worked, but framework-specific control
  flow made future migration and HITL hard to compare.
- **Problem:** Adding LangGraph could duplicate permission and publication logic.
- **Hypothesis:** One `AgentOrchestrator` contract could replace only orchestration
  while both implementations shared host-owned security boundaries.
- **Experiment:** Ran bounded and real LangGraph `StateGraph` adapters over five
  deterministic terminal/tool cases through the same `ToolGateway`.
- **Result:** Both arms passed 5/5 with behavioral parity and no permission
  violations; LangGraph added local orchestration overhead and no quality uplift.
- **Decision:** Keep bounded as default and LangGraph as an explicit alternative.
- **Trade-off:** The adapter layer adds code, but prevents framework lock-in and
  policy drift.
- **What I learned:** A framework migration is valuable when it preserves
  invariants, even when it does not improve model quality.

## Story 10: MCP interoperability behind ToolGateway

- **Situation:** Tools needed a standard interface without giving model-visible
  arguments direct authority.
- **Problem:** An MCP handler that queries storage directly could bypass ACL,
  budget, deadline, or retrieved-content admission.
- **Hypothesis:** An opaque server-issued context handle could connect MCP calls
  to the existing gateway without serializing identity or ACL scope.
- **Experiment:** Adapted typed `search/find/open` through the official MCP Python
  SDK and tested valid, invalid, expired, and revoked contexts.
- **Result:** Local/in-process calls used the same gateway and returned structured
  safe failures; no production network or OAuth path was built.
- **Decision:** Retain MCP as a protocol adapter, never as an authorization owner.
- **Trade-off:** Server-held handles need expiry and revocation state, but prevent
  caller-controlled scope expansion.
- **What I learned:** Interoperability and security are separate responsibilities.

## Story 11: trajectory versus ordinary logs

- **Situation:** Debug traces showed events but did not provide a stable integrity
  contract for replay or EvalOps.
- **Problem:** Reordering or editing a log line could change the story of a run.
- **Hypothesis:** Canonical semantic events linked by SHA-256 would make mutation
  detectable and deterministic replay possible without side effects.
- **Experiment:** Implemented event canonicalization, previous-hash links,
  append-only SQLite checks, tamper tests, and no-network replay.
- **Result:** A public 13-event sample verifies structurally and replays its
  recorded terminal facts; it is one mechanism sample, not WORM certification.
- **Decision:** Use trajectories as the canonical run record and keep operational
  logging as a separate concern.
- **Trade-off:** Hash links expose mutation but do not prevent an administrator
  replacing the complete local store.
- **What I learned:** Verifiable history is stronger than text logs but weaker
  than independently anchored audit storage.

## Story 12: retry-safe HITL without false durability claims

- **Situation:** Partial evidence sometimes requires a human publication decision.
- **Problem:** A review token could be replayed, used across tenants, or consumed
  before a transient publication failure was resolved.
- **Hypothesis:** Explicit pending/in-use/completed handling plus reviewer checks
  could make same-process resume single-use and retry-safe.
- **Experiment:** Tested accept/reject, wrong tenant and role, replay, concurrent
  resume, and a failure injected before completion.
- **Result:** Authorized decisions publish or reject once, and a handled failure
  can retry the token; process-restart recovery remains unimplemented.
- **Decision:** Document HITL as bounded same-process resume, not durable execution.
- **Trade-off:** In-memory state is simple and deterministic but cannot survive a
  crash or coordinate multiple workers.
- **What I learned:** Idempotency, authorization, and durability require separate
  evidence.

## Story 13: a versioned Agent artifact for EvalOps

- **Situation:** Evaluation consumers should not scrape private runtime objects or
  unstable logs.
- **Problem:** Without a schema, integrity and redaction rules drift between the
  Agent and evaluation layers.
- **Hypothesis:** A versioned artifact could expose only stable, verifiable run
  facts and fail closed when hashes or required fields change.
- **Experiment:** Defined `enterprise.agent-run/1.0`, generated a public sample,
  added schema/hash verification, and separated trajectory, retrieval, and answer
  metric semantics.
- **Result:** The sample is consumable and tamper-detecting; external platform
  adoption and answer correctness are not established.
- **Decision:** Treat the artifact as an integration contract, not an evaluation
  score or audit certification.
- **Trade-off:** Versioning creates migration work, but prevents log-format
  coupling and accidental claim inflation.
- **What I learned:** EvalOps begins with stable evidence contracts, not a larger
  dashboard or another Agent framework.
