# ESA vNext Current Status

## Current Position
- Workspace: `D:/文档/agent/RAG_try`; branch `codex/esa-vnext`.
- Original main HEAD: `51faa5ba2f35d79120b362fff08b091646168d77`; 27 tracked dirty files predate this work. Their changes are preserved; the RAG modules now also contain explicit integration edits.
- Scope: R1+R2 / M0-M8; DONE_R1_R2_LOCAL_DEMO. No explicit token budget assigned.
- Stage: frozen application bytes670fdb66; final delivery changes are documentation and the CLI probe only.
- Existing effective assets: main dirty RAG; `_delivery_work/ESA_AGENTOPS_20261013/source_candidate`
  for Service/AgentOps; Enterprise working `rag_source_candidate` has a later
  `generation_v2.py` edit. No archived tree will replace any of these.
- Existing successes retained: C3 A2-A5 live TEST business evidence; A1 offline
  mapping repair; Service exact preview/confirmation/idempotent readback; AgentOps readonly export.
- Historical boundary: old C3 results do not establish all vNext paths; current limited live pairs are listed below.

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
  Later clean-source and clean-dependency installation are recorded below.
- M2: actual upload/parser/library/version/job/atomic index publication/shared RAG and persisted answers added.
  Real BGE created a two-document synthetic index. First real 9B answer failed delivery because inherited
  HTTP deadline expired; durable bounded runs fixed that boundary. Second live answer delivered but partial.
  Later source-unit schema/presentation and live pairs are recorded below.
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
- Implemented continuation: unresolved user-message safety/recovery and optional original-question
  parameter prefill. Host preview/confirmation/resume blocked until input is applied or explicitly resolved;
  no invented consumption of failed input. Latest targeted bootstrap/message/lifecycle batch11 passed.
- Directory import/unchanged/replace/missing-source retention/recovery and existing embedding cache
  implemented. Program check: identical documents publish next generation with0 embedding misses.
- Interview issue log: `IMPLEMENTATION_INTERVIEW_NOTES.md`, updated from real failures only.

## Latest Checkpoint — 2026-10-30 local
- c68a115a removed eager legacy graph/evaluation imports from the thin Agent package. A separate
  uv-installed environment imports and starts committed code without author editable paths.
- Added bounded send-time deadline checking and409 settings protection during active runs/index jobs.
- Real J10 exposed early not_found: Guard admitted both policies, but the old extraction relevance
  gate treated a personal booking year as a required year in policy prose. No generation was sent.
  Product KnowledgeService now uses the existing semantic need/source contract on the whole question;
  old extractive interfaces retain their contract. Candidate admission is not final answer support.
- Real UI task8f868cae456244bba31cb0a995e6ef11 then completed knowledge-to-task, explicit user opt-in
  extraction of dates/purpose, actual asset2 selection, preview/date edit/stale-confirmation409,
  current exact confirmation, one PENDING_APPROVAL ticketfa214993a3e54b16874ccb643cbcf7d4 and idempotent reload.
  This J10 knowledge result was still partial. Its trace is not rewritten as an all-quality pass.
- Saved real response showed a recovered exact draft unit lost its existing unambiguous need association
  and was dropped by publication. Repaired that handoff; multiple/unknown needs remain unresolved.
  Missing semantic coverage cannot become complete merely from citations.
- Subsequent same-question real RAG/Agent pair both answered all six requested policy facets:
  `demo-validation/logs/KNOWLEDGE_HANDOFF_PAIR_20261029T195549.json`. The later missing-coverage guard
  changes only the absent-relation negative branch; these actual replies contained relations.
- Final related program batch:115 passed,3 FAISS binding deprecation warnings; no full historical suite.
  Includes bootstrap/messages/lifecycle, original A1 replay, generation/controller/relevance and identity boundary.
- Real unchanged-document cache comparison: first rebuild2 misses/2 embedding requests/3.282s;
  second rebuild2 hits/0 requests/0.218s. Specific batch, not QA accuracy or a universal speed claim.
- Actual appended product attempts at checkpoint: primary data21 chat/12 embed; independent TEST journey
  data9 chat/6 embed. All completed OK, raw requests/responses remain in their app.sqlite3 model_calls.
  Earlier product rows whose purpose was not recorded remain UNCLASSIFIED; historical experiment ledger untouched.
- Interview record now includes9 real problems, with causes, changes, tests/live boundaries and oral answers.

## Decisions
- Product changes will be in the current repository, not another full checkout or ZIP.
- Reuse the latest Service modules and current RAG implementation selectively;
  preserve the independent working originals and later Enterprise RAG edit.
- Historical experiment ledger stays immutable. Product model operations are ordinary
  configured local calls, not reclaimed or reset historical experiment balances.
- No giant audit bundles, full-tree duplication or unrelated historical suite.

## R2 Implementation Checkpoint — 2026-10-30 local
- Shared fixed Service Catalog now defines loan and local synthetic IT repair fields, rules/read adapters,
  operation/table/status. Both use the same task UI, native-tool loop, proposal, confirmation,
  command transaction, cancel/fence and readback. No second graph or transaction implementation.
- Real J11 UI task4540ac96eaca4f6c8e53276a69fc5aee:5 chat attempts, policy/assets/owned-ticket reads,
  natural description/impact update, stale confirmation409, oneOPEN ticket8c0cb7c79fe64abd9f9ba50e6c393486,
  idempotent retry and reload. All loan tickets/assets/eligibility/rules unchanged.
  Raw:logs/J11_2026-10-29T20-23-14-792Z.json and current database.
- Actual follow-up used prior user questions, never prior answers as evidence. Initial browser assertion
  expected the newer example phrase, while the older indexed policy said“没有规定押金”. Its zero-assumption
  explanation remains a content limitation, preserved in logs/FOLLOWUP_2026-10-29T20-06-20-469Z.json.
- J12 real two-version room answers both answered:09:00-18:00 then10:00-19:00, both retained2-hour limit.
  Initial build2 misses; changed build1 hit/1 miss. Missing source retained with notice; old source opened.
  UI continuation after opening the closed source details sent0 chat; original harness failure retained.
  Raw:J12_2026-10-29T20-33-21-435Z.json and J12_PRESENTATION_*.json.
- The earlier follow-up issue became an actual UI feedback candidate. expected=null; no automated
  truth label/model run. Current source/old version metadata and original PDF/Word parser locations retained.
- Same current UI after restart read actual old loan and new repair receipts,0 chat.
  Raw:PERSISTED_RECEIPTS_2026-10-29T20-42-24-023Z.json.
- Actual readonly dependency experiment retained asset/ticket observations after an independent description
  edit. Tool reads3->1, chat2->2; complete read elimination was false. Business rows unchanged.
  Raw:READ_REUSE_20261029T203733.json. No blanket latency or chat-saving claim.
- Repeated-start RED reproduced: second instance was not rejected and startup could interrupt active work.
  OS-level data-directory lease and readonly doctor fixed that. Cross-process crash release tested.
- Browser fixture found old confirmation/form remaining while another task loaded. Immediate clear/loading
  plus selection version fencing fixed it. Delayed real response, scope refusal, dates, long text,
  narrow screen and script payload checked; explicitly PROGRAM_FIXTURE,0 chat.
  First fixed browser result file was overwritten; initial tool output separately captured with that limitation,
  later output names use timestamps. The original historical evidence was not modified.
- Current related program regression127 passed; final small projection check3 passed. Last code after
  the127 batch only changes completed-view text and parsed-location presentation; no model input/transaction change.
  Actual JUnit:logs/R2_RELATED_REGRESSION.xml. No full historical suite or main model comparison.
- App package now0.2.0; uv lock resolved offline with the same109 total locked packages including optional groups.
  Final clean default installation and source packaging still pending at this checkpoint.
- Appended product attempts before final release checks: primary33 chat/18 embed requests;
  independent demo-validation9 chat/6 embed; presentation fixture0 inference. Historical ledger untouched.
- b81dff81 exported and installed from cache in a new directory:43 default packages, isolated-source
  probe PASS. Dev extras needed4 public wheels absent from cache; pinned packages installed only into
  that independent venv. Original project third-party environment unchanged.
- Final wire inspection found RAG num_predict1800 vs packing reserve1024. Actual callback/HTTP RED
  reproduced1800!=1024. Shared serving constants now govern both; only RAG default transport changed,
  not native600/message500 or permissions. This tiny correction supersedes b81 as final source;
  the b81 archive remains a checkpoint. Focused regression and final bounded live evidence follow.

## Next Action
No queued development or model runs. Use START.md / RELEASE.md for the frozen local demonstration.
R3, enterprise deployment and a new quality benchmark are outside this completed scope.

## Final Freeze — 2026-10-30 local
- Application/lock commit670fdb66be89e473070ada879bd01b3f47065b8a. Later delivery commit contains
  documentation and a no-inference CLI probe; verify `git diff 670fdb66..HEAD -- app pyproject.toml uv.lock` is empty.
- 955bf690 real comparison exposed two completion authorities: semantic need/body binding was complete,
  but entity-name repetition forcedpartial. Same original reply RED then scoped GREEN. Semantic mode
  now retains lexical counts as diagnostics; unknown/missing relation, unsupported claims, source and
  upstreampartial protections remain. Legacy aspect mode unchanged.
- New actual pair on670fdb66: logs/FINAL_LIVE_20261029T213822.json. Both answered, each with two sources.
  Both bodies retain1-14days/start-not-past/active-repair/one-open-request and room2hours/09-18/cleanup.
  The before/after is a content/status consistency correction, not a broad accuracy claim. No business rows changed.
  Actual num_ctx8192/num_predict1024. This pair used3chat/4query-embedding requests, no retry.
- Final source exported by scripts/export_vnext_source.py, separate environment installed44 default
  pinned packages; explicit-directory/no-editable-source probe passed. Dev adds4 packages.
  Independent Windows regression:129passed/0failed/0skipped,53.053s; build/CLEAN_FINAL_670fdb66.xml.
  Four dependency deprecation warnings remain. No full historical suite or main QA comparison.
- Real installed esa CLI invoked from another working directory: HTTP/static/API available, TEST task
  preserved across two process starts, same initialized marker,0model calls/0business tickets.
  Startup5.000s and4.360s on this machine; build/CLEAN_CLI_670fdb66.json. Not a cross-machine benchmark.
  Initial init-output capture had a Windows decoding warning; the two actual HTTP/DB checks passed.
  The reusable probe now explicitly enables UTF8 in its child process.
- Earlier independent failure: missingtzdata caused16failures, omitted HTTP helper caused1. Direct
  lockedtzdata and helper export fixed them. Offline-only install first missed its wheel; only that
  pinned public dependency was fetched in the independent venv, no model/global environment changes.
- Earlier related regression128pass/1fail exposed timing-dependent test setup: sleep10ms did not always
  expire1ms on Windows. It touched the local model port once and timed out. OriginalERROR row retained
  in logs/OFFLINE_TEST_UNEXPECTED_SENDS.json; deterministic clock plus fail-on-send transport now passes.
- Final product counts: primary40chat/26embedding requests; demo-validation9chat/6embedding; presentation0.
  Total49product chat/32embedding requests(32texts), plus the one failed test attempt =50known new chat attempts.
  All49product HTTP replies wereOK, not proof their content was all correct. Historical experiment ledger
  untouched; historical UNKNOWN staysUNKNOWN. Earlier unclassified product purposes remain unclassified.
- One authoritative product DB per declared DATA_DIR, no second quota ledger. Summary with raw pointers:
  logs/R1_R2_RELEASE_SUMMARY.json. Source archives exclude databases, raw ledgers, personal docs and indexes.
- Git remains local codex/esa-vnext; no push/PR/merge. Remote feature branch was absent at the checked state.
  Unrelated preexisting work remains dirty and excluded from the source export.

## Milestones
M0: IMPLEMENTED; first startup failure reproduced and common startup separation fixed.
M1: IMPLEMENTED for local single-owner mode; same-dir recovery, readonly doctor and OS lease tested.
     Historical JWT databases remain preserved, not reassigned to local-owner.
M2: IMPLEMENTED; shared pair and versioned answers live-verified; contextual follow-up linked, with
    the explicit content limitation above. Old source and parser location access verified.
M3: IMPLEMENTED vertical loan lifecycle; conflict/clear/repeated edits/idempotency/restart tested.
M4: IMPLEMENTED; native-tool loop, durable runs/SSE, loan/repair natural update and readonly branches live-verified;
    current browser and restart checks retained separately from fixture tests.
M5: IMPLEMENTED vertical path; J10 actual UI/model/business journey verified; knowledge handoff had a
    separate negative result and later focused live pair, as recorded above.
M6: DONE_LOCAL_RELEASE; final independent source install, actual CLI/restart and129related regressions passed.
M7: IMPLEMENTED/LIVE_VERIFIED in shared framework with synthetic backend.
M8: IMPLEMENTED/LIVE_VERIFIED; directory versions, feedback candidate and measured embedding reuse.

## External / Delivery State
- Models: installed local 9B/BGE used; all attempts remain appended in product model_calls. Historical
  grant ledger is untouched. Recompute current totals from DB rather than copying old checkpoint counts.
- Commits:540cfa55 bootstrap;38a5b69d integration;d25b4048 knowledge;78379f8a packaging correction;
  6cf66b65 pending-input recovery/prefill; c68a115a lazy legacy imports. Latest checkpoint commit follows.
  Unrelated preexisting README/Streamlit work retained.
  No remote sync or PR performed.
- Current R1/R2 scope is complete for the documented local synthetic demonstration. R3 is not activated.
