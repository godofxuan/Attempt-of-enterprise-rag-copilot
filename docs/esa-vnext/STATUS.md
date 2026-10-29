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
  Relevant offline regression: 83 passed; this newer fix still needs finite live verification.
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
Commit current integration without unrelated Streamlit/README edits; run finite live verification of
the typed-update/unit-selection repair. Then complete remaining R1 journeys and second-service R2.

## Milestones
M0: IMPLEMENTED; first startup failure reproduced and common startup separation fixed.
M1: IN_PROGRESS; CLI/UI/settings/lock/browser implemented and verified;
     persistent task recovery and explicit legacy-data integration depend on M3.
M2: IN_PROGRESS; library/index/shared knowledge implemented, newer source-unit live check pending.
M3: IMPLEMENTED vertical loan lifecycle; conflict/clear/repeated edits/idempotency/restart tested.
M4: IN_PROGRESS; thin native-tool loop, durable runs/SSE and actual loan UI journey verified;
     natural messages, branch journey and final restart tests still pending.
M5-M8: NOT_STARTED; no R1/R2 completion claim.

## External / Delivery State
- Models: installed local 9B/BGE used. At latest inspection 6 chat and4 embedding POSTs,
  all recorded in the product DB; query/index texts separated in the next usage projection.
- New commit: 540cfa55 (M1 scoped bootstrap). Later integration remains uncommitted; remote sync/PR not performed.
- Goal is active, not complete.
