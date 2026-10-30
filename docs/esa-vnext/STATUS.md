# ESA vNext Current Status

## 当前冻结交付：0.4.0（2026-10-30）

> 页面后续修正（用户截图反馈）：当前工作区在36dae403交付后新增仅表现层的会话历史整理。原60条记录保留；最近6条、时间排序、两行标题、搜索/更多、选中标记和窄屏折叠已在真实页面验证，列表从6406px降为最高480px。模型调用仍149，没有业务写入。原结果ZIP不覆盖，此UI提交尚未进入原ZIP；恢复最新页面应使用当前feature工作区。原模型/业务冻结链未改，浏览器记录在`.private/esa-vnext/ui-history-fix/`。



- U01–U24 / S0–S4本地范围完成；旧DONE_R1_R2_LOCAL_DEMO及以下过程原文保留。
- 应用冻结：b50d0f8a47d34e29d9706a2c4ef25db193ec0d26，分支codex/esa-030-040。之后仅交付文档变更，不回写7个无关修改或其他未提交工作。
- 当前入口：http://127.0.0.1:8740/；`.venv\Scripts\python.exe -m app.cli serve --data-dir .private/esa-vnext --port 8740`。同一主DATA_DIR，未重建业务库绕过未结限制。
- 用户可在会话内问答/补参/改期/选设备/预览/确认/查询；本地服务台借用预留→领用→归还后同库再次申请，报修处理→解决→关闭。真实9B工具选择与用户明确确认分开。
- 最终相关回归FINAL_B50D0F8A_REGRESSION.xml：115passed，84.44秒；不是全历史套件或质量准确率。
- 当前双入口FINAL_NATIVE_2026-10-30T06-32-24-607Z.json：实际RAG和Agent均从活动v2原文回答72小时，来源UI/窄屏通过，3chat。当前只读FINAL_READ_ONLY_20261030T063403.json：真实2chat，3张借用/2张报修前后不变，无preview/receipt。
- S2_DEEP_20261030T061510.json：两制度时长/条件正文完整、运费证据不足均真实通过。b50只恢复legacy契约，当前workbench输入和新wire均未改；不重复消耗模型复验同一协议。
- 业务真实UI闭环详见RELEASE八旅程表；借用9d254141、报修45751e73、当前PREVIEW_ONLY与状态读回c2ddd882，后续未改事务路径。续借/备选/重开等是程序检查，不冒充完整实时泛化。
- 当前应用源码独立wheel异目录init/doctor/两次HTTP启动和重启保留会话通过：3.063/2.812秒，0推理/0工单，使用既有锁定依赖环境。WHEEL-040-B50D0F8A_PROBE.json。
- 主账本起始40chat/26embed，最终149/97；本轮109chat+71embed POST（query66文本、index12文本）。失败计入，无SENDING、无活动run。其他历史计数不改；归属未知历史仍UNKNOWN。
- 先前Deep与错误不足均有负结果保留，两种无效否定规则回退；后续生成改为一个来源单位选择表示驱动正文与覆盖，不新增judge。最终有限例通过，不证明任意问题正确。
- 完整支持边界/证据适用性见RELEASE.md；实际问题口述记录见IMPLEMENTATION_INTERVIEW_NOTES.md。尚未证明追平 main。Linux/容器/多人企业部署未验证。
- 同步：本地feature里程碑已提交，未push、未PR；未找到适用的新远端授权，不将本地状态写为GitHub已更新。
- 下一动作：使用本轮结果包的源码/wheel和README复现演示；本Goal到此冻结，不再追加功能或新题集。交付提交与包摘要保存在结果包DELIVERY.json。


## 0.3 / 0.4 实施过程记录（按时间追加，早期未完成项已由上方最终状态覆盖）
- Goal ACTIVE: reviews/020-next/GOAL.md, U01-U24, S0-S4. Historical0.2.0 completion below is retained.
- Branch codex/esa-030-040 from8881b000; eight preexisting tracked modifications and unrelated untracked work retained.
- Actual port8740 was not listening. Started the existing CLI successfully with the same .private/esa-vnext data.
- Pre-upgrade SQLite backup: .private/esa-vnext/backups/pre-030-040_8881b000.sqlite3. Existing1loan/1repair ticket retained.
- Product starting counts primary40chat/26embed; historical and other declared data directories unchanged.
- S0 U01-U03: three actual REDs reproduced (asset_id KeyError, NO_WRITE_GOAL, stale active_run_id).
  Service field specs now supply required facts/form/questions. Knowledge messages go to the shared library without pending business facts.
  RunLifecycle releases only its matching task nonce/fence; all terminal events follow cleanup, cancelled messages retain raw text but release pending gate.
  UI now distinguishes stop-current-run from end-task. Related program checks21passed/0failed, S0_FINAL.xml.
- Initial unprivileged Windows asyncio probe hung creating its loopback IPC; same checks in the permitted local environment completed.
  Original audit script partial run remains isolated and is not counted as acceptance. No real model calls for S0.
- S1 U04-U08 candidate: additive conversation/turn storage, history projection, ContextBuilder and ToolCatalog reuse the one loop.
  Typed normalized changes, shared knowledge, resource selection and post-submit reads are exposed by actual task scope.
  UI split into api/events/conversation/tasks/library/renderers/settings modules; same-task timeline and current cards, cursor/terminal handling.
- Related current program batch44passed; user-role targeted8passed after a real canary exposed that the message was embedded as system data.
  First live canary4chat/1query embed: empty repair asks normally and shared policy answers, but supplied fields were not applied (FAIL).
  Original logs:upgrade-030-040/S1_CANARY_20261030T004818.json. No business rows changed; primary44chat/27embed afterward.
  Corrected the shared input boundary: current user message appears once as role=user, not duplicated in context; next live is targeted to that change.
- First browser structure check reached the new conversation but did not open its collapsed service form; harness corrected, not a product success claim.
-598d11c5 real follow-up canary passed: bare repair asks all3fields; one actual user message applies asset/description/high impact and answers loan duration via shared knowledge.
 4chat/1query embedding, business tables unchanged. Record:S1_CANARY_20261030T005431.json; primary48chat/28embed afterward.
 Corrected browser structure passed current modules/API, new conversation+repair binding, reload and390px;0model/0business submissions.
- Next: U09-U13 actual Deep/source/lifecycle work and0.3 release; then continue U14-U24.
  S0/S1 are checkpoints, not completion of0.3/0.4. S3/S4 service lifecycle/scheduling remain unimplemented.
- S2 U09-U12 in progress: DeepPlan selects1-4 actual subquestions; DeepController performs distinct searches and anchored find/open,
  then the existing runner/Guard/publisher. Strategy2checks passed; real Deep request not yet run.
- SourceSpan now propagates original parser locations/offsets through chunk/index/hit/admission/open/publication.
  Library index publisher consumes saved original parses and original-format bytes, not artificial Markdown; formats/types no longer allpolicy/md/2000.
  Default unknown source effective date uses build date only as technical index admission; no claim the policy became effective then.
  Old0.2 index generations stay unchanged; original-page precision applies to new generations, legacy view stays marked as such.
- Document batch upload, retry, rename, disable/restore, original-version comparison and service tags added. Active metadata checked against the published job's recorded metadata.
  Samples derive loan/repair documents from current SQLite rules; room is packaged knowledge-only. Business tools remain reference-only for uploaded policies.
- Related30program checks passed; Word full source path and actual two-page PDF locator checks passed. Added metadata-only stale-generation assertion next.
  Runtime server91057 still has598d11c5 S1 code in memory; restart after S2 regression before using new endpoints/live Deep.
  Next concrete action: finish S2 regression, commit candidate, restart owned server, import samples into same DATA_DIR KB,
  run one real Deep comparison and source UI check, finalize0.3 and proceed S3.
- Progress remains in this file; original design/evidence archived read-only under reviews/020-next.

- 0.3 stage commit31e0285a + entry8b4f687b retained. Real Deep first failed: both subjects read but canonical packet divided allowance across overlapping subquestions and repeated reads; loan limit was absent from sent packet.
  First correction delivered both numbers but model omitted requested applicability; result stayedpartial. Both negatives retained:S2_DEEP_20261030T015047/020012.json.
  Packet now replaces same-anchor search with actual read, budgets the actually rendered wire rather than the larger host offset table, and sends the investigation checklist to generation.43relatedprogram checks passed; next live is for this concrete change.
- U14-U18 implemented in current candidate: local TEST ActionSpec transitions, exact lifecycle previews/confirmations in the same action_proposals/confirmations/command_ledger, atomic approval+reservations, return/cancel releases, repair close/reopen, current ticket separated from immutable submission receipt.
  First service lifecycle16passed; preferences/date-candidate adjacent17passed. Actual primary database business lifecycle and browser NOT_RUN yet.
- U19-U21 candidate: default CLI factory avoids importing legacy app/container; explicit app.main legacy retained; installed model choices and onboarding, packaged sample resources, embedding misses batched16 with existing persistent cache. Program batch currently in progress; no speed claim.
- Next concrete action: finish batch/factory regression, commit S3 candidate, restart own8740server on current bytes, verify Deep, then same-primary-database UI loan/repair lifecycle and a small batch indexing/cache measurement. Do not stop at this checkpoint.

- 0.4真实UI核心链已完成（跨候选局部恢复，不冒充一次全绿）：借用b9d7ee9c71084a19b6f8e742fa60f7db改期/旧确认拒绝/当前确认/RESERVED/CHECKED_OUT/RETURNED；同库e245613868e34e2b8d24db60f8ca43ea再次申请后撤回。
  报修5842f125ffc443b8bca7322c3e67e11a从空字段自然补充、真实preview/OPEN到IN_PROGRESS/RESOLVED/CLOSED，45751e73记录S3_UI_2026-10-30T05-13-50-156Z.json最终通过。旧失败和原模型响应都保留，主库此时115chat。
- 真模型定位/实改：继续入口缺当前用户动作；未传既有目标释义；空finish未消费宿主观察；准备schema未承载用户描述；target与facts.asset_id重复表示；缺业务规则被误当缺用户信息。修复共同职责，没有题号/错字词典。
- 实测8个合成chunk一次批量embedding，冷构建3.031s、缓存重建1.016s且0新增embed，含轮询开销非纯计算时间。原资料版本替换/停用/恢复/历史定位均实操。
  该组问题却因跨文档同名属性被标冲突，内容为partial，不能算问答通过；正在收口用户明确《原文标题》时对已有policy ID的资源绑定，ACL/版本继续收紧。
- 知识已知负结果：跨国运费问题被用“没有规定押金”错误回答。一次提示追加使正常Deep退步，已回退；明确否定对象字面拦截也误伤4个原A1回归，已回退。NEGATIVE_ATTRIBUTION.xml保留，不将这些变体放入最终代码，不继续关键词修补。
  Deep真实读取与分题已存在，df0c118c有两数值/维修资格/会议室时段回答；后续实际schema预算多8字节导致0发送失败已修。当前最终Deep需要在冻结字节再记一次；错误不足反例仍为KNOWN_FAILED。
- 相关全批113passed/1failed：旧取消续跑替身对字段齐全任务仍ask_user，与当前合法动作schema不符。已保留原清理断言并改为实际合法读取→准备，额外检查preview生成和0写入；最终批待完成。
- 下一步：固定0.4候选，运行当前受影响路径、Deep-only与明确标题的两入口；发行副本/本地wheel启动和重启；汇总8类旅程、实际账目与已知知识缺口，然后交付。无有效GitHub推送授权，尚未同步，不创建虚假PR链接。

## Historical 0.2.0 Position (retained)
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
