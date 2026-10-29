# ESA vNext Current Status

## Current Position
- Workspace: `D:/文档/agent/RAG_try`; branch `codex/esa-vnext`.
- Original main HEAD: `51faa5ba2f35d79120b362fff08b091646168d77`; 27 tracked dirty files predate this work. Their changes are preserved; the RAG modules now also contain explicit integration edits.
- Native Goal: ACTIVE, R1+R2 / M0-M8. No explicit token budget assigned.
- Stage: M2-M4 vertical slices implemented; knowledge source-unit selection and product continuation next.
- Existing effective assets: main dirty RAG; `_delivery_work/ESA_AGENTOPS_20261013/source_candidate`
  for Service/AgentOps; Enterprise working `rag_source_candidate` has a later
  `generation_v2.py` edit. No archived tree will replace any of these.
- Existing successes retained: C3 A2-A5 live TEST business evidence; A1 offline
  mapping repair; Service exact preview/confirmation/idempotent readback; AgentOps readonly export.
- Existing limitation: last patched A1 live pair not established by those old results.

## Latest Actual Work
- Read parent AGENTS, Git status, GOAL/architecture/roadmap/contracts.
- Installed plan in `docs/esa-vnext/`; merged applicable conventions into root AGENTS.
- Created feature branch without committing/reverting prior edits.
- Old offline launcher actually failed: `dual_track_worker.prepare -> GET /api/tags -> WinError 10061`.
- Implemented single-app `app.cli init/serve/doctor`, existing `app.main.create_app`
  workbench lifespan, stable `.private/esa-vnext/app.sqlite3`, settings and four-tab UI.
- First actual HTTP probe found a second blocker: global identity middleware returned
  `identity_unavailable` for the new local UI/settings. Added a local workspace
  route partition; old protected document/operator APIs remain authenticated.
- 3 bootstrap program regressions first failed with 503, then passed; model unavailable,
  settings persistence, restart, cross-origin and legacy boundary checked.
- Bootstrap plus existing identity API regressions: 37 passed. Actual Edge browser
  verified unavailable-model UI, settings persistence, narrow viewport and no JS errors.
- Editable `esa` console installed; uv.lock generated (109 packages), offline lock check passed.
  This is not yet a clean-environment install claim.
- M2: actual upload/parser/library/version/job/atomic index publication/shared RAG and persisted answers added.
  Real BGE created a two-document synthetic index. First real 9B answer failed delivery because inherited
  HTTP deadline expired; durable bounded runs fixed that boundary. Second live answer delivered but partial.
  Source-unit schema/presentation integration subsequently changed; that newer knowledge path still needs live verification.
- Integrated 8 existing ServiceDesk modules into the one app, not another hidden source tree.
  Added transactional expected_facts_revision, explicit null clearing, valid-preview reuse and per-run budgets.
- Real current UI loan task 875dc57da41a4ed98f5496453cd13db0 used native Ollama tool calls:
  loan_policy/assets_search/tickets_list_mine -> prepare_preview. Date edit cleared consent;
  stale confirmation got409; current exact confirmation created one PENDING_APPROVAL ticket
  cbac73f0466f47caa10a1bfdd73e8596; reload readback passed. 4 actual chat calls across its 2 runs.
- UI harness initially observed the pre-run BLOCKED baseline too early; same task continued successfully.
  Fixed harness to wait for the persisted run, resumed that task rather than creating/re-running it.
- Current raw evidence lives in `.private/esa-vnext/logs` and the one app.sqlite3 model_calls/task_events/
  workbench_runs/tickets/confirmations tables. No historical ledger changes.
- Further finite live checks: both knowledge entries delivered partial with the same omission,
  natural update rejected UNBOUND_PARAMETER_UPDATE, owned-ticket readonly branch returned the real pending
  ticket and left DB count1->1. Raw record: logs/M4_SHARED_BRANCH_20261029T181629.json.
- Located actual early causes: old keyword-dependent planner invented a materials obligation;
  generated composite quotation crossed separate complete units; generic changes/sources dictionaries
  let the model use mismatched keys and concatenate dates into purpose. Removed those planner branches,
  made the wire select host complete-unit IDs, and changed updates to typed field/value/exact-quote rows.
  Relevant offline regression: 83 passed at that point (not additive with later batches).
- Later typed update succeeded on the same natural request; readonly owned-ticket branch completed,
  DB ticket count1->1. Knowledge body became complete but status remained partial: old clause splitting
  omitted the first obligation; model conflated a source-supported negative answer with inability to answer.
- d25b4048 now retains the whole original knowledge obligation and defines that semantic distinction.
  Real pair in logs/M2_KNOWLEDGE_PAIR_20261029T184116.json: both entries answered, all required clauses retained.
- M6 clean-source check caught an omitted untracked KnowledgeService module. Fixed in78379f8a.
  Independent committed code then started without editable paths. Actual uv sync installed64 pinned
  public dependencies in its own venv, and the probe passed there too; no model calls in either probe.
- Current uncommitted continuation: unresolved user-message safety/recovery and optional original-question
  parameter prefill. Host preview/confirmation/resume blocked until input is applied or explicitly resolved;
  no invented consumption of failed input. Latest targeted bootstrap/message/lifecycle batch11 passed.
- Directory import/unchanged/replace/missing-source retention/recovery and existing embedding cache
  implemented. Program check: identical documents publish next generation with0 embedding misses.
- Interview issue log: `IMPLEMENTATION_INTERVIEW_NOTES.md`, updated from real failures only.

## Decisions
- Product changes will be in the current repository, not another full checkout or ZIP.
- Reuse the latest Service modules and current RAG implementation selectively;
  preserve the independent working originals and later Enterprise RAG edit.
- Historical experiment ledger stays immutable. Product model operations are ordinary
  configured local calls, not reclaimed or reset historical experiment balances.
- No giant audit bundles, full-tree duplication or unrelated historical suite.

## Next Action
Finish current pending-update/prefill UI and tests, run J10 knowledge-to-task/choice in an isolated
synthetic journey, browser-check current controls, record a real cache rebuild comparison, then
freeze R1 and continue M7 IT repair through shared lifecycle plumbing (no copied Agent loop).

## Milestones
M0: IMPLEMENTED; first startup failure reproduced and common startup separation fixed.
M1: IN_PROGRESS; CLI/UI/settings/lock/browser implemented and verified;
     persistent task recovery and explicit legacy-data integration depend on M3.
M2: IMPLEMENTED vertical path; real shared pair answered. Conversation follow-up and source presentation
    still need final journey coverage; this is not a claim that all QA matches main.
M3: IMPLEMENTED vertical loan lifecycle; conflict/clear/repeated edits/idempotency/restart tested.
M4: IN_PROGRESS; native-tool loop, durable runs/SSE, loan UI, natural update and readonly branch live-verified;
    latest unresolved-input recovery covered offline, current browser/final restart checks pending.
M5: IN_PROGRESS; answer link, optional original-question prefill, dependency reuse and actual asset options implemented;
    complete J10 not yet verified.
M6: IN_PROGRESS; clean source and clean dependency installation verified. Release journey matrix/docs still pending.
M7: NOT_STARTED.
M8: PARTIAL_EARLY; directory incrementality and cache reuse tested offline; real cache comparison/feedback UI pending.

## External / Delivery State
- Models: installed local 9B/BGE used; all attempts remain appended in product model_calls. Historical
  grant ledger is untouched. Recompute current totals from DB rather than copying old checkpoint counts.
- Commits:540cfa55 bootstrap;38a5b69d integration;d25b4048 knowledge;78379f8a packaging correction.
  Later pending-input/prefill changes uncommitted; unrelated preexisting README/Streamlit work retained.
  No remote sync or PR performed.
- Goal is active, not complete.
