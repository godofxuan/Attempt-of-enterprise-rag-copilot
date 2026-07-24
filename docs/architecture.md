# Enterprise Agentic RAG Architecture

## R2-S5 trusted identity boundary

The runtime no longer accepts caller-owned `UserContext` in the HTTP body.
The authoritative request path is:

```mermaid
sequenceDiagram
    participant C as Streamlit or local caller
    participant M as Request + identity middleware
    participant J as Immutable local JWKS snapshot
    participant A as Agent runner
    participant P as Access policy

    C->>M: Bearer JWT + question/top_k
    M->>M: Reject duplicate header and parse strict compact JWS
    M->>J: Select bounded ASCII kid
    J-->>M: Pinned RS256 public key
    M->>M: Verify signature, issuer, scalar audience, type, time, claims
    M->>M: Build immutable Principal
    M->>A: question + server-derived UserContext
    Note over M,A: service roles are removed before Agent state
    A->>P: tenant + region + groups
    P-->>A: authorized evidence only
```

The trust split is deliberate:

- `.private/identity/private-*.pem` signs short-lived local demo tokens and is
  read only by the lifecycle CLI, never by FastAPI or Streamlit;
- FastAPI loads only `jwks.json` and the independent feedback HMAC key at
  process construction, so rotation stages a key, restarts the API, proves the
  pending key through `/identity/me`, and only then publishes new client tokens;
- `Principal.roles` authorizes service routes, while Agent `UserContext.roles`
  is always empty;
- chat/feedback/identity require a user token; metrics/trace require the global
  deployment role `rag.operator`; health and API schema remain public;
- authentication middleware runs before FastAPI body parsing, so an invalid
  token plus malformed body deterministically returns 401 without invoking
  retrieval, models, feedback writes, or Agent traces.
- chat issues a feedback receipt bound to the verified actor, target request,
  and keyed question/answer digests; persistence keeps one latest rating per
  actor/target and stores no raw content.

The local issuer proves boundary mechanics and lifecycle behavior. It is not a
production IdP and does not implement SSO, remote JWKS refresh, revocation,
MFA, or identity governance.

最后更新：2026-07-24

本文描述当前 R2 本地实现。它解释代码中的数据流、控制流和信任边界；
尚未准入或仍待外部验证的能力见
[Industrialization Backlog](industrialization_backlog.md)。

## 1. 系统边界

```mermaid
flowchart TB
    subgraph Build["Offline build boundary"]
        F["Checked-in fact model"] --> CG["Deterministic corpus generator"]
        CG --> P["Typed parsers"]
        P --> D["DocumentRecord"]
        D --> CH["Chunk strategies"]
        CH --> IB["Immutable index builder"]
        IB --> IV["Versioned index + manifest"]
        IV --> AP["Atomic active pointer"]
    end

    subgraph Runtime["Online request boundary"]
        Caller["Authenticated caller"] --> MW["Request + identity middleware"]
        MW --> QA["Rule-first query analyzer"]
        QA --> CTL["Bounded Agent controller"]
        CTL --> Tools["search / find / open"]
        Tools --> ACL["Access policy"]
        ACL --> RET["Hybrid retrieval + navigation"]
        AP --> RET
        RET --> LED["Evidence ledger"]
        LED --> CTL
        CTL --> GEN["Grounded generation"]
        GEN --> CIT["Claim citation verifier"]
        CIT --> MW
        MW --> OBS["Safe traces + aggregate metrics"]
        MW --> FB["Receipt-bound keyed feedback metadata"]
    end

    subgraph Evidence["Evaluation boundary"]
        EV["Frozen dev/test contracts"] --> RUN["Deterministic or live runner"]
        RUN --> ART["Immutable local artifacts"]
        ART --> PUB["Sanitized public snapshot"]
    end
```

三条边界有意分离：build 产生可验证索引；runtime 只消费 active version；evaluation 复用生产路径但把结果写到独立、不可覆盖的 run。Streamlit 不直接读取内部 index 或原始 run。

## 2. 离线数据与索引生命周期

### 2.1 事实先于文档

事实源按版本而不是原地覆盖：

- `company_facts_v1.json` 服务历史 `demo/benchmark` 和已冻结证据；
- `company_facts_v2.json` 服务当前 `expanded/expanded_benchmark`；
- `app/corpus/catalog.py` 是 profile 到 facts/config 的单一映射入口。

`scripts/generate_enterprise_corpus.py` 从事实、profile 和 seed 确定性派生
制度、wiki、邮件、工单、会议与表格，并发布 manifest/hash。生成器先为每个
active fact 建立至少一个 supporting-content assignment，再填充随机噪声，因此
覆盖是 contract，不是概率。生成器不让 LLM 自由编写 gold data，所以版本冲突、
ACL、authority 和 expected facts 可复算。

当前默认 `expanded` 为 20 policies / 40 versions / 104 facts / 240 source
documents；2,000-document `expanded_benchmark` 只用于规模验证，不是默认
运行库。`app/corpus/quality.py` 在索引前检查事实唯一性、active-fact 支持与
评测覆盖、业务 ACL group 使用、来源/格式多样性和 eval split 完整性。CI 在
Ubuntu/Windows 的完整测试前执行该门禁。

### 2.2 统一 DocumentRecord

`app/parsing/` 把不同格式归一到 typed document/section 结构。metadata 在 chunking 前完成 schema 与治理校验，避免检索阶段再从正文猜 tenant、region、ACL、status 或 authority。

### 2.3 Chunk 不只是字符串片段

`app/chunking/` 支持 fixed、heading 和 parent-child 策略。Chunk 保留稳定 ID、section path、source locator、parent relation、版本与治理 metadata。parent-child 让检索命中小片段后可以在同一已授权文档中扩展上下文。

### 2.4 不可变 index version

`scripts/build_indexes_v2.py` 先在 staging 构建 BM25/FAISS 与 metadata artifacts，再验证 schema、维度、hash 和文件集合，最后 promote 到独立 run ID。active pointer 原子切换；已 active 的版本不能被 `--force` 静默覆盖。

这解决“embedding model 改了但旧向量仍被加载”的典型问题：query embedding 维度、manifest 声明和 dense index 维度必须一致，否则 fail closed。

2026-07-24 的当前本地 active version 是
`20260724T024653Z_expanded_bge_m3_fixed`：240 个源文档经治理得到 216 个
canonical documents/chunks，使用本地 BGE-M3 1024 维向量。旧 demo index
仍作为不可变 rollback target 保存，切换 existing version 不需要重新嵌入。

## 3. 在线请求时序

```mermaid
sequenceDiagram
    participant U as UI / caller
    participant M as Middleware
    participant A as Query analyzer
    participant C as Controller
    participant T as Tool registry
    participant R as Retrieval/navigation
    participant L as Evidence ledger
    participant G as Generator/verifier

    U->>M: POST /agent/v2/chat + X-Request-ID
    M->>M: validate ID, bind deadline and counters
    M->>A: question + validated UserContext
    alt direct unsafe request
        A-->>C: unsafe intent, no retrieval work
        C-->>M: source-free unsafe response
    else safe request
        A-->>C: intent, subqueries, required aspects, filters
        loop bounded by search/find/open/step/context/deadline budgets
            C->>T: exactly one typed action
            T->>R: authorized search, find, or open
            R-->>T: visible result or typed safe error
            T-->>L: evidence observation
            L-->>C: coverage, conflicts, recommended action
        end
        C->>G: visible ledger-selected evidence
        G->>G: structured claims + citation verification
        G-->>M: answered/partial/refusal/system result
    end
    M->>M: append safe request trace and metrics
    M-->>U: typed response + matching request ID
```

## 4. Query analysis and planning

`app/agent/query_analysis.py` is rule-first:

- deterministic rules identify unsafe intent and stable task shapes;
- fact/process/comparison/completeness/no-answer become typed `QueryAnalysis`;
- comparison creates separate entities, search queries, and required aspects;
- original question remains immutable while search work can be decomposed or rewritten;
- unsafe analysis cannot carry retrieval queries or required aspects.

The controller does not accept an arbitrary model-generated plan. It chooses one action from a fixed `AgentToolName` union and validates action arguments against Pydantic models.

## 5. Retrieval and authorization

`app/retrieval/pipeline.py` and `app/retrieval/navigation.py` implement:

1. query embedding and BM25 tokenization;
2. access filtering by tenant, region, and group before candidate content can enter fusion;
3. dense + sparse ranking and reciprocal-rank fusion;
4. current/retired status, authority, effective dates, and expected policy filters;
5. duplicate/diversity controls and bounded chunks per document;
6. optional authorized parent context;
7. typed find/open by IDs already present in the active snapshot.

ACL is repeated at navigation boundaries. A caller cannot pass a file path to `open`; tools accept typed chunk/parent/document IDs and re-check visibility.

## 6. Evidence-driven control loop

`ControllerState` separates:

- analysis and immutable user context;
- evidence grouped by required aspect;
- latest tool result;
- `EvidenceLedger`;
- explicit budget counters and deadline;
- terminal decision.

The ledger partitions every required aspect into supported or missing; conflicts remain missing until resolved. Coverage is `supported / required`. Its recommendation can be answer, search, find, open, partial, permission, not found, budget, or system.

The public Agent trace receives only counts, coverage, and recommendation. Aspect text, evidence items, document IDs, question, identity, and source preview are intentionally excluded from observability.

## 7. Generation and citation verification

`app/agent/generation_v2.py` receives only visible ledger-selected sources. The model returns structured atomic claims and cited source IDs. `app/agent/citation_verifier.py` then verifies that each citation:

- is present;
- refers to current visible evidence;
- has lexical support;
- maps back to a response claim.

Source-free modes (`unsafe`, `permission`, `not_found`, `system`, `budget`) cannot return sources. Authorization is therefore not delegated to the generator or prompt.

## 8. Service and observability

`app/api/middleware.py` binds a request ID and monotonic deadline in a `ContextVar`. Normal responses, validation failures, explicit API errors, and unhandled errors share the same safe envelope and response ID.

`app/observability/` records allowlisted span names, duration, route template, outcome, status code, model calls/retries/errors, and bounded aggregate latency. It does not retain question, answer, prompt, identity, headers, source metadata, model body, or exception text. Traces are in-memory and bounded, not durable OpenTelemetry traces.

Liveness answers “is the process alive?” Readiness answers “are database, active index, and models usable?” A process can correctly return live=200 and ready=503.

## 9. Presentation boundary

`streamlit_app/api_client.py` validates every response with backend Pydantic models and converts failures to `UiApiError` without raw exception/body text. `demo_cases.py` resolves six frozen EvalCases and one direct security probe by ID. `view_models.py` converts domain models into JSON-safe table rows. Pages only render these boundaries:

- Ask calls the live API after explicit submission;
- Trace renders session Agent trace and explicitly fetched service trace;
- Evaluation reads `data/v2/public/demo_snapshot.json` through strict schema.

Every page renders while the API is offline.

## 10. Evaluation boundary

The E4 runner evaluates retrieval, response, Agent, and security separately. Deterministic mode isolates orchestration with stable hash embeddings/extractive generation; live mode exercises active BGE-M3 and Qwen. Ablation compares retrieval and workflow variants. E5 load profiles use real HTTP and capture only safe metadata.

Raw run directories are ignored because they contain machine/run provenance and detailed cases. `app/evaluation/public_snapshot.py` verifies manifest-declared hashes, extracts allowlisted aggregate fields, and publishes a small deterministic snapshot with run IDs and SHA-256 references.

## 11. Deliberate non-choices

- No LangGraph dependency: the current state machine is small, typed, and easier to audit directly.
- No open-ended tool selection: enterprise authorization and cost require deterministic bounds.
- No vector database yet: the current scale and local lifecycle do not justify operational complexity.
- No reranker yet: the optional variant remains `NOT RUN` until an admitted model improves frozen metrics enough to justify latency.
- No multi-Agent layer: current failures concern evidence, identity, indexing, and observability rather than missing Agent roles.

Related documents: [API](api.md), [Threat Model](security_threat_model.md), [Evaluation](evaluation.md), [Observability](observability.md), and [Known Limitations](known_limitations.md).

## 12. R2-S1 retrieved-content boundary (`D5 IMPLEMENTED`)

R2-S1 D4 implements the frozen boundary between raw retrieval and `Controller.observe` on the default V2 Agent path:

```text
ACL-visible ranked candidates capped at candidate_k
-> bounded body/parent/metadata/find/open/split admission
-> content-free quarantine or deeply immutable admitted snapshot
-> GuardedV2ToolExecution
-> Controller runtime type check
-> admitted-only EvidenceLedger/generation/citation
```

Ranking runs once; quarantine does not consume a top-k/diversity slot, and clean recovery stays inside the same ACL-visible pool. The tool registry checks request/global deadlines after retrieval and after Guard admission, counts only admitted prompt-reachable characters, and fails source-free on a raw execution or unavailable boundary.

R2-S1 D5 extends this path after admission:

```text
admitted records -> bounded JSON serialization
-> fresh per-model-call nonce envelope
-> trusted system contract + post-envelope reminder

GuardedV2ToolExecution -> strict aggregate-only Agent trace projection
```

The deployable `create_app()` owns one fixed secure route profile:
`/agent/v2/chat` is registered while legacy `/chat`, `/agent/chat`, and HTTP
`/ingest` are absent. R2-S5 removed the compatibility factory from the
production module, so a wrapper cannot re-enable the unauthenticated historical
routes. Default container construction validates the detector policy, and
readiness exposes only bounded aggregate resource state.

This claim remains limited to `/agent/v2/chat` and its in-process `search/find/open` registry. D5 proves deterministic composition, escaping, route, trace and lifecycle contracts; it does not provide the D6 attack success rate, false-positive rate, or live-model evidence.

See [R2-S1 design](superpowers/specs/2026-07-17-r2-s1-indirect-prompt-injection-design.md), [attack-surface map](security/r2_s1/01_attack_surface_and_trust_boundaries.md), [D4 engineering journal](security/r2_s1/06_d4_engineering_journal.md), and [D5 engineering journal](security/r2_s1/07_d5_engineering_journal.md).
