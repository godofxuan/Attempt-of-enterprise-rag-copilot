# E3 ACL-aware Retrieval and Agent Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 legacy `/chat`、`/agent/chat` 和 `hybrid_search` 默认行为的前提下，新增消费 E2 active v2 index、显式 UserContext、ACL-aware search/find/open、EvidenceLedger 和 citation verification 的 `/agent/v2/chat` 垂直链路。

**Architecture:** 新链路使用独立 Pydantic domain contracts；validated `V2IndexSnapshot` 绑定 active manifest 和全部 artifacts；ACL/metadata filter 发生在候选进入 fusion/context/trace 前。Rule-first QueryAnalysis 驱动 bounded tools，EvidenceLedger 决定继续或停止，v2 runner 只把 visible evidence 交给生成与 citation verifier。

**Tech Stack:** Python 3.11、Pydantic v2、FAISS IndexFlatIP、rank-bm25、jieba、FastAPI、pytest、本地 Ollama adapter（仅 live path）。

## Global Constraints

- 所有 production 行为先写测试并观察正确 RED，再写最小 GREEN。
- unsafe 请求在 index load、embedding、retrieval 和 generation 前 deterministic short-circuit。
- tenant/region/group ACL fail closed；roles 不隐式绕过 groups。
- denied chunk ID/title/text 不进入 fusion、context、sources、response trace 或错误消息。
- 模型只能提出结构化候选；Python 执行 ACL、budget、tool allowlist 和 stop condition。
- tests 不连接 Ollama；使用 fake embedder、fake generator 和临时 E2 version store。
- E1 frozen test 不读取、不调参、不修改；E3 experiments 只用 v2 dev。
- legacy API、router/planner/runner/evaluator 保留为 baseline，E4 前不自动迁移。
- 不实现 reranker、OCR、增量索引、真实 IAM、Redis、队列、多 Agent、长期记忆或 UI。
- 当前没有 commit/push/merge/tag 授权；计划中的每个 Change 记录 diff，但不执行 Git 写操作。
- 每个 Change 后更新 `docs/roadmap/e3_retrieval_agent_workflow_implementation.md` 和 `CURRENT_EXECUTION_HANDOFF.md`。

---

## File Structure

### Domain

- Create `app/domain/queries.py`: UserContext、filters、analysis、search/find/open requests/results。
- Create `app/domain/evidence.py`: evidence、ledger、claims、citations、AnswerResponse。
- Create `app/domain/agent.py`: budgets、actions、stop reasons、tool errors。

### Security

- Create `app/security/__init__.py`。
- Create `app/security/access.py`: ACL decision、visible projection、trace redaction。

### Retrieval

- Create `app/retrieval/__init__.py`。
- Create `app/retrieval/snapshot.py`: validated active E2 artifact loader。
- Create `app/retrieval/pipeline.py`: BM25/dense/RRF、filter、diversity、parent expansion。
- Create `app/retrieval/navigation.py`: typed search/find/open facade。

### Agent v2

- Create `app/agent/query_analysis.py`。
- Create `app/agent/evidence_ledger.py`。
- Create `app/agent/citation_verifier.py`。
- Create `app/agent/tools_v2.py`。
- Create `app/agent/controller_v2.py`。
- Create `app/agent/runner_v2.py`。
- Create `app/agent/generation_v2.py`。

### Compatibility

- Modify `app/schemas.py`: add v2 request only; old schemas unchanged。
- Modify `app/main.py`: add `/agent/v2/chat`; old endpoints unchanged。
- Modify `app/config.py`: bounded v2 Agent defaults only。

### Tests and records

- Create `tests/domain_v2/`、`tests/security/`、`tests/retrieval/`、`tests/agent_v2/`。
- Create `docs/roadmap/e3_retrieval_agent_workflow_implementation.md`。
- Create `docs/roadmap/e3_beginner_learning_and_interview.md` at final gate。

---

### Task 1: Typed E3 Domain Contracts

**Files:**
- Create: `app/domain/queries.py`
- Create: `app/domain/evidence.py`
- Create: `app/domain/agent.py`
- Modify: `app/domain/__init__.py`
- Test: `tests/domain_v2/test_query_models.py`
- Test: `tests/domain_v2/test_evidence_models.py`
- Test: `tests/domain_v2/test_agent_models.py`

**Interfaces:**
- Produces: `UserContext`, `QueryFilters`, `QueryAnalysis`, `SearchRequest`, `SearchHit`, `SearchResult`, `FindRequest`, `FindResult`, `OpenRequest`, `OpenResult`。
- Produces: `EvidenceItem`, `EvidenceLedger`, `Claim`, `ClaimCitation`, `AnswerSource`, `AnswerResponse`。
- Produces: `AgentBudget`, `BudgetState`, `AgentAction`, `ToolError`, `AnswerMode`, `AgentStopReason`。

- [ ] **Step 1: Write failing query contract tests**

```python
def test_user_context_rejects_duplicate_groups_and_extra_fields(): ...
def test_search_request_cannot_override_user_tenant_or_region(): ...
def test_comparison_analysis_requires_two_entities_and_subqueries(): ...
def test_search_result_rejects_hits_from_another_index_run(): ...
```

- [ ] **Step 2: Verify query RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\domain_v2\test_query_models.py -q -p no:cacheprovider
```

Expected: collection fails with `ModuleNotFoundError: app.domain.queries`。

- [ ] **Step 3: Implement strict query models**

Required signatures:

```python
class UserContext(StrictModel):
    user_id: str
    tenant_id: str
    region: str
    groups: list[str]
    roles: list[str] = []

class SearchRequest(StrictModel):
    query: str
    user: UserContext
    filters: QueryFilters
    top_k: int = 5
    candidate_k: int = 20
    mode: Literal["bm25", "dense", "hybrid"] = "hybrid"
    include_parent: bool = True
    max_chunks_per_doc: int = 2
    timeout_ms: int = 5000
```

- [ ] **Step 4: Write and verify evidence/agent RED**

Test coverage: duplicate required aspects、coverage consistency、answered requires claims/sources、unsafe cannot expose sources、budget counters cannot exceed limits、unknown tool rejected、safe messages cannot contain denied metadata。

- [ ] **Step 5: Implement evidence and agent models**

`EvidenceLedger` validator recomputes or verifies `coverage = supported/required`；`AnswerResponse` enforces source-free unsafe/permission/not_found/system/budget outcomes；all models use `extra="forbid"`。

- [ ] **Step 6: Run Task 1 GREEN**

Expected: all `tests/domain_v2` pass；legacy 225 tests remain unchanged when run later。

- [ ] **Step 7: Record E3-C01**

Document exact RED/GREEN and explain why runtime dicts are insufficient for security/budget state。

---

### Task 2: ACL Policy and Redacted Projection

**Files:**
- Create: `app/security/__init__.py`
- Create: `app/security/access.py`
- Test: `tests/security/test_access_policy.py`
- Test: `tests/security/test_trace_redaction.py`

**Interfaces:**
- Consumes: `UserContext`, `ChunkRecord` or serialized chunk dict。
- Produces: `AccessDecision(allowed, code)` for internal use, `is_visible(user, chunk) -> bool`, `visible_chunks(...)`, `redact_trace_payload(...)`。

- [ ] **Step 1: Write ACL RED tests**

```python
def test_access_requires_tenant_region_and_group_intersection(): ...
def test_roles_do_not_bypass_missing_group(): ...
def test_visible_projection_never_returns_denied_chunk(): ...
def test_public_error_and_trace_do_not_contain_denied_ids_titles_or_text(): ...
```

- [ ] **Step 2: Verify RED**

Expected: `ModuleNotFoundError: app.security`。

- [ ] **Step 3: Implement fail-closed policy**

Unknown/missing tenant、region、ACL fields return denied. Internal codes are `tenant_mismatch/region_mismatch/group_mismatch/malformed_metadata`；public projection exposes only aggregate status。

- [ ] **Step 4: Run GREEN and mutation checks**

Change each ACL dimension independently in parametrized tests. Assert input chunks are not mutated。

- [ ] **Step 5: Record E3-C02**

Include the difference between authentication, authorization and this demo fixture policy。

---

### Task 3: Validated V2 Index Snapshot

**Files:**
- Create: `app/retrieval/__init__.py`
- Create: `app/retrieval/snapshot.py`
- Create: `tests/retrieval/conftest.py`
- Create: `tests/retrieval/test_snapshot.py`

**Interfaces:**
- Consumes: E2 `load_index_version(root)` and validated artifacts。
- Produces: `V2IndexSnapshot.load(root)`, fields `version`, `faiss_index`, `bm25`, `chunks`, `parents_by_id`, `documents_by_id`, `chunk_index_by_id`。

- [ ] **Step 1: Build temporary E2 store fixture**

Use E1 demo corpus and fake 4D embedder; activate one fixed or parent-child run in `tmp_path`。No Ollama。

- [ ] **Step 2: Write snapshot RED tests**

Test active pointer required、manifest/chunk/FAISS counts aligned、parent map loaded、Unicode root、tampered artifact rejected before pickle consumption。

- [ ] **Step 3: Verify RED**

Expected: `ModuleNotFoundError: app.retrieval.snapshot`。

- [ ] **Step 4: Implement loader**

Call E2 validation first, then deserialize. Reject unknown FAISS type/metric, empty BM25 corpus, duplicate chunk IDs and parent ID collision。

- [ ] **Step 5: Run GREEN and E2 store regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\retrieval\test_snapshot.py tests\indexing\test_store.py -q -p no:cacheprovider
```

- [ ] **Step 6: Record E3-C03**

Explain why validated pickle is loaded only after manifest hash checks。

---

### Task 4: ACL-aware Hybrid Retrieval Pipeline

**Files:**
- Create: `app/retrieval/pipeline.py`
- Test: `tests/retrieval/test_pipeline_acl.py`
- Test: `tests/retrieval/test_pipeline_ranking.py`
- Test: `tests/retrieval/test_pipeline_parent.py`

**Interfaces:**
- Consumes: `V2IndexSnapshot`, `SearchRequest`, injected `embed_text(text) -> list[float]`。
- Produces: `HybridRetrievalPipeline.search(request) -> SearchResult`。

- [ ] **Step 1: Write zero-leak RED tests**

Fixtures contain a high-scoring denied chunk and a lower-scoring visible chunk. Assert denied chunk ID/text is absent from hits、fusion diagnostics、trace-safe stage data and exception text in BM25/dense/hybrid modes。

- [ ] **Step 2: Verify RED**

Expected: module/function missing, not fixture error。

- [ ] **Step 3: Implement filter-first candidate construction**

Build visible indices with `AccessPolicy` and `QueryFilters` before creating dense/BM25 ranked candidate objects. Do not store denied IDs in `SearchResult`。

- [ ] **Step 4: Add ranking RED tests**

Test BM25-only without embed call、dense dimension mismatch fail closed、hybrid RRF deterministic ties、current/authoritative filters、as-of date、department/policy filter、max chunks per doc。

- [ ] **Step 5: Implement BM25/dense/RRF and metadata rules**

RRF constant is explicit in result config. Authority/current adjustment is deterministic and separately reported from lexical/vector scores。

- [ ] **Step 6: Add parent expansion RED and GREEN**

Child hit keeps child citation ID/locator while `context_text` comes from authorized parent. Missing/mismatched parent fails closed without using unrelated text。

- [ ] **Step 7: Run Task 4 GREEN**

Run all `tests/retrieval/test_pipeline_*` plus E2 builder/adapter tests。

- [ ] **Step 8: Record E3-C04 and first retrieval experiment**

Measure deterministic fixture and demo dev behavior without changing frozen test。

---

### Task 5: Typed Search, Find and Open Navigation

**Files:**
- Create: `app/retrieval/navigation.py`
- Test: `tests/retrieval/test_navigation.py`
- Test: `tests/security/test_navigation_zero_leak.py`

**Interfaces:**
- Produces: `DocumentNavigator.search(SearchRequest)`, `.find(FindRequest)`, `.open(OpenRequest)`。
- Errors: `ToolError(code="invalid_args|not_found|permission|timeout|system", retryable, safe_message)`。

- [ ] **Step 1: Write search/find/open RED tests**

Test find scoped to one visible doc、open by chunk/parent/doc、max chars、max matches、unknown ID、denied ID indistinguishable from not found in public message。

- [ ] **Step 2: Verify RED**

Expected: `ModuleNotFoundError: app.retrieval.navigation`。

- [ ] **Step 3: Implement bounded navigator**

No filesystem path is accepted from tool args. Navigation uses only snapshot maps and caller UserContext. Token/substring matching uses existing tokenizer and stable ordering。

- [ ] **Step 4: Add deadline/structured error tests**

Inject monotonic clock or fake slow pipeline. Deadline checks occur before and after call; timeout result contains no internal path/chunk text。

- [ ] **Step 5: Run GREEN and record E3-C05**

Include examples showing search discovers, find narrows inside doc, open retrieves bounded context。

---

### Task 6: Rule-first QueryAnalysis

**Files:**
- Create: `app/agent/query_analysis.py`
- Test: `tests/agent_v2/test_query_analysis.py`

**Interfaces:**
- Produces: `RuleFirstQueryAnalyzer(fallback=None).analyze(question, user) -> QueryAnalysis`。
- Fallback protocol: `analyze(question, user) -> QueryAnalysis`，only called after deterministic safety rules。

- [ ] **Step 1: Write behavior RED tests**

Test unsafe short circuit、comparison extracts two `《...》` entities and two subqueries、completeness/process/current/historical filters、ordinary fact、ambiguous fallback。

- [ ] **Step 2: Write invariant RED tests**

Fallback cannot remove risk flags、change original question、inject tenant/region/group filters、add more than bounded subqueries or return unsafe as safe。

- [ ] **Step 3: Verify RED**

Expected: module missing。

- [ ] **Step 4: Implement deterministic rules and validated fallback merge**

Use structured regex/token rules only for behaviorally meaningful fields. Do not preserve legacy route labels that change nothing。

- [ ] **Step 5: Run GREEN and legacy router regression**

Old `route_query` tests must still pass untouched。

- [ ] **Step 6: Record E3-C06**

Document rule-vs-LLM boundary and remaining language limitations。

---

### Task 7: EvidenceLedger and Citation Verifier

**Files:**
- Create: `app/agent/evidence_ledger.py`
- Create: `app/agent/citation_verifier.py`
- Test: `tests/agent_v2/test_evidence_ledger.py`
- Test: `tests/agent_v2/test_citation_verifier.py`

**Interfaces:**
- Produces: `build_ledger(analysis, evidence_by_aspect, conflicts=[]) -> EvidenceLedger`。
- Produces: `verify_claims(claims, visible_hits) -> list[ClaimCitation]`。

- [ ] **Step 1: Write ledger RED tests**

Comparison one side -> coverage 0.5 + partial/search; both sides -> answer; zero visible with denied-only signal -> permission; no match -> not_found; unresolved equal-authority conflict -> search/partial; budget exhausted -> budget/partial。

- [ ] **Step 2: Verify RED then implement ledger**

Required aspect support comes from tool purpose and visible evidence, not arbitrary LLM claim. Authority/current conflict resolver is deterministic。

- [ ] **Step 3: Write citation RED tests**

Test missing citation、unknown/denied chunk ID、valid visible citation、lexical support zero、multiple claims and duplicate citations。

- [ ] **Step 4: Implement verifier**

Presence and visible-reference correctness are hard checks. Lexical overlap is a support signal explicitly labelled heuristic, not semantic entailment。

- [ ] **Step 5: Run GREEN and record E3-C07**

Include examples of citation presence vs correctness vs semantic support。

---

### Task 8: Bounded V2 Controller, Tools and Runner

**Files:**
- Create: `app/agent/tools_v2.py`
- Create: `app/agent/controller_v2.py`
- Create: `app/agent/runner_v2.py`
- Modify: `app/config.py`
- Test: `tests/agent_v2/test_tools_v2.py`
- Test: `tests/agent_v2/test_controller_v2.py`
- Test: `tests/agent_v2/test_runner_v2.py`
- Test: `tests/security/test_agent_trace_zero_leak.py`

**Interfaces:**
- Produces: `V2ToolRegistry(navigator)`, `V2AgentController`, `V2AgentRunner.run(question, user, top_k=None) -> AnswerResponse`。
- Controller consumes typed `AgentAction` and `EvidenceLedger`; no arbitrary tool name from model。

- [ ] **Step 1: Write tool allowlist/budget RED tests**

Search/find/open consume separate counters; over-budget returns typed error without executing tool; unsafe consumes zero; context char cap enforced。

- [ ] **Step 2: Implement registry and BudgetState consumption**

Registry accepts only enum tool names and typed args. Every result updates request-local context through typed models。

- [ ] **Step 3: Write controller trajectory RED tests**

Trajectories:

```text
unsafe -> refuse
fact -> search -> ledger -> answer
comparison -> search(entity A) -> search(entity B) -> ledger -> answer/partial
completeness -> search -> open -> ledger -> answer
no match -> not_found
denied-only -> permission
missing + exhausted -> budget/partial
```

- [ ] **Step 4: Implement explicit state machine**

No recursive loop. Max steps and deadline checked centrally. Missing aspect determines next subquery/tool purpose。

- [ ] **Step 5: Write runner zero-leak RED tests**

High-scoring denied evidence cannot appear in response sources、claims、citations or trace. Tool/system exceptions return `system`, never fallback to legacy retrieval。

- [ ] **Step 6: Implement runner and redacted trace**

Trace records action、status、latency、visible count、budget and stop reason only. Query text may be truncated/hashed; chunk text omitted。

- [ ] **Step 7: Run GREEN plus legacy Agent regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\agent_v2 tests\security -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_agent_controller.py tests\test_agent_adaptive_runner.py tests\test_agent_api.py -q -p no:cacheprovider
```

- [ ] **Step 8: Record E3-C08**

Compare old retry loop and new missing-aspect-driven actions without claiming LLM autonomy。

---

### Task 9: Generation Adapter and `/agent/v2/chat`

**Files:**
- Create: `app/agent/generation_v2.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Test: `tests/agent_v2/test_generation_v2.py`
- Test: `tests/agent_v2/test_api_v2.py`
- Test: `tests/security/test_api_v2_zero_leak.py`

**Interfaces:**
- Produces: visible-hit-to-prompt adapter and `run_agent_v2_chat` dependency for endpoint。
- API request requires `user_context`; response is typed `AnswerResponse`。

- [ ] **Step 1: Write generation RED tests**

Prompt contains only ledger-selected visible context; parent context bounded; source numbering stable; generator receives original question and analysis intent; no legacy search call。

- [ ] **Step 2: Implement fake-friendly generation adapter**

Inject `chat_fn`. Default uses existing Ollama transport, not `answer_question/hybrid_search`. Parse bounded structured response or fail closed to `system`。

- [ ] **Step 3: Write API RED tests**

Missing user_context -> 422；valid request passes exact user to v2 runner；legacy `/agent/chat` response unchanged；unsafe endpoint call does not instantiate/load retrieval pipeline。

- [ ] **Step 4: Implement schemas and endpoint**

Add `AgentV2ChatRequest`; do not modify `ChatRequest` fields or old route implementations. Dependency construction is lazy after unsafe analysis。

- [ ] **Step 5: Run GREEN and endpoint compatibility suite**

Run new API/security tests plus old `test_agent_api.py` and `test_rag_service_agent_flow.py`。

- [ ] **Step 6: Record E3-C09**

Document why required UserContext is safer than implicit admin/default groups。

---

### Task 10: Demo Dev Evidence, Documentation and E3 Gate

**Files:**
- Create: `scripts/eval_agent_v2_dev.py`
- Create: `tests/agent_v2/test_eval_agent_v2_dev.py`
- Modify: `docs/roadmap/e3_retrieval_agent_workflow_implementation.md`
- Modify: `docs/roadmap/engineering_decision_failure_ledger.md`
- Modify: `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`
- Create: `docs/roadmap/e3_beginner_learning_and_interview.md`

**Interfaces:**
- Consumes: E1 demo dev, E2 active/fake deterministic index or explicit live index。
- Produces: action/outcome/security/coverage details without reading frozen test。

- [ ] **Step 1: Write evaluator RED tests**

Metrics: outcome accuracy、comparison full coverage、permission zero-source、unsafe zero-tool、budget compliance、trace completeness、citation presence/visible correctness。Details retain safe IDs only。

- [ ] **Step 2: Implement deterministic evaluator**

No output path prints JSON only；explicit output creates new run directory and refuses overwrite。Live mode is separate and never silently substituted。

- [ ] **Step 3: Run demo dev behavior audit**

Record every number and failure. Compare fixed E2 BM25 failure categories, but do not claim E4 final quality evaluation。

- [ ] **Step 4: Run E3 focused gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\domain_v2 tests\retrieval tests\security tests\agent_v2 -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_agent_controller.py tests\test_agent_adaptive_runner.py tests\test_agent_api.py -q -p no:cacheprovider
```

- [ ] **Step 5: Run repository gates**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app scripts tests
git diff --check
```

Also verify E1 frozen test hash、E2 build dry-run no-write、Git lock absent、project Python/pip background process 0。

- [ ] **Step 6: Complete beginner record**

Explain every E3 file、ACL order、RRF、query decomposition、ledger、budgets、tool errors、citations、good/bad results and interview answers。Do not mark user learning as complete without hands-on acceptance。

- [ ] **Step 7: Stop before E4**

Set handoff to `E3 implementation complete, awaiting user acceptance` and require exact command `批准E3，执行E4评估与消融`。Do not commit/push without separate authorization。
