# Teaching Codex Handoff

This is the single entry point for any Codex task that teaches this project.
Do not summarize the README and call that teaching. Read the evidence map first,
then use the existing detailed chapters listed below. Do not change project
facts to make an explanation easier.

Canonical base branch/state: `codex/agent-runtime-vnext` / `RAG_VNEXT_CLOSED`.
Current durable integrity overlay:
`codex/durable-runtime-integrity-fix-v1`. For this overlay, read
`docs/review/P1_INTEGRITY_FIX_REPORT.md` before tutorial section 9; teach the
CAS/lease/fencing state machine, local transaction boundary, outbox projection,
and upgrade migration without turning them into a general durable-runtime claim.
This is portfolio-ready teaching material, not proof of production readiness.
Teaching may use consumed cases for historical analysis, but must never rename
them as blind validation. Runtime mechanisms also must not be presented as
answer-quality improvements.

## Required reading order

1. `docs/handoffs/PROJECT_EVIDENCE_MAP.md`
2. `docs/learning/RAG_PROJECT_TEACHING_HANDOFF.md`
3. `docs/learning/AGENT_RUNTIME_TUTORIAL.md`
4. `docs/agent_runtime/10_FINAL_ARCHITECTURE.md`
5. `docs/agent_runtime/09_SECURITY_REVIEW.md`
6. `docs/agent_runtime/08_AB_EVALUATION.md`
7. `docs/resume/RESUME_SAFE_VNEXT_METRICS.md`
8. `docs/handoffs/INTERVIEW_STORY_BANK.md`
9. `docs/multidoc_attribution/03_LEARNING_GUIDE.md` (historical diagnosis)
10. `docs/multidoc_candidate/04_LEARNING_AND_INTERVIEW_GUIDE.md` (historical rejection)
11. `docs/final_evidence_closure/02_LEARNING_GUIDE.md`
12. `docs/learning/RAG_INTERVIEW_UPDATE.md`

## Teaching contract

For every module, teach in this order:

1. explain the prerequisite concept in plain language;
2. trace one concrete request through real source files;
3. explain why the current design exists;
4. compare at least one reasonable alternative;
5. state the trade-off and failure mode;
6. use one real project result, including a failure where relevant;
7. ask one interview question;
8. give a fact-bounded reference answer;
9. ask one deeper follow-up;
10. require the learner to answer again without reading the reference answer.

## Module 1: RAG from first principles to this repository

- **Foundation:** `query -> retrieval candidates -> admitted evidence -> answer
  claims -> citations`. Retrieval decides what may be available; generation
  decides how to express it; citation checks whether published claims retain a
  visible evidence link.
- **Source trace:** `app/agent/runner_v2.py` orchestrates;
  `app/retrieval/pipeline.py` retrieves and filters;
  `app/agent/controller_v2.py` tracks required aspects and evidence;
  `app/agent/citation_verifier.py` checks candidate claims.
- **Design reason:** each stage has a different correctness boundary and must be
  measured separately.
- **Alternative:** a single prompt with pasted Top-K context is simpler but
  cannot independently expose retrieval, permission, admission, or grounding
  failures.
- **Trade-off:** more explicit stages increase code and test volume but make
  failures attributable.
- **Real result:** WixQA Dense Recall@5 66.42% is retrieval quality, not answer
  accuracy.
- **Interview question:** Why can a high Recall@5 system still give a wrong
  answer?
- **Reference answer:** the correct source may be present while the generator
  omits it, misreads it, combines facts incorrectly, or cites an unsupported
  claim.
- **Follow-up:** Which metric would you add for each downstream failure?
- **Learner answer target:** name retrieval recall, required-evidence
  completeness, answer correctness, citation precision/recall, and unsupported
  claim rate without treating them as synonyms.
- **Code/test exercise:** trace one `answer_question` fixture from retrieval to
  citation filtering, then add an assertion that distinguishes a retrieved gold
  source from a supported published claim.

## Module 2: BM25, Dense, RRF, Recall and nDCG

- **Foundation:** BM25 rewards lexical term evidence; Dense compares learned
  vector similarity; RRF combines rank positions without understanding scores.
- **Source trace:** `app/external_datasets/wixqa_retrieval.py` and
  `scripts/eval_wixqa_retrieval.py`.
- **Design reason:** all arms use the same dataset, chunks, IDs, Top-K, and metric
  definitions so the retrieval method is the intended variable.
- **Alternative:** cross-encoder reranking may improve ordering but cannot recover
  a document absent from its candidate pool and adds latency.
- **Trade-off:** Dense used more latency than BM25 but gained quality; equal RRF
  spent still more latency while losing quality relative to Dense.
- **Real result:** Recall@5 BM25/Dense/equal-RRF was
  42.75%/66.42%/59.25%; nDCG@5 32.15%/52.16%/47.16%.
- **Interview question:** Why did RRF regress even though fusion is often useful?
- **Reference answer:** equal RRF assumed equally useful arms; weak high-ranked
  BM25 candidates displaced Dense candidates, and rank-only fusion had no
  calibrated evidence that BM25 deserved equal weight.
- **Follow-up:** How would you retest a weighted fusion without leaking labels?
- **Learner answer target:** tune only on a development split, freeze one
  candidate, then evaluate once on a disjoint held-out cohort with quality and
  latency gates.
- **Code/test exercise:** use the checked-in WixQA fixture to calculate one
  Recall@5 and one nDCG@5 value by hand, then match the evaluator output.

## Module 3: evidence-controlled RAG

- **Foundation:** identity answers "who"; ACL answers "what may this principal
  see"; retrieved-content admission answers "what content may enter Agent
  state"; the ledger answers "which required facts are supported"; the grounding
  gate answers "which claims may be published".
- **Source trace:** `app/api/identity.py`, `app/security/access.py`,
  `app/retrieval/pipeline.py`, `app/security/retrieved_content.py`,
  `app/agent/controller_v2.py`, and `app/agent/citation_verifier.py`.
- **Design reason:** model text cannot be an authorization or release authority.
- **Alternative:** prompt-only instructions are easier but retrieved documents
  can contain adversarial instructions and a model can ignore policy wording.
- **Trade-off:** deterministic gates are reproducible and fail closed, but may
  reject valid paraphrases and do not prove semantic entailment.
- **Real failure:** the project explicitly does not claim semantic citation
  correctness or hallucination immunity.
- **Interview question:** What does ACL solve that a grounding gate does not?
- **Reference answer:** ACL prevents unauthorized evidence from entering the
  visible path; grounding checks support among already visible evidence. A
  grounded answer can still leak data if visibility was wrong.
- **Follow-up:** Why must ACL also apply before parent expansion and citation
  output?
- **Learner answer target:** identify every place an unauthorized source could be
  reintroduced after initial retrieval.
- **Code/test exercise:** add a regression fixture in which parent expansion
  finds an unauthorized source and verify it never reaches evidence or citation.

## Module 4: bounded Agent controller

- **Foundation:** the query analyzer emits intent and required aspects; the
  controller chooses typed tool actions; budgets and stop rules bound execution;
  observations update the evidence ledger.
- **Source trace:** `app/agent/query_analysis.py`,
  `app/agent/controller_v2.py`, `app/agent/tools.py`, and
  `app/agent/runner_v2.py`.
- **Design reason:** explicit state makes action sequence, tool errors, budget
  exhaustion, and terminal reasons testable.
- **Alternative:** an open-ended LLM planner is more flexible but harder to
  authorize, reproduce, and bound.
- **Trade-off:** the bounded controller is safer and easier to evaluate, but the
  current default may under-explore and does not automatically rewrite/retry.
- **Real failure:** the paired WixQA route used search once and find/open zero
  times, gave no retrieval gain, and added latency.
- **Interview question:** Why is this an Agent if the current candidate was
  rejected?
- **Reference answer:** Agent describes the decision-and-tool mechanism; quality
  improvement is a separate empirical claim. The mechanism exists, while this
  external route failed its adoption gate.
- **Follow-up:** What evidence would justify enabling one retry?
- **Learner answer target:** name a pre-registered failure subset, fresh data,
  bounded cost, paired OFF/ON quality, latency, tool-step, and regression gates.
- **Code/test exercise:** lower a tool budget in a controller fixture and assert
  the exact terminal reason and recorded step count.

## Module 5: multi-document failure attribution

- **Foundation:** finding any one gold source differs from finding every required
  source. Per-question recall can be partial while all-gold completeness remains
  zero.
- **Source trace:** `app/evaluation/wixqa_multidoc_attribution.py` and
  `app/evaluation/wixqa_multidoc_candidate.py`.
- **Design reason:** stage accounting localizes first loss to Top-20 acquisition,
  Top-5 ordering, Guard/admission, evidence representation, or final selection.
- **Alternative:** inspecting only the final answer cannot distinguish a missing
  candidate from a generation omission.
- **Trade-off:** oracle probes reveal capacity but cannot be quoted as real
  quality because they inject gold information.
- **Real result:** among 20 consumed cases, all-gold Top-5/10/20 completeness was
  3/9/13; first loss was Top-20 for 7, Top-5 for 10, and response selection for
  3. The later candidate produced zero paired complete-case fixes.
- **Interview question:** Why was the candidate rejected despite citation recall
  rising 2.5 percentage points?
- **Reference answer:** the pre-registered objective was complete evidence, not a
  small partial-recall movement; completeness stayed 0%, precision fell 5.83pp,
  p95 rose 1.86x, and no case changed from incomplete to complete.
- **Follow-up:** Why can those 20 cases no longer be a blind test?
- **Learner answer target:** explain label/result exposure, adaptive tuning, test
  contamination, and the need for a new independently frozen cohort.
- **Code/test exercise:** classify three fixture failures by first-loss stage and
  verify an oracle case is excluded from headline quality aggregation.

## Module 6: RAG security

- **Foundation:** trusted identity and ACL constrain principals; retrieved-content
  injection defense treats documents as untrusted data; Guard OFF/ON measures
  the boundary; benign utility detects overblocking.
- **Source trace:** `app/security/identity.py`,
  `app/security/retrieved_content.py`, and
  `app/evaluation/garak_latent_report_eval.py`.
- **Design reason:** a source can be authorized yet malicious, so ACL and content
  admission solve different threats.
- **Alternative:** asking the LLM to ignore document instructions remains inside
  the attacked trust domain.
- **Trade-off:** strict scanning reduces measured attacks but can quarantine
  benign content; that cost needs a realistic benign denominator.
- **Real result:** one pinned garak subset changed ASR 4/12 to 0/12 and exposure
  12/12 to 0/12, with 0/2 benign quarantines and 1.42 ms mean scan.
- **Interview question:** Why is that not proof of universal security?
- **Reference answer:** it covers 12 attacks from one probe subset, one model and
  one protocol; evasion families, real traffic, a precise FPR, red-team review,
  and production containment remain unmeasured.
- **Follow-up:** What would an independent security holdout require?
- **Learner answer target:** freeze new attack families before guard changes,
  isolate fixtures, hold model/retrieval constant, report ASR, exposure, benign
  utility, latency, and human review.
- **Code/test exercise:** add one malicious and one similar benign retrieved
  fragment, then assert Guard admission and the reason code for each.

## Module 7: reliability and activation

- **Foundation:** staging isolates incomplete builds; resumability reuses verified
  progress; immutable targets prevent in-place corruption; an active pointer
  selects one complete version; rollback changes that pointer to a prior target.
- **Source trace:** `app/external_datasets/enterprise_rag_bench_fts.py`,
  `app/indexing/store.py`, and `app/indexing/incremental_snapshot.py`.
- **Design reason:** readers should see either the old complete index or the new
  complete index, never half of both.
- **Alternative:** overwrite one live directory in place is simpler but exposes
  mixed state after interruption.
- **Trade-off:** immutable versions consume additional disk and require explicit
  retention, but simplify verification and rollback.
- **Real result:** FTS hard exits passed 30/30 and active-pointer exits 12/12 with
  zero mixed state or restart failures.
- **Interview question:** What is the difference between process crash, atomic
  rename, and power-loss durability?
- **Reference answer:** process-crash tests kill the program; atomic rename gives
  namespace all-or-nothing visibility; power loss additionally requires proof
  about filesystem and device cache persistence, which is NOT_RUN here.
- **Follow-up:** Why is an atomic pointer not a production HA system?
- **Learner answer target:** mention one host, no replication/quorum, no traffic
  failover, no backup-restore SLO, and no storage fault testing.
- **Code/test exercise:** interrupt a temporary staging build at a supported
  failure point and assert readers still resolve the old complete active target.

## Module 8: evidence engineering

- **Foundation:** `implemented`, `tested`, `measured`, `reproduced`, `externally
  validated`, and `production proven` are six different evidence levels.
- **Source trace:** `scripts/verify_portfolio_release.py`, public evidence JSON,
  `docs/enterprise_eval/CONSUMPTION_LEDGER.md`, and this handoff.
- **Design reason:** separating levels prevents a passing unit test from becoming
  a quality or production claim.
- **Alternative:** narrative-only reporting is shorter but permits stale numbers,
  hidden denominators, and accidental claim inflation.
- **Trade-off:** hashes, protocols, negative results, and verifier tests add
  maintenance, but make the project auditable.
- **Real failure:** equal RRF and the bounded multi-document candidate were
  implemented and measured, then rejected instead of shipped.
- **Interview question:** What does the portfolio verifier prove?
- **Reference answer:** clean Git identity plus dependency, compile, frozen
  evidence/prose, Agent/ACL/Guard regression, and public leak-audit contracts. It
  does not prove model quality, production readiness, or third-party validation.
- **Follow-up:** When may a negative result appear on a resume?
- **Learner answer target:** only when phrased as an evidence-backed engineering
  decision, with the rejected candidate, gate, measured trade-off, and no claim
  that failure itself improved user quality.
- **Code/test exercise:** change a copied metric in a temporary documentation
  fixture and confirm the evidence-contract test fails closed.

## Module 9: RAG pipeline versus replaceable Agent Runtime

- **Foundation:** RAG supplies and validates evidence; an Agent Runtime owns the
  bounded decision loop that chooses tools and terminal states. The
  `AgentOrchestrator` protocol separates that loop from authority enforcement.
- **Source trace:** `app/agent_runtime/orchestrator.py` defines the protocol,
  `BoundedControllerAdapter`, and `LangGraphOrchestratorAdapter`; both receive the
  same `AgentRunRequest` and return the same `AgentRunResult` contract.
- **Design reason:** framework migration must not duplicate identity, ACL, Guard,
  citation, or publication logic.
- **Alternative:** embed permissions in each framework node. This is locally
  convenient but allows policy drift and makes parity impossible to audit.
- **Trade-off:** the interface adds translation code, while keeping the lighter
  bounded controller as default avoids paying framework overhead without a need.
- **Real result:** both arms passed five fixed mechanism cases with no permission
  violations; this proves compatibility on those cases, not answer quality.
- **Interview question:** Why implement LangGraph but not make it the default?
- **Reference answer:** it is useful for explicit graph state and HITL, but the
  tiny parity diagnostic showed no quality gain and higher orchestration latency.
- **Follow-up:** What evidence would justify changing the default?
- **Learner answer target:** require a fresh workload, same authority path,
  quality/cost/latency gates, and a migration rollback condition.
- **Code/test exercise:** run one fixed case through both adapters and compare
  terminal state, tool sequence, evidence IDs, and permission violations.

## Module 10: Tool contracts, gateway authority, and MCP

- **Foundation:** a tool schema validates shape; `ToolGateway` validates whether
  this caller may execute it now. MCP standardizes tool interoperability but does
  not create authorization.
- **Source trace:** `app/agent_runtime/tool_contract.py` defines typed requests and
  results; `tool_gateway.py` enforces context; `mcp_adapter.py` maps official SDK
  calls back through the gateway using an opaque server-issued handle.
- **Design reason:** prompts and client-supplied identity are untrusted input.
  Server-held context binds tenant, ACL scope, allow-list, budget, sequence,
  deadline, and Guard policy.
- **Alternative:** expose retrieval directly from an MCP handler or include ACL
  fields in model arguments. Either lets a caller request broader authority.
- **Trade-off:** opaque handles require state, expiry, and revocation, but avoid
  serializing sensitive authority into model-visible arguments.
- **Real result:** local/in-process MCP tests exercise real `search/find/open`
  dispatch and failure mapping; no production network transport or OAuth exists.
- **Interview question:** Why is MCP not a security boundary by itself?
- **Reference answer:** MCP defines discovery and invocation. The host still owns
  identity, authorization, budgets, content admission, and result publication.
- **Follow-up:** What must change before exposing the adapter over a network?
- **Learner answer target:** name authenticated transport, credential rotation,
  rate limits, isolation, observability, revocation, and deployment threat tests.
- **Code/test exercise:** forge or expire a context handle in the MCP test and
  verify no gateway tool executes and only a structured safe error is returned.

## Module 11: canonical trajectory and deterministic replay

- **Foundation:** canonical serialization gives semantically identical events the
  same bytes; each event hash binds its content and previous hash. Replay first
  verifies the chain, then reconstructs recorded facts without rerunning tools.
- **Source trace:** `app/agent_runtime/trajectory.py` canonicalizes and stores
  events; `replay.py` validates ordering/hash links and derives the final view.
- **Design reason:** ordinary logs can be reordered or silently edited and often
  cannot explain which evidence produced a terminal decision.
- **Alternative:** rerun the Agent from the original question. External state,
  model sampling, and side effects make that nondeterministic and unsafe.
- **Trade-off:** semantic events improve auditability but do not make SQLite WORM
  storage or protect against an administrator replacing the whole database.
- **Real result:** the public sample has 13 ordered events and a verified artifact
  hash; one sample demonstrates the mechanism, not production audit compliance.
- **Interview question:** What does deterministic replay replay?
- **Reference answer:** recorded semantic events and derived state, not network
  calls, model generation, or tool side effects.
- **Follow-up:** How would you strengthen tamper evidence across machines?
- **Learner answer target:** external checkpoints/signatures, key management,
  append-only storage, retention, access control, and independent verification.
- **Code/test exercise:** mutate one event field in a temporary trajectory and
  assert verification fails before replay emits a result.

## Module 12: HITL resume and durability boundary

- **Foundation:** HITL pauses publication when partial evidence needs an explicit
  reviewer decision. A review token identifies pending state; it is not user
  identity or durable workflow storage.
- **Source trace:** the LangGraph adapter in `app/agent_runtime/orchestrator.py`
  creates review requests, validates reviewer tenant/role, marks tokens in use,
  and consumes them only after a successful terminal transition.
- **Design reason:** review must not bypass the same publication boundary, and a
  transient failure must not permanently consume an otherwise valid decision.
- **Alternative:** let the UI publish partial text directly. That bypasses the
  orchestrator, evidence trail, reviewer checks, and retry semantics.
- **Trade-off:** the current in-memory checkpointer and pending registry support
  same-process retry-safe resume but lose state on restart.
- **Real result:** tests cover accept, reject, wrong tenant/role, replayed token,
  concurrent resume, and retry after injected failure; crash recovery is NOT_RUN.
- **Interview question:** Why is retry-safe not the same as crash-safe?
- **Reference answer:** retry-safe preserves token/state after a handled failure
  in the live process; crash-safe requires durable atomic state across restart.
- **Follow-up:** What persistent state machine would you introduce first?
- **Learner answer target:** define pending/claimed/completed states, idempotency,
  atomic compare-and-set, lease expiry, and an append-only decision record.
- **Code/test exercise:** inject one publication failure, retry the same token,
  and verify exactly one completion event and no duplicate publication.

## Module 13: Agent Run Artifact and EvalOps boundary

- **Foundation:** `enterprise.agent-run/1.0` packages identity-safe run metadata,
  tool/evidence summaries, trajectory, terminal result, and hashes into a stable
  consumer contract. EvalOps can validate and aggregate it without rerunning the
  Agent or reading private runtime state.
- **Source trace:** `app/agent_runtime/evalops_artifact.py`, its JSON schema under
  `docs/agent_runtime/schemas/`, the sample evidence, and
  `scripts/verify_agent_run_artifact.py`.
- **Design reason:** test logs are not a versioned data contract; consumers need
  schema versioning, canonical hashes, explicit redaction, and fail-closed input.
- **Alternative:** have dashboards scrape application logs. That couples parsing
  to log wording and weakens integrity and privacy boundaries.
- **Trade-off:** the schema stabilizes integration but requires migration policy;
  it does not prove a deployed external EvalOps consumer exists.
- **Real result:** the sample and five-case A/B diagnostic validate artifact and
  parity mechanisms only. WixQA Recall@5/nDCG@5 separately measure retrieval;
  neither is end-to-end answer correctness.
- **Interview question:** Why can the artifact be verified but the answer still be
  wrong?
- **Reference answer:** schema and hashes prove structural integrity and recorded
  history, not semantic truth; answer correctness needs a separate gold/human
  protocol.
- **Follow-up:** Which metrics belong at trajectory, retrieval, and answer layers?
- **Learner answer target:** separate tool/terminal parity, retrieval Recall/nDCG,
  evidence completeness, answer correctness, citation precision/recall, and cost.
- **Code/test exercise:** validate the public sample, then remove a required field
  or alter a hash and confirm the consumer rejects it before aggregation.

## Teaching stop rule

After the learner can explain all thirteen modules and answer the story-bank
follow-ups, stop adding architecture for its own sake. Resume experimental
development only when there is a new legally usable cohort or recurring
real-user failure pattern and a frozen validation protocol.
