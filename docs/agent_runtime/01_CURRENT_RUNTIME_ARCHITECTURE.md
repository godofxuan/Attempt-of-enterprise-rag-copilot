# Current Agent Runtime Architecture

## One-page flow

```text
User query
  -> FastAPI identity boundary
  -> rule-first query analysis
  -> bounded controller
  -> typed search/find/open request
  -> tool registry budget and deadline checks
  -> document navigator and retrieval pipeline
  -> ACL filtering
  -> retrieved-content admission and Guard
  -> evidence ledger
  -> claim construction
  -> deterministic citation/grounding checks
  -> answered / partial / refusal / safe error terminal
```

The Python host owns every security and publication boundary. A configured
model may assist query analysis or answer wording, but model output is parsed
into strict schemas and cannot grant identity, expand the tool allowlist, bypass
admission, increase a budget, or publish an unverified terminal answer.

## 1. API and identity

**Input:** HTTP request and bearer identity.  
**Output:** a trusted `UserContext` plus question and request correlation.  
**Authority:** `app/api/identity.py`, middleware, and the request context.  
**Host controls:** route access, token verification, tenant, groups, roles,
request ID, and deadline.  
**Model authority:** none.  
**Stop conditions:** missing, forged, expired, mismatched, or unauthorized
identity fails before Agent execution.  
**Tests:** `tests/api_v2/test_identity_boundary_api.py`,
`tests/api_v2/test_real_jwt_integration.py`, and trusted-identity security tests.

## 2. Query analysis

**Input:** question and trusted user context.  
**Output:** strict `QueryAnalysis`: intent, entities, search queries, required
aspects, filters, risk flags, and source.  
**Authority:** `RuleFirstQueryAnalyzer` in `app/agent/query_analysis.py`.  
**Model authority:** an optional model fallback may propose structured analysis.  
**Host controls:** schema validation, unsafe intent rules, filter shape, maximum
query/aspect counts, and fallback behavior.  
**Stop conditions:** unsafe intent routes to a safe terminal; malformed model
output cannot become executable work.  
**Current limit:** rule-first analysis often creates one aspect and one search;
it is not a general autonomous planner.

## 3. Bounded controller

**Input:** `QueryAnalysis`, current evidence state, observations, and budget.  
**Output:** one validated `AgentAction`.  
**Authority:** `V2AgentController` in `app/agent/controller_v2.py`.  
**Model authority:** none in the default controller.  
**Host controls:** action sequence, aspect coverage, completion logic, safe
terminals, and hard budget exhaustion.  
**Stop conditions:** completed, partial evidence, no match, denied evidence,
unsafe request, system failure, or exhausted budget.  
**Current limit:** the default path searches each required aspect. `find` exists
but is not normally selected; `open` is mainly used for completeness handling;
automatic query rewrite/retry is disabled.

## 4. Tool execution

**Input:** typed `SearchRequest`, `FindRequest`, or `OpenRequest`.  
**Output:** typed result or structured `ToolError`.  
**Authority:** `V2ToolRegistry` in `app/agent/tools_v2.py`.  
**Model authority:** a model may only propose arguments that survive schema and
host policy validation.  
**Host controls:** allowlist, call counts, step count, context size, per-call
timeout, request deadline, and result admission.  
**Stop conditions:** invalid arguments, permission denial, timeout, budget, or
system failure become bounded observations rather than unrestricted retries.

## 5. Retrieval and ACL

**Input:** typed request carrying the server-derived `UserContext`.  
**Output:** visible versioned chunks or a safe no-result/denial state.  
**Authority:** `DocumentNavigator`, `HybridRetrievalPipeline`, document access
policy, and version metadata.  
**Model authority:** no direct SQL, FAISS, SQLite, file, or index access.  
**Host controls:** tenant, region, groups, status, authority level, temporal
scope, active index manifest, result limits, and timeout.  
**Stop conditions:** cross-tenant and invisible documents remain unavailable;
internal denied counts are excluded from external serialization.

## 6. Retrieved-content admission

**Input:** retrieved search hits, find previews, or opened content.  
**Output:** admitted evidence, filtered evidence, and safe counters.  
**Authority:** `RetrievedContentAdmission` and the retrieved-content Guard in
`app/security/`.  
**Model authority:** retrieved text is data, never an instruction source.  
**Host controls:** indirect-injection detection, output normalization, maximum
content, and rejection.  
**Stop conditions:** all evidence filtered produces a safe evidence-filtered or
partial terminal, not an answer grounded in rejected text.

## 7. Evidence state

**Input:** admitted tool outputs.  
**Output:** an Evidence Ledger tied to document, chunk, version, locator, and
tool provenance.  
**Authority:** `app/agent/evidence_ledger.py`.  
**Host controls:** only admitted, visible evidence enters generation.  
**Current limit:** the ledger is request-scoped evidence state; it is not yet an
append-only durable Agent trajectory.

## 8. Claims, citations, and terminal publication

**Input:** question, analysis, and Evidence Ledger.  
**Output:** structured claims, citations, answer mode, and stop reason.  
**Authority:** response builder plus `app/agent/citation_verifier.py`; the runner
publishes the final terminal.  
**Model authority:** wording or structured claim proposals when configured.  
**Host controls:** claim evidence IDs, citation existence, supportedness,
terminal mapping, and fallback to partial/refusal/error.  
**Stop conditions:** unsupported or absent evidence cannot be silently promoted
to a grounded answer.

## 9. Runner and observability

`V2AgentRunner` owns the loop: analyze, ask the controller for one action,
execute it through the registry, feed the observation back, and stop at a host
terminal. It returns a bounded step trace. Request observability separately
records route latency, status, model counters, process memory, and named spans.

Current request traces are stored in a bounded in-memory store and correlate by
request ID. They are operational observations, not durable semantic execution
history. vNext must correlate trajectory events with trace/session/step IDs
without treating either record as an authorization source.

## Production-like versus prototype scope

**Production-like mechanisms:** strict domain schemas; trusted identity and ACL;
retrieved-content admission; bounded execution; deterministic citation checks;
versioned index activation/rollback; crash-recovery tests; security regression
tests; evidence-linked evaluation and CI.

**Prototype or limited behavior:** rule-first planning depth; automatic adaptive
retrieval; durable Agent event storage; replay/resume; MCP interoperability;
alternative graph orchestration; meaningful HITL; and externally demonstrated
end-to-end Agent quality improvement.

Existing WixQA evidence shows that the bounded Agent path reused the retrieval
ranking but did not improve it. A rejected multi-document candidate fixed zero
consumed cases while reducing precision and increasing latency. These are
constraints for vNext evaluation, not defects to conceal.

