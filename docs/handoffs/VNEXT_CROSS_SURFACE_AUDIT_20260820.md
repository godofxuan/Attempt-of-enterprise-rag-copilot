# vNext Cross-surface Audit - 2026-08-20

## Audit identity

- branch: `codex/agent-runtime-vnext`
- PRE_SYNC_HEAD: `ef9d0a919d3c002b7d868035c90b9f9624202513`
- scope: documentation/claim synchronization only; no metric recomputation and
  no new model, Dense, WixQA, EnterpriseRAG-Bench, FinQA, or garak run
- precedence: code/tests -> committed evidence -> CI -> vNext architecture and
  security docs -> current handoffs -> dated historical reports

## Matrix

| File/surface | Previous current wording | Code/test/evidence fact | Valid? | Class | Repair action | Authoritative entry after repair |
|---|---|---|---|---|---|---|
| `README.md` | `RAG_VNEXT_CLOSED`; bounded default; LangGraph/MCP/trajectory present | Matches runtime and closeout tests | yes | CURRENT | Retain; point resume/teaching to canonical ledgers | README + Project Status |
| `PROJECT_STATUS.md` top | 2026-08-11 archive enum and `current Agent candidate REJECTED` | vNext runtime exists after that cutoff | no as current; yes historically | HISTORICAL | Add 2026-08-20 canonical block; preserve old stages below a historical marker | `PROJECT_STATUS.md` top |
| `PROJECT_EVIDENCE_MAP.md` top | archive enum and stopped feature development | Current branch contains Agent Runtime vNext | no as current | HISTORICAL | Set `RAG_VNEXT_CLOSED`; add vNext mechanism claims without relabeling quality evidence | Evidence Map |
| `RESUME_METRIC_LEDGER.md` | numeric classes A-D | Numbers match evidence, but class names differ from vNext handoff | yes, naming drift | DUPLICATE | Make this the single numeric authority and map to four requested categories | Metric Ledger |
| `RESUME_SAFE_VNEXT_METRICS.md` | duplicates WixQA/index/garak numbers | Same numbers already live in Metric Ledger | valid but drift-prone | DUPLICATE | Convert to vNext claim policy that references the numeric ledger | Metric Ledger + vNext policy |
| `FINAL_RESUME_ENTRY_CN.md` | strong baseline bullets, no vNext Runtime/MCP/replay | vNext mechanisms are tested and documented | incomplete | UNSAFE BY OMISSION | Add role-specific bounded bullets and source/test/evidence mapping | Final Resume Entry |
| other `resume_package/*` surfaces | old candidate pool and evidence IDs stopped at P6 | baseline facts remain valid; P7/P8 were absent | partial | CURRENT + INCOMPLETE | Add current-state banners, P7/P8 mappings, runtime stories, and current forbidden wording | Final Resume Entry + Metric Ledger |
| `RESUME_CODEX_HANDOFF.md` | archive state; says do not add LangGraph/MCP | vNext implements both with bounded claims | false as current | HISTORICAL | Point to current state and permit only verified local/in-process wording | Resume handoff |
| `resume_package/PROJECT_SUMMARY.md` | archive state and feature stopped | superseded by vNext | historical only | HISTORICAL | Add supersession banner; preserve old result narrative | Current status + final entry |
| `TEACHING_CODEX_HANDOFF.md` | archive state; modules stop at old controller/evidence work | vNext tutorial and runtime code now exist | incomplete | UNSAFE BY OMISSION | Update reading order and add Runtime/MCP/trajectory/HITL/EvalOps modules | Teaching handoff |
| `RAG_PROJECT_TEACHING_HANDOFF.md` | enterprise evaluation only | still correct for retrieval/indexing, not full current curriculum | yes but partial | HISTORICAL MODULE | Add current curriculum banner and link runtime tutorial | Teaching handoff |
| `RAG_INTERVIEW_UPDATE.md` | bounded Agent answers predate vNext | baseline facts remain valid, runtime facts missing | partial | HISTORICAL MODULE | Add vNext interview supplement pointer | Story Bank + tutorial |
| `INTERVIEW_STORY_BANK.md` | eight baseline/evaluation stories | evidence remains valid; no Runtime/MCP/replay/HITL story | partial | CURRENT + INCOMPLETE | Preserve eight and append bounded vNext stories | Story Bank |
| `RECRUITER_SUMMARY.md` | says feature development stopped; no vNext | no longer describes current branch | no | HISTORICAL | Synchronize concise vNext positioning and keep limitations | Recruiter Summary |
| `docs/final_closeout/resume/*` | role-specific vNext package | consistent with PRE_SYNC_HEAD closeout | yes | CURRENT | Reference, do not create another numeric authority | Fact Sheet -> Metric Ledger |
| old `codex/rag-eval-system` mentions | historical branch recorded in dated protocols/results | true for those executions | yes historically | HISTORICAL | Keep; forbid use as current branch in canonical surfaces | Cross-surface contract |
| `66.42%` / `52.16%` | sometimes copied into many surfaces | evidence binds them to WixQA retrieval | only with scope | CURRENT METRIC | Numeric authority in one ledger; enforce “not answer accuracy” | Metric Ledger |
| `511,962` / `1.37 GiB` | scale claim | public synthetic, one-host FTS build | yes with scope | CURRENT METRIC | Retain one-host/public synthetic qualifiers | Metric Ledger |
| `4/12 -> 0/12` | security result | pinned 12-attack subset only | yes with denominator | CURRENT LIMITED | Keep as specialized/security bullet, not universal claim | Metric Ledger |
| five-case parity | occasionally presented near architecture | deterministic mechanism diagnostic, not external quality/performance | yes only interview-side | INTERVIEW_ONLY | Enforce explicit small synthetic boundary | vNext metrics policy |
| third-party provenance | no canonical record; root `LICENSE` absent | direct API dependencies and concept references exist | incomplete | UNSAFE BY OMISSION | Add provenance table; record unknowns and no-copy evidence boundary | `THIRD_PARTY_PROVENANCE.md` |

## Search classification decision

Occurrences of old dates, old branches, rejected candidates, or stopped stages
inside immutable evidence, dated protocols, engineering journals, and historical
reports are retained. A string is a problem only when a current entry point
uses it without a historical marker. No global replacement was performed.
