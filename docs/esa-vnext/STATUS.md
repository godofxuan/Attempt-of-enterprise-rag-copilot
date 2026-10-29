# ESA vNext Current Status

## Current Position
- Workspace: `D:/文档/agent/RAG_try`; branch `codex/esa-vnext`.
- Original main HEAD: `51faa5ba2f35d79120b362fff08b091646168d77`; 27 tracked dirty files predate this work and remain untouched.
- Native Goal: ACTIVE, R1+R2 / M0-M8. No explicit token budget assigned.
- Stage: M1 bootstrap implemented; M2 document library / shared knowledge integration next.
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
- Interview issue log: `IMPLEMENTATION_INTERVIEW_NOTES.md`, updated from real failures only.

## Decisions
- Product changes will be in the current repository, not another full checkout or ZIP.
- Reuse the latest Service modules and current RAG implementation selectively;
  preserve the independent working originals and later Enterprise RAG edit.
- Historical experiment ledger stays immutable. Product model operations are ordinary
  configured local calls, not reclaimed or reset historical experiment balances.
- No giant audit bundles, full-tree duplication or unrelated historical suite.

## Next Action
Integrate document library/shared knowledge and
port current Service modules without overwriting source originals.

## Milestones
M0: IMPLEMENTED; first startup failure reproduced and common startup separation fixed.
M1: IN_PROGRESS; CLI/UI/settings/lock/browser implemented and verified;
     persistent task recovery and explicit legacy-data integration depend on M3.
M2-M8: NOT_STARTED (existing underlying assets above are not reset or reimplemented blindly)

## External / Delivery State
- Models: installed local 9B/4B/BGE metadata checked; no generation or embedding sent.
- Live journeys this iteration: NOT_RUN.
- New commits / remote sync / PR: none yet.
- Goal is active, not complete.
