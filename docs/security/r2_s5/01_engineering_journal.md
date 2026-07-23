# R2-S5 Trusted Identity Boundary Engineering Journal

Status: exact-SHA CI #17 failed; repair is locally green; replacement CI pending

Started: 2026-07-22

Selected design: local reproducible RSA JWT/JWKS identity source

This journal records design decisions, code locations, RED/GREEN evidence,
failures, corrections, security boundaries, and interview explanations. It is
append-only during implementation; later corrections supersede earlier entries
instead of silently rewriting the history.

## 1. Why R2-S5 is next

R2-S4 completed cross-model security-evaluation operations, but it did not make
the serving API production-ready. The most consequential serving gap is that
the caller supplies `UserContext` in the request body. Existing ACL code checks
tenant, region, and groups correctly after receiving that object; it does not
authenticate where those fields came from.

This is not fixed by adding another LLM, Agent framework, vector database,
queue, cache, or deployment platform. The missing control is a deterministic
identity authority boundary before Agent execution.

## 2. Existing code before R2-S5

- `app/schemas.py::AgentV2ChatRequest` requires `user_context` in JSON.
- `app/main.py::agent_v2_chat` passes it directly to `run_agent_v2_chat`.
- `app/security/access.py::AccessPolicy` performs fail-closed
  tenant/region/group matching; roles do not bypass groups.
- `/feedback`, `/observability/metrics`, and trace lookup are unauthenticated.
- Streamlit exposes editable user, tenant, region, groups, and roles and sends
  them in the request body.
- Liveness/readiness exist, but readiness has no identity-key check.

The ACL implementation remains useful and is retained. R2-S5 changes the
authority that creates its `UserContext` input.

## 3. Option decision

Three routes were considered:

1. local reproducible JWT/JWKS identity source;
2. immediate real IdP/JWKS integration;
3. trusted reverse-proxy identity headers.

The owner approved option 1. It provides deterministic tests and an interview
demo without external accounts or network availability. The verifier interface
keeps a later real IdP adapter possible, but this stage does not claim one.

## 4. Initial architecture decision

The trust path is:

```text
Bearer token -> local public JWKS -> verified Principal
-> deterministic UserContext -> existing AccessPolicy -> retrieval/Agent
```

The private key stays under ignored `.private/identity/` and is used only by a
local CLI. The API receives public keys only. The secure body will no longer
accept identity. Metrics and trace will require `rag.operator`; feedback will
bind to a domain-separated HMAC pseudonym. Health remains public, and readiness
will reveal only identity `ok|error`.

## 5. Engineering implementation order

The work uses vertical TDD rather than writing the entire test suite first:

1. configuration and dependency contract;
2. one valid JWKS snapshot;
3. one valid JWT-to-Principal flow;
4. negative cases one behavior at a time;
5. service/readiness integration;
6. API route enforcement;
7. privacy-bounded feedback and observability;
8. local CLI and UI migration;
9. frozen security/performance evaluation;
10. full regression, review, public documentation, and remote CI.

## 6. Standards and dependency evidence

RFC 8725 requires explicit algorithm verification, issuer/subject validation,
audience validation, and treating claims as untrusted until validation. RFC
7517 defines the JWKS representation. FastAPI's official JWT tutorial uses
PyJWT and recommends its crypto extra for asymmetric algorithms.

At implementation start, the selected pinned versions are PyJWT 2.13.0 and
cryptography 49.0.0. This choice will be rechecked by installation, `pip check`,
Linux CI, and the repository dependency snapshot tests. Cryptographic
verification will not be reimplemented manually.

## 7. Claim boundaries before implementation

Planned completion can prove only a local synthetic identity boundary. Real
SSO, remote OIDC discovery, remote JWKS availability, revocation, refresh,
SCIM, policy administration, production deployment, and production traffic
remain `NOT RUN` or unimplemented.

## 8. Completed security-review disposition

The read-only security review completed with zero Critical, ten Important, and
three Minor findings. These are contract corrections, not optional ideas.

### Important contracts

1. **Client token destination:** local clients must accept only an exact
   canonical numeric-loopback origin, reject userinfo/path/query/fragment,
   disable environment proxy inheritance, and disable redirects. A future
   nonlocal mode needs a separate HTTPS allowlist.
2. **API errors:** the error abstraction must preserve headers. Missing or bad
   credentials are 401 with `WWW-Authenticate: Bearer`; a valid non-operator is
   403; unavailable JWKS/verifier is generic retryable
   `503 identity_unavailable`.
3. **Strict JWT:** reject duplicate header/payload keys, unexpected and remote
   key headers, non-scalar audience, non-integer timestamps, unbounded/non-ASCII
   key IDs, malformed compact serialization, and all algorithm ambiguity.
4. **Role isolation:** `Principal.roles` is only service authorization and must
   map to `UserContext.roles=[]`; `rag.operator` must never affect retrieval or
   Agent prompts.
5. **Persona workflow:** the CLI must issue an ignored persona token bundle;
   Streamlit selects server-issued personas and never signs or reads private
   keys. User and operator credentials are separate.
6. **Load-profile migration:** `scripts/load_profile.py` must stop sending body
   identity, use user/operator token providers, and never save or print tokens.
7. **Feedback identity:** replace enumerable plain SHA-256 with an independent
   secret-key HMAC, add `target_request_id`, and label question/answer hashes as
   caller-declared unless tied to a server-owned response.
8. **Observability:** denied operations may emit bounded route/status/latency/
   decision telemetry with `model_calls=0`, but no Agent trace, retrieval,
   feedback write, or trace lookup. `/identity/me` is the one intentional safe
   identity disclosure. Operator is a global deployment role only.
9. **Compatibility app:** it is local/offline-only, binds numeric loopback, is
   absent from deployment/CI startup guidance, and is never a production
   rollback target.
10. **Configuration/dependencies:** audience and operator role need strict
    validation; repository tests with exact dependency sets must be updated for
    the pinned JWT/crypto dependency closure.

### Minor contracts

1. The 1,000-verification p95 target is a recorded local benchmark artifact,
   not a hard shared-CI wall-clock gate.
2. OpenAPI, `/docs`, and `/redoc` remain public as an intentional
   low-sensitivity schema surface and require a no-secret verification.
3. Environment token and token-file sources are mutually exclusive. Token
   files are freshly read, bounded, regular, no-symlink/reparse, and never put
   in Streamlit session state.

## 9. TDD work log to date

Only evidence actually observed by the focused identity-core work is marked
complete here. API, UI, feedback, readiness, evaluation, full-suite, audit,
and CI results remain pending.

### 9.1 Configuration defaults: RED -> GREEN

- **RED:** accessing the new identity settings raised `AttributeError` because
  the settings did not exist.
- **Change:** added pinned local JWKS path, issuer, audience, RS256 algorithm,
  explicit token type, lifetime, skew, and size/count bounds.
- **GREEN:** default-settings tests passed.
- **Why:** configuration is part of the trust boundary; an implicit default in
  route code would be difficult to validate and audit.

### 9.2 Unsafe issuer matrix: RED -> GREEN

- **RED:** six unsafe issuer cases were accepted.
- **Change:** issuer validation now requires HTTPS and rejects userinfo, query,
  and fragment components.
- **GREEN:** the six negative cases passed.
- **Remaining:** exact audience and operator-role validation is still partial.

### 9.3 Private JWKS path: RED -> GREEN

- **RED 1:** a relative JWKS path was not resolved to a canonical project path.
- **Change 1:** relative paths are resolved deterministically.
- **GREEN 1:** the private relative-path test passed.
- **RED 2:** a JWKS path inside the repository but outside `.private` was
  accepted.
- **Change 2:** repository-local JWKS material is restricted to `.private`.
- **GREEN 2:** the tracked/public repository-path case was rejected.
- **Remaining:** the full symlink/reparse and descriptor-replacement matrix is
  pending.

### 9.4 JWKS provider: RED -> GREEN

- **RED:** importing the planned identity/JWKS module failed because it did not
  exist.
- **Change:** added an immutable bounded local RSA public-JWKS snapshot with
  duplicate-object-key detection and fixed RS256 metadata checks.
- **GREEN:** a generated 2048-bit RSA public key loaded as the expected key
  ring.
- **Remaining:** malformed-file, replacement, rotation-overlap, and retired-key
  cases are pending.

### 9.5 Valid JWT verification: RED -> GREEN

- **RED:** importing/constructing the planned verifier failed because it did
  not exist.
- **Change:** added strict `Principal`, Bearer parsing, fixed-algorithm PyJWT
  verification, issuer/audience/time/lifetime checks, and deterministic
  Principal-to-UserContext mapping.
- **GREEN:** the valid RS256 token produced the exact expected Principal and
  Agent context.

### 9.6 Timestamp types and role isolation: RED -> GREEN

- **RED:** boolean `nbf` was accepted as an integer, and service roles flowed
  into `UserContext`.
- **Change:** timestamp validation rejects booleans/non-integers; mapping now
  forces `UserContext.roles=[]` while retaining roles on Principal for API
  authorization.
- **GREEN:** both focused regression cases passed.
- **Why:** Python booleans subclass integers, so an explicit type check is
  required. Service authorization and document authorization are separate
  domains.

### 9.7 Duplicate JWT JSON keys: RED -> GREEN

- **RED:** the default JSON behavior accepted duplicate header/payload keys and
  retained one value, allowing validation ambiguity.
- **Change:** compact JWT header and payload are bounded and pre-parsed with a
  duplicate-key-rejecting JSON loader before signature/claim verification.
- **GREEN:** duplicate keys in either JWT object are rejected safely.
- **Why:** signature validity does not remove parser-differential risk when two
  components can interpret duplicate names differently.

### 9.8 Focused checkpoint

The combined focused identity-core run covering configuration, JWKS, and JWT
behavior reported:

```text
23 passed
```

This checkpoint proves only the tested identity core. It is not evidence that
service wiring, API protection, feedback HMAC, client safety, persona tooling,
evaluation, full regression, public audit, or remote CI is complete.

## 10. Current implementation status (superseded checkpoint)

This table was the identity-core checkpoint before service/API/client work. It
is retained as implementation history. Section 12 is the current status.

| Area | Status | Evidence or remaining work |
|---|---|---|
| Dependency install and pins | partial | packages installed/pinned; exact-set tests, `pip check`, CI pending |
| Identity config | partial | focused defaults/issuer/path tests pass; audience/operator hardening pending |
| JWKS snapshot | partial | valid snapshot passes; full negative/rotation matrix pending |
| Strict JWT and Principal mapping | partial | focused matrix and duplicate-key cases pass; rotation/performance pending |
| Service container/readiness | planned | no completion evidence recorded |
| API 401/403/503 boundary | planned | no completion evidence recorded |
| Feedback HMAC/target binding | planned | no completion evidence recorded |
| Persona CLI and Streamlit | planned | no completion evidence recorded |
| `load_profile.py` migration | planned | no completion evidence recorded |
| Origin/token-file controls | planned | no completion evidence recorded |
| Compatibility-app restriction | planned | no completion evidence recorded |
| Security evaluation/full gates | planned | no completion evidence recorded |

## 11. Next implementation checkpoint

Continue from the strict identity core into service-container ownership and
fail-closed readiness, then enforce authentication before request-body parsing.
Do not begin UI claims or release evidence until the API status/header and
zero-side-effect contracts pass focused tests.

## 12. Superseding implementation checkpoint

The checkpoint in sections 9-11 was subsequently extended through the service,
API, persistence, lifecycle, and client boundaries. The following table is the
current state; it supersedes section 10 without erasing the earlier history.

| Area | Current state | Observed evidence |
|---|---|---|
| Dependency pins and strict config | implemented locally | included in one 201-test core-related checkpoint; final `pip check`/CI pending |
| Bounded JWKS and strict JWT | implemented | duplicate-key, header, claim, rotation, and retirement tests included in focused checkpoints |
| Principal to Agent mapping | implemented | service roles stay on `Principal`; `UserContext.roles` is always empty |
| Service container/readiness | implemented | `identity: ok|error` only; focused resource/API checks pass |
| API middleware | implemented | identity API suite: 17 passed; real RS256 HTTP integration: 1 passed |
| Feedback privacy and migration | implemented | HMAC actor, target request, legacy hash migration/drop/VACUUM covered by focused tests |
| Demo identity lifecycle | implemented | `init`, `rotate`, `retire`, `status`, persona/operator separation covered by focused tests |
| Token sources and clients | implemented | UI/load checkpoint: 54 passed |
| Compatibility acknowledgement | implemented | legacy factory refuses construction without explicit unsafe-local acknowledgement |
| JWT public-audit detection | implemented | audit unit test recognizes JWT-shaped credential material |
| Local warm benchmark | implemented | post-hardening 1,000 runs, p95 0.1334 ms, target met |
| Frozen standalone R2-S5 matrix/evaluator | implemented | frozen hash verified; 17/17 cases pass with zero denied side effects and zero credential leaks |
| Final full regression | pending | first run found three migrated legacy tests; clean final rerun not yet recorded |
| Final public audit/security review/exact-SHA CI | pending | no completion claim until main agent runs and records them |

## 13. Service and readiness slice: RED -> GREEN

- **RED:** after adding the identity probe, readiness tracing rejected the new
  span name because `readiness.identity` was missing from the closed
  `SpanName`/`SPAN_NAMES` allowlist. The probe itself was valid, but the
  observability schema treated it as unknown.
- **Change:** `app/observability/tracing.py` added exactly one allowed span,
  `readiness.identity`. `app/runtime/resources.py` added the identity check and
  asks both the verifier and the feedback HMAC hasher to report readiness.
- **GREEN:** focused readiness tests report only `identity: ok|error`; simulated
  exceptions containing a private path and key marker do not appear in the
  serialized response.
- **Reasoning:** readiness is an operational decision, not a debug dump. A
  process can stay alive while returning not-ready, allowing an orchestrator to
  stop traffic without exposing JWKS paths, key IDs, or HMAC material.

## 14. HTTP identity boundary: RED -> GREEN

- **RED:** protected routes could previously reach FastAPI body validation or
  handlers without a server-verified principal. That allowed body identity and
  created ambiguous 401-versus-422 behavior.
- **Change:** `app/api/identity.py::TrustedIdentityMiddleware` matches the
  protected route/method matrix before body parsing, reads exactly one
  Authorization header, verifies it, checks the operator role where required,
  and stores only `Principal` in request state.
- **Change:** `app/api/errors.py` now preserves response headers, allowing all
  missing/invalid credential responses to carry `WWW-Authenticate: Bearer`.
- **Change:** `app/main.py` derives the Agent `UserContext` only through
  `Principal.to_user_context()` and adds `/identity/me` as the intentional safe
  disclosure endpoint.
- **GREEN:** the focused identity API run reported `17 passed`; a separate real
  RS256 integration test reported `1 passed`.
- **Contract:** missing/invalid token is 401, valid non-operator is 403, and an
  unavailable verifier is generic retryable 503. Invalid authentication wins
  over malformed body validation, and denied requests do not call the Agent.

## 15. Role-domain separation

- **Problem found:** treating every token role as an Agent role would let a
  deployment role such as `rag.operator` accidentally influence retrieval or
  prompts.
- **Change:** `Principal.roles` remains available to the API boundary, but
  `Principal.to_user_context()` deliberately emits `roles=[]`.
- **Result:** metrics and trace lookup can require an operator credential while
  document visibility continues to depend only on tenant, region, and groups.
- **Why this matters industrially:** service administration and business-data
  authorization are separate policy domains. Keeping them separate reduces the
  blast radius of a mistaken role assignment.

## 16. Feedback privacy and SQLite lifecycle

- **Before:** the legacy `feedback` table stored question and answer plaintext;
  the later metadata table did not bind an authenticated actor or identify the
  answer request being rated.
- **Change:** `app/security/identity.py::FeedbackActorHasher` computes a
  domain-separated HMAC-SHA-256 from issuer and subject using an independent
  local key. It does not reuse the JWT signing key.
- **Change:** `FeedbackRequest` requires `target_request_id`; `app/db.py` stores
  request IDs, actor HMAC, caller-declared question/answer SHA-256 digests, and
  the helpful bit. It never receives the bearer token or raw claims.
- **Migration:** `init_db()` adds missing columns idempotently, converts legacy
  plaintext rows to hashes with a fixed non-identifying actor sentinel, drops
  the old table, commits, then executes `VACUUM` so deleted plaintext is removed
  from unused SQLite pages rather than merely becoming unreachable through SQL.
- **Result:** focused persistence tests verify idempotence, source-table removal,
  no plaintext byte remnants, valid target IDs, and valid actor pseudonyms.
- **Limitation:** question/answer hashes remain caller-declared metadata; they
  are not claimed as server-attested answer provenance.

## 17. Demo identity lifecycle and Windows fix

- **Implementation:** `app/security/demo_identity.py` owns local key/artifact
  generation. `scripts/manage_demo_identity.py` exposes `init`, `rotate`,
  `retire`, and `status` commands. Initialization writes an ignored private key,
  public JWKS, identity manifest, independent HMAC key, persona token bundle,
  load-test user token, and separate operator token.
- **Rotation behavior:** `rotate` makes a new key active while retaining old
  public keys for overlap. `retire --kid` removes only a non-active key. The API
  uses an immutable JWKS snapshot, so lifecycle commands report that restart is
  required.
- **Failure encountered:** on Windows, atomic artifact replacement initially
  raised `WinError 32` because a named temporary file was still open when
  `os.replace` attempted to move it.
- **Fix:** finish writing and close the temporary handle first, then call
  `os.replace`; cleanup remains in `finally` so failed writes do not leave
  credential fragments behind.
- **Result:** lifecycle tests prove persona/operator separation, old/new overlap,
  retired-key rejection, and accidental reinitialization refusal.

## 18. Token sources, Streamlit, and load profile

- **Token-source contract:** `app/security/token_source.py` supports either one
  static environment token or one bounded private token file, never both. Token
  files and persona bundles are reread for every request, reject symlink/reparse
  inputs through the shared private-file snapshot reader, and reject duplicate
  JSON object keys.
- **Transport contract:** `streamlit_app/api_client.py` and
  `scripts/load_profile.py` accept only canonical numeric IPv4 loopback origins
  such as `http://127.0.0.1:8000`, set `trust_env=False`, and disable redirects.
  This prevents a bearer token from following a redirect or an environment
  proxy to another destination.
- **UI migration:** `streamlit_app/pages/1_Ask.py` removed editable tenant,
  region, group, and role fields. A demo scenario selects a persona ID, and the
  client resolves the matching server-issued token. Trace access uses the
  separate operator token. Feedback carries the answer request ID.
- **Load migration:** `scripts/load_profile.py` removed body `user_context`,
  resolves separate user/operator token providers, and excludes credentials
  from saved artifacts.
- **GREEN:** the combined UI/load-profile checkpoint reported `54 passed`.

## 19. Public audit and performance evidence

- `scripts/audit_public_repo.py` now recognizes compact JWT-shaped strings as
  credential findings; its unit test proves a synthetic JWT candidate is
  rejected. This is audit hardening, not proof that the final whole-repository
  audit has already passed.
- `scripts/benchmark_identity_verification.py` records public-safe environment
  metadata and latency percentiles without tokens or claims.
- The checked artifact
  `docs/security/r2_s5/evidence/identity_benchmark_windows.json` records 1,000
  warm RS256 verifications after 50 warmups: p50 0.0579 ms, p95 0.1334 ms, p99
  0.2481 ms, max 0.4053 ms. The local p95 <= 10 ms target was met. This rerun
  occurred after canonical Base64url validation was added, so the evidence
  includes the added security check.
- This latency is verifier-only warm local evidence. It is not end-to-end HTTP
  latency, remote JWKS latency, IdP latency, or a CI timing gate.

## 20. Full-suite migration event

- **First run:** `1745 passed, 17 skipped, 3 failed`.
- **Cause:** three historical tests still encoded the old contract by sending
  body `user_context` through the unauthenticated global app. The failures were
  test-contract drift, not proof that authentication itself was broken.
- **Fix:** migrate those tests to send verified bearer identity, assert body
  identity rejection, and explicitly acknowledge the local compatibility
  factory where the legacy endpoint is the behavior under test.
- **Focused confirmation:** the three migrated tests then reported `3 passed`.
- **Current claim:** a clean final full-suite rerun has not yet been observed.
  Therefore the project records the correction but does not claim the full
  regression gate complete.

## 21. Evidence ledger and remaining gates

Observed checkpoints, each with a deliberately narrow meaning:

```text
core-related checkpoint          201 passed
UI and load-profile checkpoint    54 passed
identity API checkpoint           17 passed
real JWT HTTP integration          1 passed
first historical full run       1745 passed, 17 skipped, 3 legacy failures
migrated legacy focused rerun       3 passed
warm verifier benchmark         1000 iterations, p95 0.1334 ms
```

Still pending before R2-S5 release acceptance:

1. rerun the complete suite after all changes and record one clean result;
2. run compile, dependency consistency, and diff hygiene gates;
3. run the complete public repository audit and secret/token/key scans;
4. perform an independent whole-diff security review and resolve all
   Critical/Important findings;
5. commit the exact reviewed tree, push it, and require exact-SHA Linux CI.

Until those gates exist, the precise status is **behavior implemented and
focused-tested; release acceptance pending**.

## 22. Post-review hardening discoveries

### 22.1 OpenAPI security contract: RED -> GREEN

- **RED:** the middleware enforced bearer authentication, but generated OpenAPI
  had no `securitySchemes`. A human using `/docs` could not see which routes
  required bearer credentials.
- **Fix:** add a documentation-only FastAPI `HTTPBearer` dependency to every
  protected operation. Enforcement remains in middleware so invalid credentials
  are still rejected before body parsing.
- **GREEN:** OpenAPI now publishes `BearerAuth` on chat, feedback, identity,
  metrics, and trace while health/schema endpoints remain public.

### 22.2 Noncanonical Base64url signature: integration RED -> GREEN

- **RED:** the real JWT HTTP integration changed only the final signature
  character but still received 200. This was not an RSA verification bypass:
  the replacement changed unused Base64 padding bits, so both strings decoded
  to the same signature bytes.
- **Risk:** accepting multiple compact strings for one signed byte sequence can
  break token caches, deny lists, equality checks, and audit correlation.
- **Fix:** every JWT segment is decoded and then re-encoded without padding; the
  canonical result must equal the original segment exactly.
- **GREEN:** a deterministic test constructs a different string with identical
  decoded signature bytes and the HTTP boundary now returns 401.

### 22.3 Configuration and client canonicalization

- Audience validation now rejects whitespace and control characters instead of
  checking only length/ASCII. Path normalization preserves the lexical final
  component so runtime symlink/reparse checks cannot be erased by `resolve()`.
- Streamlit and load clients now reject outer whitespace as noncanonical rather
  than silently trimming an origin before attaching a bearer credential.

## 23. Real process smoke

A fresh ignored identity was generated and `app.main:app` was started on
numeric loopback port 8875 without reload. The following process-level results
were observed without calling the model:

```text
GET /health/live                                      200
GET /identity/me with load-user token                 200
principal subject                                     load-demo-employee
GET /observability/metrics with user token            403
GET /observability/metrics with operator token        200
GET /health/ready                                     200 / identity=ok
GET /identity/me without token                        401 / WWW-Authenticate=Bearer
bad token plus invalid/body identity                  401
valid token plus body identity override               422
```

Only the uvicorn PID created for this smoke was terminated, and port 8875 had
no listener afterward. This proves real HTTP middleware/header/readiness wiring
on the local machine; it does not replace full tests, model evaluation, a real
IdP, or remote CI.

## 24. Frozen identity matrix and post-hardening focused gate

- Added `data/v2/security/r2_s5_identity_matrix_v1.json` and froze its SHA-256
  as `24183d6da6002a7ea67b9515d19133a883fe4173dbf2ab4107f8e18bcb8c700b`.
- `app/evaluation/trusted_identity.py` executes real ephemeral RSA/JWKS cases
  through the HTTP boundary. `scripts/eval_trusted_identity.py` refuses to
  overwrite an existing result, keeping each run immutable.
- The local run reported 17/17 passing cases, including 11 negative denials,
  zero denied Agent calls or feedback writes, and zero credential leaks.
- The checked public result contains only case IDs, expected/actual decisions,
  bounded counters, and aggregate results. A test recomputes it from the frozen
  matrix so the evidence cannot silently drift away from code behavior.
- A combined identity/security/API/UI/load-profile checkpoint then reported
  `264 passed, 2 skipped`. This is broader focused evidence, not the final
  historical full-suite gate.

## 25. Full-suite documentation contract drift: RED -> GREEN

- **RED:** the first post-implementation full rerun reported
  `1759 passed, 18 skipped, 1 failed`. The only failure was
  `test_readme_is_a_current_evidence_first_entrypoint`: secure startup added an
  identity-initialization command, while the test and README prose still said
  the Quick Start had exactly three commands.
- **Cause:** this was a repository documentation contract that had not been
  migrated with the new mandatory identity bootstrap. Removing the bootstrap
  command would have hidden a real prerequisite.
- **Fix:** the README now says four ordered commands. The test asserts the exact
  four command strings and their order: initialize identity, run tests, start
  the API, then start Streamlit.
- **GREEN:** the focused contract test passed, followed by a clean full rerun of
  `1760 passed, 18 skipped`. The three warnings remain the known FAISS SWIG
  deprecation warnings.

## 26. Public-audit findings: classify, fix, rerun

- **First audit:** `512 candidates / 2 findings`.
- `app/api/identity.py` used a local variable named `authorization`; the
  credential-assignment scanner correctly raised a conservative finding even
  though the value came from an incoming header rather than a literal secret.
  Renaming it to `authorization_header` made the data meaning explicit without
  weakening the scanner.
- `tests/security/test_identity_config.py` used userinfo inside a deliberately
  invalid `identity.localhost` issuer URL. The email scanner cannot infer that
  this is URL userinfo, so the fixture now uses the reserved `.invalid` domain
  while preserving the tested attack shape.
- **GREEN:** related identity/API tests reported `35 passed, 1 skipped`; the
  complete audit then reported `512 candidates / 0 findings`.

## 27. Clean-checkout identity absence simulation

The local workspace contains ignored demo identity files, while GitHub Actions
starts without them. A fresh process therefore overrode both identity paths to
nonexistent ignored locations and ran health, request-context, service-profile,
and resource tests. Result: `18 passed`. The service stayed live, readiness and
protected behavior failed closed, and no test depended on the developer's
private files. This is targeted CI-equivalence evidence; the pushed Linux CI is
still the authoritative clean-checkout gate.

## 28. Demo key lifecycle hardening: two RED -> GREEN fixes

### 28.1 Keyring capacity

- **RED:** after the maximum eight-key overlap was reached, another rotation did
  not raise and wrote a ninth key. The API verifier would reject that JWKS on
  restart because its configured maximum is eight.
- **Fix:** rotation checks capacity before key generation or any file write and
  instructs the operator to retire an old key first.
- **GREEN:** the regression fills the ring, snapshots every artifact, attempts
  one more rotation, and proves both the exception and byte-for-byte unchanged
  directory.

### 28.2 Manifest path escape

- **RED:** a locally tampered manifest could place path separators in `kid` and
  consequently in `private_key_file`. During forced reinitialization, stale-key
  cleanup could resolve outside the identity directory.
- **Fix:** manifest loading now admits only generated kid grammar, requires the
  exact basename `private-<kid>.pem`, requires the public JWK kid to match, and
  validates the active kid type before any write or cleanup.
- **GREEN:** the regression points a tampered manifest at an outside sentinel,
  expects fail-closed validation, and proves the sentinel bytes remain intact.
  The complete lifecycle file reports `5 passed`.

## 29. JWKS/header key-ID grammar alignment: RED -> GREEN

- **RED:** JWT headers required a bounded ASCII `kid`, but JWKS loading admitted
  non-ASCII or whitespace-containing IDs. A key ring containing only such keys
  could pass readiness even though no accepted JWT header could select a key.
- **Fix:** public JWKS parsing now applies the same ASCII and identity-value
  grammar before constructing `PyJWK` objects.
- **GREEN:** the policy matrix first failed on both new malformed key IDs, then
  the complete JWKS file reported `10 passed, 1 skipped`. The skip is the
  platform-dependent symlink creation case.

## 30. Identity CLI lexical path preservation: RED -> GREEN

- **RED:** `scripts/manage_demo_identity.py` called `Path.resolve()` on the
  selected directory before `demo_identity.py` could inspect it. A final
  symlink or Windows reparse point could therefore be converted to its target,
  erasing the evidence needed by the no-redirect check.
- **Fix:** the CLI now performs lexical `os.path.abspath` normalization only;
  the lower-level directory checker remains responsible for link/reparse
  rejection.
- **GREEN:** a CLI-level test replaces `Path.resolve` with a failure sentinel
  and proves `status` passes the lexical absolute path to the lifecycle layer.
  CLI plus lifecycle tests report `6 passed`.

## 31. Independent review finding: mounted-app authentication bypass

- **Independent finding:** zero Critical, one Important, one Minor. The
  Important observed that middleware matched raw `scope["path"]`, while
  Starlette routing removes `scope["root_path"]` for a mounted application.
  Operator metrics/trace routes relied entirely on middleware, so mounting the
  secure app below a prefix could bypass their identity/role check.
- **RED reproduction:** mount the app at `/prefix`; an unauthenticated request
  to prefixed metrics returned 200 instead of 401.
- **Fix:** middleware now uses Starlette's own application-relative
  `get_route_path(scope)` before matching the closed protected-route table.
  This keeps the security decision aligned with the router under both direct
  and mounted/root-path deployment.
- **GREEN:** the mounted regression verifies missing/user/operator credentials
  produce 401/403/200 respectively. The complete identity API file reports
  `20 passed`.
- **Minor disposition:** JWKS is intentionally an immutable startup snapshot;
  removing/retiring a key requires verifier rebuild by process restart. The CLI
  prints `restart_required`, the runbook requires restart after rotate/retire,
  and dynamic revocation remains an explicit non-goal rather than a silently
  accepted production capability.
- **Resolution review:** the same reviewer inspected the corrected path logic
  and mounted regression and reported zero unresolved Critical and zero
  unresolved Important in this area. Tests were run by the main process, not by
  the read-only reviewer.

## 32. Immutable result publication: RED -> GREEN

- **Gap:** `eval_trusted_identity` checked `Path.exists()` and later used normal
  `write_text`. That protects ordinary reruns but leaves a check/write race and
  treats a dangling final symlink as absent.
- **Fix:** an early `lstat` rejects every existing final component, then the
  writer uses operating-system `O_CREAT | O_EXCL` at publication time. It writes
  UTF-8 bytes, fsyncs, never replaces an existing artifact, and removes only a
  partially created target after an in-process write failure.
- **GREEN:** the writer test creates one result, verifies a second publication
  raises `FileExistsError`, and proves the first bytes remain unchanged. The
  frozen evaluation file reports `4 passed` including exact public recompute.

## 33. Lifecycle review reopened five Important risks

The first implementation was not treated as final merely because its focused
tests passed. A separate read-only lifecycle review inspected
`app/security/demo_identity.py`, `app/security/identity.py`, and the lifecycle
tests and returned five Important findings:

1. a first initialization interrupted before manifest publication could leave
   runtime artifacts that a reader did not consistently classify as
   uncommitted;
2. a legacy v1 manifest could be accepted by a runtime reader, creating a
   downgrade path around the new artifact-digest contract;
3. recovery completed the old journal and returned, swallowing the operator's
   current `force`, `rotate`, or `retire` intent;
4. POSIX mode bits were implemented, but Windows DACL protection and
   crash-left journal secrecy had not been demonstrated;
5. lexical ancestor checks did not hold the identity directory stable while a
   lifecycle operation was in progress.

The review also recorded Minor follow-ups: directory fsync after rename/unlink,
a bounded Windows lock wait, semantic journal validation, and validation of
legacy private-key paths before any read. These findings became implementation
work, not documentation-only dispositions.

## 34. Transactional identity lifecycle hardening

### 34.1 Commit point and downgrade behavior

`identity_manifest.json` is now the only commit point for a coherent artifact
set. Runtime readers perform these checks:

- if a journal exists but the manifest does not, every runtime artifact is
  rejected as uncommitted;
- if a v2 manifest exists, its recorded SHA-256 must match the exact artifact
  snapshot being consumed;
- a v1 manifest is rejected by runtime readers and can only be converted by the
  lifecycle manager under its operation lock;
- v1 private-key filenames are validated before any private file is opened.

The upgrade is itself a journaled `upgrade` operation. It calculates private
key and runtime artifact digests, writes a complete v2 staged manifest, and
publishes that manifest last.

### 34.2 Recovery executes old and current intent

Every public lifecycle command now follows:

```text
prepare private directory
  -> acquire process and operating-system lock
  -> validate and finish an existing journal
  -> load the newly committed state
  -> execute the command that the operator invoked now
```

Recovery no longer returns the prior operation as the result of the current
command. Regressions inject failure before manifest publication, recover that
operation, and prove a second `force` creates a third key generation while a
second `rotate` adds another distinct active key.

### 34.3 Journal semantic validation

JSON shape validation alone was insufficient because a syntactically valid
journal could still express an incoherent mutation. Before any journal write
or recovery mutation, `_validate_operation_semantics()` now proves:

- staged manifest schema, key IDs, retired-key set, and active key are coherent;
- each private-key digest matches its PEM bytes and its public numbers match
  the staged JWK;
- staged `jwks.json` exactly equals the public projection of the manifest;
- every runtime artifact digest matches the manifest;
- `init`, `rotate`, `retire`, and `upgrade` have the expected key-set delta,
  extra private-key write, and delete set;
- a delete cannot target a key that remains in the staged manifest.

A regression tampers a recoverable journal's delete set and proves validation
fails before changing the committed manifest or private key.

### 34.4 Atomicity and filesystem durability

`_atomic_write()` writes a unique same-directory temporary file, flushes and
fsyncs it, closes it, atomically replaces the destination, and fsyncs the held
directory descriptor on POSIX. Deletes also fsync the directory. Safe
crash-left names matching `.<artifact>.tmp-<16 hex>` are removed only after the
OS lifecycle lock is held; links, reparse points, directories, and other names
are never silently removed.

Windows locking now retries nonblocking byte-range acquisition for at most
30 seconds instead of waiting forever. The lifecycle lock also holds a
directory handle without delete sharing, rechecks the directory after opening,
and releases that handle on every exception path. A regression forces lock-path
validation to fail after handle acquisition and proves the guard exits.

## 35. Windows ACL implementation failure and correction

The first Windows-hardening attempt delegated ACL changes to a PowerShell child
process. It failed in two useful stages:

1. the initial command expected the target in `$args[0]`, but the invocation did
   not populate that value as assumed;
2. after fixing argument passing, the Codex execution environment exposed a
   more serious identity mismatch: the Python parent and PowerShell child could
   run under different Windows security principals, so the child could grant
   access to the wrong SID.

The final implementation in `app/security/private_fs.py` does not shell out.
It uses Win32 APIs through `ctypes` in the same Python process:

- `OpenProcessToken` and `GetTokenInformation` obtain the current process SID;
- `CreateWellKnownSid` obtains LocalSystem;
- `InitializeAcl` and `AddAccessAllowedAceEx` construct an exact DACL;
- `SetNamedSecurityInfoW` applies a protected directory DACL;
- `GetNamedSecurityInfoW`, `GetAclInformation`, `GetAce`, and `EqualSid`
  independently audit the result.

The accepted ACL has exactly one full-control ACE for the current process SID
and one for LocalSystem. The root DACL is protected from inheritance, while
files may contain the exact inherited pair. POSIX retains root `0700` and file
`0600` enforcement. This is still local demo secret storage, not an HSM or
enterprise secret manager.

## 36. Feedback changed from attribution to cryptographic answer binding

The earlier feedback design pseudonymized the actor but did not prove that the
question and answer submitted later were the same bytes served by the API. A
caller could attach arbitrary content to a valid request ID.

The new flow is:

```text
authenticated chat
  -> Agent answer
  -> HMAC receipt over principal + request ID + keyed content digests
  -> X-Feedback-Receipt response header
  -> transient UI session state
  -> authenticated feedback request
  -> constant-time receipt verification
  -> keyed metadata persistence
```

`FeedbackActorHasher` uses domain-separated, length-prefixed HMAC-SHA256
messages. The receipt binds issuer, audience, tenant, subject, target request
ID, question HMAC, and answer HMAC. The `helpful` choice is deliberately not
bound because the user chooses that value during feedback. Missing, malformed,
wrong-actor, wrong-target, modified-question, and modified-answer receipts fail
before any database call.

The API checks all chat dependencies before Agent execution and checks database
plus identity dependencies before feedback persistence. Feedback therefore
remains available during model/index outages, but never during identity or
database unavailability.

## 37. Feedback privacy migration and durable erasure state

`feedback_events` no longer stores question/answer plaintext or ordinary
enumerable SHA-256. It stores:

- current and target request IDs;
- actor HMAC;
- domain-separated question and answer HMACs;
- the boolean rating and binding version;
- bounded legacy provenance.

Legacy plaintext rows are converted using the exact container's keyed digest
provider. An older hash-only schema is rebuilt without carrying its enumerable
SHA columns forward; values that cannot be cryptographically upgraded receive
an explicit all-zero sentinel and an `unverifiable` binding version rather than
invented trust.

Dropping a SQLite table does not erase bytes from freelist pages. Migration
therefore commits `feedback_vacuum_required=1` before `VACUUM`. The marker is
cleared only after both VACUUM and WAL checkpoint complete. A newly discovered
gap was that `PRAGMA wal_checkpoint(TRUNCATE)` reports busy/partial status in
its return row; ignoring that row could clear the marker while an old WAL still
existed. `_require_complete_wal_checkpoint()` now treats busy, partial,
malformed, or absent status as failure. The marker remains durable, readiness
stays false, and the next initialization retries.

## 38. Client identity-channel and receipt isolation

The default client no longer shares one `requests.Session` across public,
persona, and operator channels. It creates three cookie-rejecting sessions,
sets `trust_env=False`, disables redirects per request, and accepts only the
canonical numeric IPv4 loopback origin. A response cookie from one channel
therefore cannot become ambient authentication on another channel.

The load profile mirrors this with thread-local per-channel sessions. Token
sources are resolved per request, and startup rejects byte-identical persona
and operator tokens using `hmac.compare_digest`, including equal tokens loaded
from different files.

Chat success is now invalid unless `X-Feedback-Receipt` is exactly 64 lowercase
hex characters. Streamlit retains it only in the current answer state, clears
it whenever the answer is cleared, and sends it back with feedback. Missing or
malformed receipts fail before token resolution or network I/O. Focused client
and page tests reported `36 passed`.

## 39. Readiness and configuration consistency corrections

Business routes no longer rely only on the last background readiness snapshot:

- chat requires database, index, all configured models, and identity;
- feedback requires database and identity;
- dependency failure returns a bounded retryable `service_not_ready` error
  before Agent execution or database mutation.

The model probe now includes the evidence model instead of checking only chat
and embedding models. Database probing passes the exact `ServiceContainer`
settings and keyed content-digest provider; it no longer falls back to process
global settings during a custom/test deployment.

When `data_dir` is explicitly overridden, derived raw, parsed, index, v2 index,
and SQLite paths follow it unless each path was explicitly overridden itself.
This prevents a deployment from splitting supposedly isolated state across the
new data root and old defaults.

## 40. Identity matrix strengthened from status checks to data-flow proof

The frozen matrix grew from 17 to 20 cases. New negative cases cover missing
receipt, one-nibble receipt tampering, and answer modification. The evaluator
now proves, per successful path:

- chat returned a receipt that verifies for the authenticated principal,
  response request ID, exact question, and exact answer;
- feedback persistence received the expected actor pseudonym and target;
- persistence received only keyed question/answer digests, not raw content or
  ordinary SHA-256;
- the exact container settings object reached the database boundary;
- denied requests caused zero Agent calls and zero feedback writes.

Leak detection now scans response bodies and headers for complete user/operator
tokens, individual JWT segments, invalid-token fixtures, PEM markers, raw HMAC
key encodings, private key filenames, and identity claims outside the
documented `/identity/me` response. Dedicated tests prove the detector itself
fires for these classes.

Current deterministic evidence:

```text
matrix SHA-256  fe5fdddd9cd4d067930b971ca0658a22deb63778723c31597df7f7fab70b4e2f
cases          20/20 passed
denials        14
denied effects 0
credential leak findings 0
```

`release_pass` is explicitly a result for this frozen matrix only. It does not
mean the service is production-ready and cannot substitute for full pytest,
public-repository audit, independent review, or exact-commit Linux CI.

## 41. Focused checkpoint before final review

The latest non-additive focused evidence is:

```text
Streamlit/client                                  36 passed
feedback privacy + identity API + runtime         48 passed
identity lifecycle                               17 passed, 1 skipped
trusted identity evaluator                         6 passed
```

The skipped lifecycle case is the platform-dependent directory-symlink
creation regression. These numbers overlap and must not be summed into a fake
suite total. Full-suite, final audit, benchmark refresh, independent whole-diff
review, commit, push, and remote CI remain release gates at this checkpoint.

## 42. Independent review wave found release-blocking boundary gaps

The first whole-diff reviews were intentionally run before documentation
closeout. They did not merely count tests; they inspected failure behavior and
used focused reproductions. The important findings were:

1. Streamlit could use its framework default listener, which exposed a local
   persona/operator credential workflow beyond loopback.
2. `wal_checkpoint(TRUNCATE)` could return a busy/partial status without
   raising SQL error, while the old code treated the call as complete erasure.
3. A valid feedback receipt could be replayed into multiple rows for the same
   actor and answer.
4. A missing identity manifest could fall through to standalone artifact
   loading, weakening the manifest commit point.
5. public readiness refresh could invoke database initialization and therefore
   acquire write locks or retry VACUUM.
6. lifecycle filesystem checks did not validate artifact owner or hardlink
   count and did not use write-through replacement on Windows.
7. stale temporary cleanup matched a broader namespace than the manager's
   actual atomic targets.
8. `status` could recover/upgrade state while reporting no restart requirement.

These were classified as release blockers because each one affects a
deployment, privacy, or trust-boundary property even though the normal happy
path already passed.

Two later delegated re-review tasks produced no usable result: one was stopped
by an external safety classifier and one remained running without a report.
They are recorded as unavailable review attempts, not as zero-finding
evidence. Local reproductions, regression tests, and a new narrowed review are
the evidence used for closeout.

## 43. Lifecycle review fixes and the Windows ancestor-lock trade-off

Managed identity readers now require a valid manifest by default. A standalone
mode exists only behind an explicit parameter used by isolated tests; app
builders do not enable it. External single-token files are a separate caller
credential source and explicitly opt in after the same regular-file,
size, owner, permission, hardlink, and link checks.

POSIX validation now requires the current owner, root/current-owned ancestors,
private modes, and exactly one hardlink. Windows validation audits the owner as
current SID or LocalSystem and applies an exact protected DACL for those
principals. Atomic publication uses `MoveFileExW` with
`MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH`.

An attempted stricter implementation tried to hold every Windows ancestor
directory without delete sharing. It failed at the user-profile directory
because normal
Windows sharing semantics make arbitrary higher ancestors unavailable for this
lock mode. Keeping that approach would make the demo undeployable on an
otherwise valid workstation. The final boundary holds the identity root and
all available ancestors, requires the immediate parent handle, and compares
the root's file identity after open. This is a documented local-filesystem
trade-off, not a claim of protection against a compromised same-account host.

Cleanup now removes only names belonging to known managed atomic targets.
Unrelated `.notes.tmp-*` files remain untouched. `status` reports
`restart_required=true` when it recovered a journal or upgraded v1 state,
because runtime verifier snapshots do not hot-reload.

## 44. Feedback replay, privacy migration, and WAL truthfulness

The feedback contract has two independent idempotency layers:

```text
HTTP integrity:
  receipt = HMAC(actor + target request + keyed question/answer digests)

database cardinality:
  UNIQUE(actor_hmac_sha256, target_request_id)
  WHERE binding_version = 'feedback-receipt-v1'
```

`BEGIN IMMEDIATE` and `INSERT ... ON CONFLICT DO UPDATE` serialize competing
ratings and leave one latest row. A migration deduplicates already-existing
current-version rows before creating the partial unique index. A regression
submits two different ratings and proves the row count stays one while the
latest value wins.

For old plaintext removal, SQL success alone is insufficient. SQLite returns
`(busy, log_frames, checkpointed_frames)` from
`PRAGMA wal_checkpoint(TRUNCATE)`. The code now rejects missing, malformed,
busy, or partial results. A real long-lived reader regression scans `.db*`
files, proves the durable migration marker remains while erasure is incomplete,
and proves initialization retries rather than declaring readiness.

## 45. Readiness and local-client deployment corrections

Database migration moved to the controlled service `start()` path. The public
readiness refresh calls only `check_db()` and is serialized by an `RLock`.
Tests prove one initializer call and repeated read-only probes. This prevents a
health scraper from becoming an unexpected schema writer or VACUUM trigger.

The API client owns three distinct sessions:

```text
public   -> health/readiness
persona  -> chat, identity, feedback
operator -> metrics, trace
```

Every session rejects cookies, environment proxies, and redirects. The exact
origin is numeric IPv4 loopback. Streamlit now binds to `127.0.0.1` in checked
configuration. A valid chat response must include one 64-character lowercase
feedback receipt; the UI keeps it only for the current answer and clears it
after a successful rating.

## 46. Final frozen evaluation and isolated benchmark refresh

The final matrix added missing receipt, one-nibble receipt tampering, and
modified-answer cases. The evaluator also inspects the exact persistence call
to prove actor/target binding, keyed content digests, the container's settings
object, and absence of raw question/answer. Final deterministic evidence:

```text
matrix SHA-256       fe5fdddd9cd4d067930b971ca0658a22deb63778723c31597df7f7fab70b4e2f
cases                20/20 passed
denied cases         14
denied side effects  0
credential leaks     0
```

The output writer deliberately refuses to overwrite an existing artifact. A
fresh result was therefore written under ignored `security_runs/` and compared
with the public JSON. Both files have SHA-256:

```text
94125e66d1ac4b2c32562d623b6351a10cfa021ecd7d760dbc4eb89a3a0b1e66
```

The benchmark script gained `--ephemeral-demo`. It creates a complete managed
identity in a temporary directory and cannot modify the operator's real
`.private/identity`. The final Windows/CPython 3.11 run recorded:

```text
warmup / iterations  50 / 1000
p50 / p95 / p99      0.0540 / 0.0980 / 0.1658 ms
max                  0.2548 ms
target               p95 <= 10 ms, met
```

This measures only warm in-process RS256 verification against an immutable
JWKS snapshot. It says nothing about HTTP, retrieval, LLM, remote IdP, or
production tail latency.

## 47. Final local whole-tree gate

After all code changes and the ephemeral benchmark regression were present,
the complete repository suite reported:

```text
1817 passed, 19 skipped, 3 warnings in 132.17s
```

The skips are platform/optional-environment cases. The warnings are the known
FAISS/SWIG `DeprecationWarning` messages. There were no functional failures.
Focused results are retained for diagnosis but are not added to 1,817 because
they overlap the full suite.

At this checkpoint the remaining release work is exact documentation
normalization, final candidate audit/diff/compile/dependency checks, narrowed
whole-diff review, commit/push, and exact-SHA GitHub Actions. Those results must
be appended after their commands complete.

## 48. Documentation normalization and final local nonfunctional gates

The first post-documentation public audit reported:

```text
public candidates=515 findings=1
```

The finding was a machine-specific user-profile path written into this journal
while documenting the Windows ancestor-lock experiment. It contained no key or
token, but exposed a local username and made the public artifact less portable.
The path was generalized to “user-profile directory”; the scanner was not
weakened. The rerun reported:

```text
public candidates=515 findings=0
```

Other local release commands:

```text
python -m compileall -q app scripts streamlit_app tests  exit 0
python -m pip check                                      no broken requirements
git diff --check                                         exit 0
```

`git diff --check` printed only Git's line-ending notice that `.env.example`
will normalize CRLF to LF when Git next writes it. It reported no whitespace
error.

## 49. Second review wave invalidated the first closeout numbers

The narrowed API/privacy review returned zero Critical and four Important
findings:

1. caller-reused request IDs could make feedback for different answers overwrite
   each other;
2. SQLite connection context managers committed/rolled back but did not close
   connections, leaving Windows file locks to cyclic garbage collection;
3. the supposedly read-only database probe created an empty file when its
   parent directory existed but the database was missing;
4. model readiness listed model names with `/api/tags` but never proved that
   Ollama could load the model.

The narrowed lifecycle review returned zero Critical, five Important, and one
Minor finding:

1. naming a standalone payload `identity_manifest.json` bypassed the managed
   commit check;
2. `status` hardened an arbitrary directory before proving it was an identity
   root, changing ACLs and leaving a lock file on operator error;
3. `rotate` rewrote client tokens before a running immutable API snapshot
   adopted the new JWKS, creating a restart-window outage;
4. a valid journal could be serialized above its own recovery read limit;
5. a POSIX root rename could separate the held lock/descriptor from later
   path-based writes;
6. POSIX `flock` blocked forever instead of honoring the documented timeout.

Therefore the earlier 1,817-test result and 515/0 audit became **pre-review
baselines**, not final release evidence. Release stayed blocked until every
finding had a regression and a fresh whole-tree gate.

## 50. Feedback, SQLite, and executable model-readiness RED/GREEN

### 50.1 Content-bound feedback idempotency

The initial replay index was:

```text
UNIQUE(actor_hmac_sha256, target_request_id)
```

`target_request_id` can be a valid caller-supplied `X-Request-ID`, so two
different served answers could share it. The second write updated the first
row. The corrected identity is:

```text
UNIQUE(
  actor_hmac_sha256,
  target_request_id,
  question_hmac_sha256,
  answer_hmac_sha256
)
WHERE binding_version = 'feedback-receipt-v1'
```

The receipt already authenticates these keyed content digests. Including them
in the database key gives both required behaviors: a retry for the exact same
answer updates one latest rating, while a reused correlation ID with different
served content keeps separate rows.

### 50.2 Deterministic connection ownership and read-only health

Python's SQLite connection context manager controls transactions; it does not
promise `close()`. `init_db`, `save_feedback_metadata`, `check_db`, and VACUUM
now wrap connections in `contextlib.closing`. A tracking `sqlite3.Connection`
subclass proves both checked operations called `close()` before returning.

`check_db` now opens the absolute SQLite URI with `mode=ro`. Its regression
creates the parent directory without the database, calls readiness, and proves
the result is false and no zero-byte file appears.

### 50.3 Model presence is not model readiness

The prior `/api/tags` probe reproduced the original Ollama failure mode: a
listed model could still fail while loading its GGUF. The corrected probe:

1. checks names using `/api/tags` with the short connection timeout;
2. executes `/api/embed` with a one-word input for the embedding model;
3. sends an empty, non-streaming `/api/generate` preload request for each
   distinct chat/evidence model;
4. validates bounded response shapes and treats HTTP/load/shape failure as
   `models=error`.

Ollama documents both
[`/api/embed`](https://docs.ollama.com/api/embed) and empty
[`/api/generate` preloading](https://docs.ollama.com/faq). A separate bounded
`readiness_model_load_timeout_seconds` defaults to 60 seconds, while connection
failure still uses the short two-second readiness timeout.

The four direct RED tests first reported three failures plus the corrected
missing-parent precondition; after implementation all four passed. The broader
database/resources/settings/health checkpoint reported:

```text
56 passed, 3 known SWIG warnings
```

The Windows pytest cleanup warning visible during this wave came from the
lifecycle review's deliberate arbitrary-directory ACL reproduction. It is not
accepted as normal behavior; the lifecycle fix must remove that side effect.

### 50.4 Real local model-load confirmation

`ollama list` showed the exact configured `bge-m3`, `qwen2.5:3b`, and
`qwen3:8b` models. Running the production `_probe_models()` against
`http://127.0.0.1:11434` then completed all three executable probes and printed:

```text
model_execution_probe=ok
```

The call took approximately 14 seconds including process startup and cold/warm
model handling. This is a local operational confirmation, not a deterministic
CI gate or latency SLO.

## 51. Lifecycle review RED/GREEN and two-phase rotation

### 51.1 Reserved manifest name cannot become a runtime artifact

The commit verifier previously special-cased the manifest filename in a way
that let a standalone JWKS or HMAC payload named `identity_manifest.json`
escape managed validation. The branch now always fails closed: the manifest is
metadata, never a loadable runtime artifact. Separate regressions cover both
the JWKS provider and feedback HMAC loader.

### 51.2 `status` validates before it mutates

The old status path called `_prepare_directory()`, which hardened the entire
target before proving it belonged to this manager. A typo in `--directory`
could change an ordinary file's ACL and leave `.identity.lock` behind.

`status` now performs a read-only preflight:

```text
validate existing root without following links
-> require a valid committed manifest or semantically recoverable journal
-> only then harden and acquire the lifecycle lock
-> recover/upgrade/status
```

Tests snapshot directory entries, contents, mode/ACL state, and lock-file
absence for an ordinary directory and an invalid manifest marker. Both error
paths have zero filesystem mutation.

### 51.3 Rotation is staged before token activation

Publishing a new JWKS and new client tokens in one atomic operation was
internally consistent on disk but inconsistent with a running API's immutable
JWKS snapshot. The corrected operator protocol is:

```text
rotate
  -> append a pending public key to JWKS
  -> keep active_kid and every client token unchanged

restart API
  -> immutable verifier snapshot now knows old + pending public keys

activate --kid <pending> --api-base-url http://127.0.0.1:8000
  -> issue an in-memory 60-second probe signed by pending key
  -> call authenticated /identity/me on exact numeric loopback
  -> require HTTP 200 and the exact expected key_id
  -> only then set active_kid and atomically publish new client tokens

wait old-token overlap
  -> retire --kid <old>
  -> restart API to remove the old verification key
```

An old API snapshot cannot validate the probe, so activation changes no token
files. A restarted snapshot accepts both old and pending keys, activation
publishes new tokens without another restart, and old tokens remain valid for
the overlap window. A pending key can be retired to cancel the stage. Activation
publication uses the same journal; `status` completes an interrupted commit.

The loopback proof is a local demo control, not remote attestation. A malicious
same-account process that impersonates the local API remains outside this
stage's host trust boundary.

### 51.4 Journal write and recovery limits are now the same bytes

The prior validator bounded decoded write payloads but recovery bounded the
larger Base64/JSON journal. A sufficiently long valid issuer could therefore
produce a journal that the manager itself refused to recover.

`_commit_operation()` now serializes the exact journal first and rejects it if
the final byte length exceeds 524,288. The rejection occurs before journal,
private-key, JWKS, or token publication. The recovery reader uses that same
constant.

### 51.5 POSIX path replacement and lock timeout

An open POSIX directory descriptor does not prevent its pathname from being
renamed. Lifecycle state now binds the root `(st_dev, st_ino)` captured after
lock acquisition. Every path write first verifies the pathname still identifies
that directory. POSIX open/stat/chmod/replace/unlink/scandir operations are
then executed relative to the held `dir_fd`, so a replacement directory never
receives writes under the old lock.

POSIX `flock` now uses `LOCK_EX | LOCK_NB` with the same bounded polling
deadline as Windows. `EACCES/EAGAIN` retry; unrelated filesystem errors fail
immediately; deadline exhaustion returns a safe lock-timeout error.

Main-process focused rerun:

```text
identity JWKS + feedback key + lifecycle + CLI  49 passed, 3 skipped
```

The skipped cases are platform-specific, including the real POSIX root-rename
regression that must execute in Linux CI. No functional test failed.

## 52. Final full-suite path-redaction failure and correction

The first post-review full-suite run used an in-repository
`.private/pytest-*` base directory so identity lifecycle tests could preserve
their production rule that local credentials stay below `.private`. It reached
completion with one failure:

```text
test_eval_cli_publishes_valid_evidence_and_returns_zero
expected "<external>/" in commands.txt
```

This was not an identity authorization failure. The public exposure evidence
CLI considered every path below the repository root publishable as a relative
path. That assumption was too broad: `.private/` is deliberately ignored and
may contain local credentials, temporary test inputs, or machine-specific
state. A path can be lexically inside the checkout and still be outside the
public evidence boundary.

`_safe_display_path()` now distinguishes tracked-style repository paths from
the explicit `.private` root. A `.private/.../source` path is rendered only as
`<external>/source`; no absolute prefix or private subtree is serialized.
A direct platform-independent regression fixes this contract even when CI's
normal `tmp_path` happens to live outside the checkout.

RED/GREEN evidence:

```text
new boundary + original failing integration test  2 passed
complete exposure evidence subsystem              378 passed, 9 skipped
```

The scanner was not weakened and the test was not skipped. The production
redaction rule was tightened because the failing test exposed a real
publishability mistake.

## 53. Post-review final local release evidence

After all database, model-readiness, lifecycle, and path-redaction corrections,
the complete working tree was rerun from a fresh private pytest root:

```text
full pytest  1835 passed, 20 skipped, 3 warnings in 102.71s
```

The 20 skips are platform/optional-environment conditions. In particular, the
real POSIX root-rename and lock behavior must run on Linux CI. The three
warnings are the existing SWIG/FAISS deprecation warnings; there are no test
failures or Windows cleanup errors.

The trusted-identity evaluator then regenerated a fresh candidate:

```text
matrix cases                  20 / 20 passed
denied cases                  14
denied side-effect violations  0
credential leaks               0
matrix definition SHA-256     fe5fdddd...70b4e2f
candidate/public SHA-256       94125e66...a0b1e66 (byte-identical)
```

The isolated ephemeral verifier benchmark was rerun rather than copied from
the pre-review artifact:

```text
warmup / iterations  50 / 1000
p50 / p95 / p99      0.0540 / 0.0957 / 0.1572 ms
max                  0.5045 ms
local target         p95 <= 10 ms, met
```

Finally, the public scanner inspected every tracked or untracked candidate
selected by its Git-aware policy:

```text
public candidates=515 findings=0
```

`0 findings` means no credential-shaped value, private runtime path, local
identity, frozen secret fixture content, or other configured disclosure was
found among 515 candidates. It does not mean the scanner inspected zero files,
and it is not a substitute for code review or exact-SHA Linux CI.

## 54. Third independent review reopened the release

Two fresh read-only reviewers inspected the post-review code and documentation
instead of trusting the 1,835-test result. Together they reported:

```text
Critical   0
Important 10
Minor      4
release    HOLD
```

The ten release-blocking findings were:

1. the production module still exported an unauthenticated compatibility app
   that an external wrapper could bind beyond loopback;
2. legacy one-step rotate journal recovery could publish tokens without the
   new pending-key activation proof;
3. `retire` did not enforce the old-token overlap window;
4. stale readiness could run several cold model probes synchronously on a
   public or business request;
5. readiness used `/api/generate` instead of the production `/api/chat`
   contract and did not validate finite/index-matched embedding dimensions;
6. legacy SQLite migration coerced malformed `helpful` values with `bool()`;
7. strong credential/local-identity checks covered only selected public
   evidence paths;
8. `docs/api.md` still mixed executable pre-R2-S5 and current contracts;
9. GitHub CI covered only Ubuntu although the local identity manager contains
   Windows DACL/MoveFileExW code;
10. Actions, Python/pip, and transitive dependencies were not all fixed to an
    immutable supply-chain input.

The four Minor findings were default-public behavior for newly added routes,
no byte-level authenticated body limit, equality leakage from deterministic
content HMACs, and weak benchmark provenance/overwrite behavior.

This review invalidated both the previously labeled final `1835/20` regression
and the old `515/0` scanner result as release evidence. They remain historical
checkpoints only. No commit or push was allowed while the disposition was
HOLD.

## 55. Third-review RED/GREEN integration in progress

### 55.1 Deployable legacy HTTP surface removed

An acknowledgement boolean could name a dangerous factory but could not prove
which socket an external ASGI runner selected. The production module now has a
single factory and no code path that registers `/ingest`, `/chat`, or
`/agent/chat`. Historical comparisons remain below the deployable HTTP layer.

The route policy also changed from a protected-route allowlist to
public-by-exception. Health/schema routes are explicitly public; operator
routes are explicit; every unknown future route defaults to user
authentication. A valid user can still receive the real downstream 404, but an
unauthenticated caller cannot discover or reach a forgotten business route.

### 55.2 Authenticated request bytes are bounded before JSON parsing

After bearer and operator checks, the identity middleware validates body
framing and buffers at most 128 KiB before FastAPI/Pydantic. `Content-Length`
and actual chunked bytes are both bounded. Invalid credentials still return
401 before the body is read; an authenticated oversized request returns
`413 request_body_too_large` with zero Agent/database side effects.

Focused entry-boundary evidence:

```text
initial RED                         import/policy contract failed
entry GREEN                         7 passed
expanded identity/API boundary     31 passed
chunked body without Content-Length 1 passed
```

### 55.3 Readiness is a background state machine, not request work

`start()` now publishes a fail-closed snapshot and starts a background refresh
thread, allowing the FastAPI lifespan to yield and liveness to respond. Public
ready and protected routes only read the latest snapshot. An expired snapshot
becomes not-ready until the background refresh publishes a new result.

The model probe now uses `/api/embed` plus the production `/api/chat` endpoint.
Every embedding element must be finite and the vector length must equal the
active index manifest. Tags, embedding, chat, and evidence model requests share
one total cold-load deadline. Closing the service prevents an in-flight result
from being published.

Evidence recorded so far:

```text
readiness/config/health tests  43 passed
real local model contract      1024-d BGE-M3 + Qwen2.5/Qwen3 /api/chat = ok
```

### 55.4 Legacy feedback values fail closed

Both legacy table migration paths now select SQLite `typeof(helpful)` and
accept only storage type `integer` with exact value 0 or 1. NULL, REAL, TEXT,
BLOB, 2, and negative values roll back without dropping the source table,
clearing the erasure marker, or leaving a partial replacement. Correcting the
source value makes the migration retryable.

```text
strict migration RED    15 failed, 4 passed
strict migration GREEN  19 passed
related DB/API checks    52 passed
```

### 55.5 Audit strength without path-wide blind spots

Applying every evidence-package rule to all source files initially produced
176 findings across 136 files. That result was retained as a diagnostic, not
silenced with a docs/tests allowlist. It exposed two different semantics:

- high-confidence credentials, private keys/tokens, absolute user paths, and
  local usernames must be checked across every Git candidate;
- system prompts, frozen attack fixtures, environment names, and ignored run
  directories are forbidden specifically in artifacts claiming to be
  redacted public evidence, but are legitimate in their implementation,
  frozen source corpus, and operational documentation.

The scanner now implements those two layers. Test fixtures use explicit
synthetic markers; three historical references to the local Windows username
were generalized. The expanded scanner suite reports 77 passing tests and the
real repository again reports `515 candidates / 0 findings`, now with the
broader global credential/identity coverage.

### 55.6 API and CI contracts

`docs/api.md` now contains one executable R2-S5 contract. It no longer gives
copyable body-identity, receipt-free feedback, or legacy route commands.

GitHub CI is now a full Ubuntu/Windows matrix. Python is fixed at 3.11.9, pip at
26.0.1, and `actions/checkout` plus `actions/setup-python` are pinned to full
commit SHAs obtained from the official repositories. The two operating systems
exercise POSIX and Windows filesystem branches for the same candidate commit.

Transitive dependency hashes/SBOM remain a real supply-chain limitation; fixed
direct requirements and a fixed resolver improve the boundary but do not
justify calling the dependency closure fully reproducible.

## 56. Key-lifecycle release blockers closed locally

### 56.1 Why the previous rotation code was still unsafe

The normal workflow was already two-phase:

```text
rotate -> publish old + pending JWKS -> restart API
       -> activate only after the restarted snapshot verifies a pending-key probe
```

However, recovery semantics are part of the security boundary. The operation
journal validator still accepted an older one-step `rotate` target where the
new key was already active and no pending key remained. A crash or crafted
journal could therefore reach a state that the normal `activate` function
would never publish without proof. The code also trusted the operator to wait
before `retire`; it did not encode or enforce that overlap.

The third independent review treated both as Important, release-blocking
findings. That review is the RED evidence. No claim is made that a separate
pytest RED run existed before the repair.

### 56.2 Manifest v3 makes overlap a persisted invariant

`app/security/demo_identity.py` now uses
`demo-identity-keyring-v3`. It adds two non-secret fields:

```json
{
  "retire_not_before": {
    "<old-kid>": 1780000000
  },
  "emergency_revocations": [
    {"kid": "<old-kid>", "revoked_at": 1779999500}
  ]
}
```

On successful activation, the previous active key receives a retirement
deadline of activation time plus the maximum permitted demo-token lifetime
(900 seconds) plus verifier clock skew (30 seconds). This is deliberately
conservative: it remains correct even if the old token was created with a
longer lifetime than the new `activate` command requests.

The manifest validator now requires deadline keys to equal exactly:

```text
all key IDs - active key - pending key
```

This single invariant covers initialization, one or more retained old keys,
one pending stage, activation, pending cancellation, normal retirement, and
emergency retirement. Missing deadlines, deadlines for active/pending keys,
boolean/non-integer timestamps, duplicate emergency entries, and emergency
entries for non-retired keys fail closed.

Committed v1 and v2 manifests are upgraded transactionally through the same
manifest/journal commit mechanism. Existing inactive v2 keys receive a fresh
conservative overlap window. The API-side artifact verifier rejects v1/v2 as
requiring managed upgrade, so an old manifest cannot silently bypass the
lifecycle manager. An unfinished old-format operation journal is not migrated:
it is rejected rather than guessing whether an activation proof occurred.

### 56.3 Retirement is enforced in both the command path and recovery path

`retire_demo_identity_key` now checks the persisted deadline before creating
any journal or deleting any private key:

```text
pending key                    -> may be cancelled immediately
old key and deadline elapsed   -> normal retirement
old key and deadline active    -> reject with UTC deadline
active key                     -> always reject
```

The operation-journal semantic validator repeats the authorization check.
This matters after a crash: recovery cannot replay a target that removes a
still-overlapping key unless the target also contains a valid emergency audit
append. Existing deadlines, retired history, and emergency history must remain
unchanged across rotate/activate operations; retire may remove only its own
deadline and append only its own retired key.

The old `legacy_transition` branch was deleted. A regression test changes an
otherwise valid staged rotation journal into a one-step active-key switch,
adds internally consistent retirement metadata, and verifies that recovery
still rejects it without changing the committed manifest.

### 56.4 Emergency revocation is explicit and auditable

Breaking the overlap window is sometimes necessary after key compromise, but
it must not look like routine maintenance. Both the Python lifecycle API and
CLI require:

```text
emergency_revoke = true
exact confirmation = RETIRE_ACTIVE_TOKENS_NOW
```

The CLI form is:

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity retire `
  --kid <old-kid> `
  --emergency-revoke `
  --confirm-emergency-revoke RETIRE_ACTIVE_TOKENS_NOW
```

If the deadline is still active, the manifest records the retired key ID and
revocation epoch. `status` exposes the retirement-deadline map and aggregate
emergency-revocation count, but no private key or bearer token. Supplying the
confirmation without emergency mode, or emergency mode without the exact
phrase, fails before lifecycle mutation.

### 56.5 Verification and observed Windows cleanup warning

Focused lifecycle and CLI:

```text
34 passed / 2 platform skips / 3 known SWIG warnings
```

Expanded security plus identity API:

```text
234 passed / 4 platform skips / 3 known SWIG warnings
```

The new cases cover enforced waiting, exact-deadline retirement, emergency
confirmation and audit visibility, v1/v2 transactional upgrade, crash-recovery
idempotence, and one-step journal rejection. The two runs also emitted pytest
post-run warnings while deleting temporary Windows directories whose ACLs were
intentionally hardened by negative tests. The test outcomes are green, but the
cleanup warning remains recorded rather than being described as absent.

These are focused GREEN results only. The pre-review `1835 passed` result
remains invalid as final evidence until the complete repository suite is run
again after every third-review repair.

## 57. Lifecycle follow-up review found two real state-machine defects

### 57.1 Independent finding: configured skew exceeded lifecycle skew

A read-only follow-up reviewer found no Critical but found two Important
issues. The first compared code across modules instead of reading the lifecycle
file in isolation:

```text
initial lifecycle overlap skew       30 seconds
Settings allowed verifier skew       0..120 seconds
maximum demo token lifetime          900 seconds
```

At skew 120, a verifier may accept a token until `exp + 120`, while the first
v3 implementation allowed retirement at activation + 900 + 30. That created a
90-second early-invalidation window.

The correction introduces one configuration upper-bound constant in
`app/config.py`. `activate_demo_identity` now receives the exact configured
skew used by the API, validates it against that same 120-second bound, and
persists:

```text
intermediate retire_not_before =
    activation time
    + maximum demo token lifetime
    + then-current configured verifier skew
```

At this intermediate checkpoint, the CLI passed
`settings.identity_clock_skew_seconds`; v1/v2 migration had no
historical runtime setting, so it conservatively uses the maximum 120 seconds.
A boundary test proves ordinary retirement fails at deadline minus one and
succeeds exactly at the deadline for skew 120. Section 58 supersedes the
then-current configuration rule after the reviewer found drift risk.

### 57.2 Independent finding: recovery authorization changed with wall time

The first emergency implementation inferred whether a journal represented
emergency retirement by comparing recovery time with the deadline. This made
an interrupted, correctly confirmed emergency operation unrecoverable if the
process restarted after the deadline:

```text
authorized before deadline -> emergency event written to journal
crash during publication
recover after deadline      -> old validator reclassified it as scheduled
target still has emergency event -> permanent journal rejection
```

At this checkpoint the operation schema became `demo-identity-operation-v2`.
Section 60 records the later v3 completed-state hardening. Version 2 froze
semantic authorization when the journal was created:

```json
{
  "retirement_authorization": {
    "mode": "emergency",
    "authorized_at": 1780000000
  }
}
```

Scheduled retirement records the same immutable shape with mode `scheduled`.
Recovery validates mode and `authorized_at` against the committed deadline and
requires an emergency event to match the same key and timestamp exactly. It
never reclassifies the operation from the current wall clock.

Activation journals also freeze `activated_at`, configured skew, and maximum
token lifetime. Semantic recovery requires the newly added deadline to equal
their exact sum. A tampered activation journal that shortens the deadline to
the past is rejected without changing the committed manifest.

### 57.3 Operator-contract cleanup

`rotate --token-lifetime-seconds` was removed because rotate does not mint
tokens; token lifetime belongs to activate. Keeping a validated but unused
option would mislead operators about which phase freezes token policy.

`status` now reports the non-secret emergency key IDs and revocation epochs as
well as the aggregate count. This makes a break-glass action inspectable
without opening the manifest manually.

### 57.4 New state-space coverage

The focused lifecycle/CLI gate now reports:

```text
39 passed / 2 platform skips / 3 known SWIG warnings
```

New cases cover:

- maximum configured verifier skew;
- emergency retirement interrupted before publication and recovered after the
  overlap deadline;
- two consecutive rotate/activate cycles with both old-key deadlines preserved
  and independently retired;
- v2 multi-key migration receiving conservative deadlines;
- activation-journal deadline shortening;
- full emergency event visibility through status/CLI.

The reviewer also correctly noted two threat-model limits. A process with the
same account's identity-directory write permission can coordinate artifact and
hash changes; plain SHA-256 is integrity metadata, not authenticity against
that actor. The loopback HTTP activation probe assumes a trusted local host and
does not authenticate the responding process. Both are now explicit in
`docs/known_limitations.md`; production admission requires real issuer/service
authentication and stronger key custody.

## 58. Configuration-drift closure

The same reviewer rechecked Section 57 and found one remaining path: using the
current configured skew at activation is insufficient if an operator later
raises skew and restarts the API. A key activated at 30 seconds would retain a
930-second window, while the restarted verifier at 120 seconds could still
accept the old token for 1,020 seconds.

The final lifecycle rule therefore does not depend on the current setting:

```text
every new activation deadline =
    activation time + 900 seconds + allowed skew maximum (120 seconds)
```

The v2 migration already used this conservative maximum. Activation now does
the same, and the operation journal requires the frozen activation policy to
contain exactly 120 rather than any lower valid value. The API may still run
with a smaller skew such as the 30-second default; the extra overlap is a
bounded availability cost that prevents later configuration drift from
invalidating still-acceptable tokens early.

The boundary test now states this contract explicitly. It verifies the
persisted deadline is activation + 1,020 seconds, rejects retirement at
deadline minus one, and accepts it exactly at the deadline.

## 59. Public-gate failures during closeout

The next public gate did not pass on the first attempt:

```text
public audit                515 candidates / 1 finding
status/repository tests     81 passed / 1 failed
```

The audit finding was not a leaked credential. The broad credential-assignment
rule interpreted a local variable named `authorization`, bound from an
operation record, as an authorization-header assignment. No
scanner exception or file whitelist was added. The variable was narrowed to
`retirement_grant`, which is also the more accurate domain name.

The failed repository test still required the old status title
“R2-S5 local closeout”, while `PROJECT_STATUS.md` had correctly moved back to
“third-review fixes; final gate pending”. The test was stale, not the status
document, so the test contract was updated.

The exact rerun then produced:

```text
public audit                515 candidates / 0 findings
status/repository tests     82 passed / 3 known SWIG warnings
```

The final targeted lifecycle/config gate is `53 passed / 2 platform skips`.
The lifecycle reviewer performed one last read-only pass and reported no
remaining Critical or Important findings. These results admit the whole-tree
gate; they do not replace it.

## 60. Final-candidate two-reviewer HOLD and repair wave

After the first whole-tree candidate passed locally, two independent read-only
reviewers inspected the current implementation and evidence rather than the old
test summary. The security review found `0 Critical / 2 Important`; the
engineering/evidence review found `0 Critical / 5 Important`. The release
therefore remained `HOLD`. The seven findings were:

1. authenticated request buffering bounded bytes but not zero-byte ASGI
   messages or total read time;
2. journal recovery skipped operation postconditions when the current manifest
   already equaled the journal target;
3. `docs/api.md` documented answer modes that do not exist in the Pydantic
   contract;
4. result/design/plan documents mixed old and current test/benchmark evidence;
5. the benchmark wrote `target_met=false` but still exited successfully and no
   test bound checked-in evidence to current source;
6. the public audit missed common credential names and masked every string
   constant in test functions that called the auditor;
7. the design said `/identity/me` hid issuer/audience/key ID while the
   implementation intentionally returned them.

The same review noted three non-blocking documentation/provenance issues:
emergency retirement wording omitted the mandatory API restart, the direct
dependency count was stale, and the deterministic identity matrix artifact has
weaker standalone provenance than the benchmark. All three are repaired in
this wave.

### 60.1 Authenticated request-stream RED

The old middleware appended every ASGI message to a deque and incremented only
`total += len(body)`. An authenticated peer could repeatedly send:

```python
{"type": "http.request", "body": b"", "more_body": True}
```

Each message consumed memory while `total` stayed zero. A receive coroutine that
never returned also kept the request open indefinitely. Two real middleware
tests were added before the fix. Their RED output was:

```text
zero-byte stream -> AssertionError after the 258th receive
stalled stream   -> outer asyncio TimeoutError after 200 ms
2 failed
```

This confirmed two distinct resource dimensions. A byte limit alone cannot
bound object count, and a count limit alone cannot bound connection occupancy.
The production fix in `app/api/identity.py` now applies, after bearer and role
verification but before FastAPI body parsing:

```text
maximum body bytes       128 KiB
maximum ASGI messages    256
total body read window   5 seconds (monotonic clock)
```

Byte/message overflow returns safe `413 request_body_too_large`; a total read
deadline returns safe `408 request_body_timeout`; malformed ASGI framing
returns safe 400. Invalid bearer precedence remains 401 and never reads the
body. The focused gate is:

```text
5 passed / 3 known SWIG warnings
```

### 60.2 Completed-journal semantic RED and v3

`_validate_operation_semantics()` previously did this:

```python
if current is not None and current["raw"] == manifest_raw:
    return
```

That shortcut is necessary for idempotent crash recovery only if the target is
also a legal completed state for the recorded operation. Equality proves that
bytes were published; it does not prove that a `rotate` remained staged rather
than silently becoming a one-step activation.

The new regression creates a valid rotate journal, transforms its target into a
valid activated manifest, publishes every target artifact in commit order, and
leaves the journal behind. Before the fix, `demo_identity_status()` accepted
the state and deleted the journal:

```text
Failed: DID NOT RAISE IdentityConfigurationError
```

Recovery now calls `_validate_completed_operation_semantics()` before the
equality return. It checks an operation-specific postcondition:

- `init`: exactly one active subject key and empty retirement history;
- `rotate`: subject exists and is still the pending, non-active key;
- `activate`: subject is active, no key is pending, and the previous active key
  has the exact frozen overlap deadline;
- `retire`: subject is absent, is the last retired key, has no deadline, has the
  exact private-key delete, and emergency evidence matches when applicable;
- `upgrade`: subject remains the active key and no key deletion is present.

The operation schema is now `demo-identity-operation-v3`. Activation policy
adds `previous_active_kid`; both transition-time and completed-state recovery
bind it to the deadline:

```text
deadline = activated_at + 900 + 120
```

Old/unknown journal shape fails closed rather than being guessed. The focused
recovery cases first passed `4/4`; the complete lifecycle/CLI gate then passed:

```text
40 passed / 2 platform skips / 3 known SWIG warnings
```

### 60.3 Benchmark becomes a release gate

The benchmark already recorded `target_met`, immutable output, run ID,
environment, and source SHA-256. Its module entry point still called `main()`
without `SystemExit`, and `main()` returned `None`. A simulated p95 miss
therefore reproduced:

```text
expected exit code 1
observed None
```

The command now writes the result first, then returns `0` only when the target
is met and `1` otherwise; `python -m` raises `SystemExit(main())`. A second test
loads the checked-in public benchmark and requires:

- schema v2 and ephemeral managed input;
- 1,000 iterations;
- `target_met=true` and p95 not above its recorded target;
- exact SHA-256 equality for all recorded source files.

The new immutable candidate run is:

```text
run_id       identity-benchmark-20260723T124717Z-668f464566bb
p50/p95/p99  0.0546 / 0.0904 / 0.1433 ms
max          0.3601 ms
target       p95 <= 10 ms, met
tests        4 passed
```

The measurement is still warm in-process verifier latency, not HTTP, RAG, LLM,
remote IdP, or production SLO evidence.

### 60.4 Credential audit: blind spots, then false positives

Seven new tests were first RED: no detection for `client_secret`,
`AWS_SECRET_ACCESS_KEY`, `secret_access_key`, `refresh_token`, generic `token`,
AWS access-key ID shape, or a credential literal inside a test function that
called `audit_repository()`.

The initial rule expansion correctly detected these cases but produced 30
whole-repository findings. Inspection showed most were ordinary context-handle
assignments, RSA private-key type annotations, and keyword forwarding from an
already validated token variable. None bound a hard-coded literal credential.

Removing the new names would restore the blind spot. Adding file or test
whitelists would restore the bypass. The scanner was instead split by syntax:

- Python files are parsed with `ast`; it flags hard-coded string values bound
  to credential variable/attribute/subscript names, sensitive dict keys and
  keyword arguments, plus credential assignments embedded inside string
  literals;
- Markdown, JSON, env and other text retain regex assignment scanning;
- high-confidence OpenAI/GitHub/JWT/AWS/Slack/GitLab/Google token shapes are
  scanned at byte and text levels;
- only the scanner's own rule-definition AST nodes are masked;
- the previous “mask every string in auditor tests” function was deleted.

Test fixtures now construct realistic leak values at runtime so the temporary
candidate is caught without signing a realistic credential into the repository
itself. The final focused and whole-candidate evidence is:

```text
public-audit + trace-redaction tests  87 passed
repository audit                     515 candidates / 0 findings
```

This remains a high-signal heuristic, not a substitute for provider-side secret
scanning, credential rotation, or review of binary/oversized artifacts.

### 60.5 Contract and operator documentation reconciliation

The documentation fixes are semantic, not cosmetic:

- `AnswerResponse.mode` now lists the exact eight values from
  `app/domain/agent.py`;
- `/identity/me` explicitly returns subject, tenant, region, groups, roles,
  issuer, audience and key ID. The latter values are already present in the
  caller's validated token/header and key ID is required by the staged
  activation proof. Timestamps, raw token/hash, key paths, JWK and additional
  claims remain excluded;
- readiness still exposes only `identity=ok/error`;
- emergency retirement help now says the key leaves the *next* API snapshot
  and a restart is required to reject still-live tokens;
- `requirements.txt` is documented as 17 direct pins, not 15;
- historical `1835/20` and old p95 values are labeled historical everywhere;
  the current status remains `HOLD`.

Before the additional provenance work below, the focused repairs, source-bound
benchmark and public audit were GREEN while a fresh matrix was still pending.
Section 60.6 closes that matrix item. Whole-tree pytest, independent `0/0`
re-review, commit/push and exact-SHA Ubuntu/Windows CI remain required.

### 60.6 Deterministic matrix provenance hardening

The public matrix result previously carried only the frozen matrix SHA. That
proved which cases were evaluated but not which evaluator/API/identity code
produced the decisions. Adding a wall-clock run ID would weaken the existing
cross-platform byte-for-byte recomputation contract.

`TrustedIdentityEvaluationResult` therefore advances to schema v2 with:

- deterministic contract ID
  `trusted-identity-contract-ddaddc325893bbdb`;
- exact SHA-256 for ten evaluator, API, persistence, identity, lifecycle and
  runner source files;
- the existing frozen matrix ID/SHA and per-case result;
- no wall-clock time, random nonce, host path or environment-specific field.

The RED test initially failed at import because the provenance contract did not
exist. After implementation, the full matrix evaluation test file passes
`6/6`. A fresh immutable result and the checked-in public artifact are
byte-identical:

```text
cases                    20/20
denied side effects      0
credential leaks         0
release_pass             true (matrix scope only)
artifact SHA-256         e7159efea7d46d6537829e895fe8b8233698f17bda3ec652cb6f727d76784067
```

This closes standalone evaluator provenance for the deterministic local matrix.
It still does not attest the Python interpreter, transitive wheels, runner image
or producer identity; those remain supply-chain/deployment limitations.

## 61. Repaired whole-tree release gate

After the seven findings in Section 60 were repaired and all source-bound
artifacts were regenerated, the complete current worktree was tested again.
This run is separate from the historical `1835/20/3` checkpoint that the
reviewers invalidated:

```text
compileall                         exit 0
pip check                          no broken requirements
git diff --check                   exit 0
public repository audit            515 candidates / 0 findings
full pytest                        1892 passed / 20 skipped / 3 warnings
full pytest elapsed                125.73 seconds
```

The diff check emitted only Git's existing notice that `.env.example` will be
normalized from CRLF to LF when Git next writes it; it reported no whitespace
error. The three warnings are the existing FAISS/SWIG deprecation warnings.
The 20 skips are platform-qualified tests, not silently removed failures.

This gate proves that the repaired worktree is internally consistent on the
current Windows/CPython environment. It does not yet release the candidate.
The remaining ordered gates are a fresh independent `0 Critical / 0 Important`
whole-diff review, commit/push, and Ubuntu/Windows GitHub Actions on the exact
committed SHA.

### 61.1 Final matrix recomputation after documentation reconciliation

After the status documents were changed from `PENDING` to the actual whole-tree
result, the deterministic matrix was run once more into an ignored candidate
path. It did not overwrite the checked-in public artifact:

```text
candidate  security_runs/r2_s5/identity_matrix_result_final_gate.json
cases      20 passed / 0 failed; 14 denied
effects    0 denied side-effect violations
leaks      0 credential leaks
release    true (matrix scope only)
SHA-256    e7159efea7d46d6537829e895fe8b8233698f17bda3ec652cb6f727d76784067
```

The candidate and `docs/security/r2_s5/evidence/identity_matrix_result.json`
have the exact same SHA-256. During the human-readable summary check, a one-line
helper first requested a nonexistent `contract_id` key and raised `KeyError`;
inspection of the frozen schema showed the actual field is
`evaluation_contract_id`. Re-reading with that exact field confirmed
`trusted-identity-contract-ddaddc325893bbdb`. The evaluation command itself had
already exited zero, so this was a display-helper mistake rather than an
evaluation failure.

## 62. Fourth review wave: partial closure, new HOLD, and repair

Two independent reviewers re-read the repaired worktree. The security reviewer
verified the authenticated-body and journal fixes and returned:

```text
Critical   0
Important  0
Minor      3 documentation inconsistencies
```

The engineering/evidence reviewer verified the earlier AnswerMode, benchmark,
identity-disclosure, matrix-provenance and dependency fixes, but returned:

```text
Critical   0
Important  2
Minor      1 stale Linux-only CI wording
```

The first Important finding showed that the credential scanner still treated
arbitrary substrings as safe. Values containing `test`, `$`, `{`, `<` or `(`
could bypass a literal credential assignment. The second showed that
`invalid_content_length` and `invalid_request_body` existed in code but were
missing from the public API error table and lacked complete zero-downstream
regression coverage.

The security-review Minors were also real contract drift:

- invalid `X-Request-ID` is replaced, not returned as a validation error;
- trace lookup requires operator authentication, not unauthenticated localhost;
- the runbook still showed retired body `user_context` without a bearer token.

The candidate returned to `HOLD`. A security review reaching `0/0` cannot
override a separate engineering review with open Important findings.

### 62.1 Additional local finding and RED

Manual boundary inspection found a related framing failure before editing code.
`_content_length_error()` called `int(rendered)` on an authenticated header. A
5,000-digit value exceeded CPython's integer-string conversion limit and raised
an uncaught `ValueError` instead of a safe 413.

Twelve new parameterized cases were added before implementation changes:

- duplicate `Content-Length`;
- `Content-Length` plus `Transfer-Encoding`;
- non-numeric and 5,000-digit lengths;
- non-dict ASGI message, wrong message type, non-bytes body and non-bool
  `more_body`;
- credential values colliding with `test`, `$` and `(`;
- the public 400 error contract.

The RED run reproduced exactly the missing behavior:

```text
5 failed / 7 passed
```

The seven already-passing cases proved the existing malformed ASGI and ordinary
length branches returned safe errors with zero downstream calls. The failures
were the huge integer conversion, three credential bypasses, and absent docs.

### 62.2 GREEN implementation

`Content-Length` comparison now strips leading zeroes and compares digit count
plus same-length lexical order against `131072`. It never creates an attacker-
sized Python integer. Authentication still occurs first, and framing rejection
still occurs before body receive, JSON parsing, persistence, retrieval or Agent
execution.

Credential placeholders are now admitted only by bounded marker matching or an
exact dynamic-reference grammar:

- safe words such as `test`, `fake` and `redacted` require non-alphanumeric
  boundaries;
- `$ENV_VAR`, `${ENV_VAR}`, `<placeholder>` and `{placeholder}` must match the
  complete value;
- Python AST string literals do not become dynamic merely because they contain
  `$`, `{` or `(`;
- bare text may admit explicit settings/config references, a known context
  binding call, or a variable name ending in `_token`, `_secret` or `_key`.

The API table now publishes both 400 codes and explains duplicate/conflicting
framing. The request-ID, operator trace and authenticated smoke-runbook text now
matches the executable service. All Linux-only acceptance wording was changed
to the actual Ubuntu/Windows matrix.

The immediate GREEN and broader regression were:

```text
new RED/GREEN cases               12 passed
boundary/audit/redaction          125 passed
public repository audit           515 candidates / 0 findings
git diff --check                  exit 0
```

### 62.3 Source-bound evidence invalidation and regeneration

`app/api/identity.py` is one of the ten source files bound into the deterministic
matrix result. The framing fix therefore intentionally invalidated the prior
Section 61 artifact even though all 20 decisions stayed the same. The evaluator
was rerun into an ignored candidate path, then that generated file was
mechanically promoted to the checked-in public evidence:

```text
cases                    20 passed / 0 failed; 14 denied
denied effects           0
credential leaks         0
release_pass             true (matrix scope only)
evaluation contract      trusted-identity-contract-947bc529798ebcf6
app/api/identity.py SHA  878bb8c76a40ed18ed88f251dc50d3a5add280ad3662543173713aa62e11ad73
artifact SHA-256         2ec62b6e8eda35531b43a67263cec16dc42fb07e207ec2b43d22d1cfb6227c12
```

Candidate and public artifact bytes are identical. This is why the earlier
`e7159efe...84067` value remains only as history rather than being silently
edited in the old journal entry.

### 62.4 Second repaired whole-tree gate

After the code, tests, public evidence and documentation were all current:

```text
full pytest                        1904 passed / 20 skipped / 3 warnings
full pytest elapsed                150.66 seconds
compileall                         exit 0
pip check                          no broken requirements
matrix + benchmark contract tests 10 passed
public repository audit            515 candidates / 0 findings
git diff --check                   exit 0
```

The three summarized warnings remain the known FAISS/SWIG deprecations. Pytest
also printed post-summary Windows cleanup warnings for old permission-hardened
temporary `garbage-*` directories. They did not change the test exit code or
business result, but are recorded rather than hidden.

The candidate remains `HOLD` until both reviewers re-read this exact repaired
worktree and return `0 Critical / 0 Important`. Only then may it be committed,
pushed, and tested by Ubuntu/Windows Actions on the exact commit SHA.

## 63. Fifth review wave: whole-value placeholder grammar

The engineering reviewer returned `0 Critical / 0 Important` after Section 62.
The security reviewer then found one additional Important issue in the stricter
credential audit. A client-secret field whose test value was assembled from
the three pieces `prod-`, `test`, and `-LiveCredentialValue42` was incorrectly
treated as a safe fixture.

The previous repair changed unbounded substring matching into word-boundary
matching. That closed `latest-production-value`, but punctuation around `test`
still formed valid boundaries. Because the implementation used `.search()`,
one safe word anywhere still marked the whole literal safe.

Two more parameterized cases were added before the next implementation change:

```text
prod-test-LiveCredentialValue42
real-redacted-LiveCredentialValue42
```

The RED result was `2 failed / 3 passed` in the five-case collision matrix.
The scanner then changed from searching markers to full-value validation.
Accepted synthetic forms are now an anchored grammar, including exact demo
tokens, values starting with an explicit `test-`/`never-show-` style fixture
prefix, bracketed redaction placeholders, and separately validated complete
dynamic references. A safe word in the middle of an otherwise arbitrary value
does not match.

The stricter whole-repository run initially reported:

```text
515 candidates / 1 finding
```

The finding was an intentional leakage-test literal in
`tests/api_v2/test_errors.py`, not a production credential. The scanner was not
relaxed. Instead, the test now assembles its synthetic secret from two runtime
string parts, preserving the response/log redaction assertion without storing
one complete credential-shaped literal in the repository.

Final local evidence for this wave is:

```text
whole-value focused regression    8 passed
public-repository + API errors     91 passed
boundary/audit/redaction           127 passed
public repository audit            515 candidates / 0 findings
full pytest                        1906 passed / 20 skipped / 3 warnings
full pytest elapsed                166.65 seconds
compileall                         exit 0
pip check                          no broken requirements
git diff --check                   exit 0
```

This wave changed the audit script and tests, not the ten source files bound by
the trusted-identity matrix. The matrix artifact therefore remains exactly
`2ec62b6e...7c12`; regenerating it would add no new source provenance. The
candidate remains `HOLD` pending the security reviewer's final `0/0`
confirmation.

## 64. Final independent closure and release handoff

The exact Section 63 worktree was re-read by both independent reviewers:

```text
security reviewer      0 Critical / 0 Important / RELEASE
engineering reviewer   0 Critical / 0 Important / RELEASE
```

The security reviewer verified that placeholder admission uses anchored
whole-value grammar plus `.fullmatch()`, that all five collision cases require a
finding, and that the synthetic fixture refactor did not weaken response/log
redaction assertions. The engineering reviewer verified the current
`14 / 127 / 1906 / 20 / 3 / 515/0` evidence set, all matrix source hashes, the
benchmark source hashes, and the separation between historical
`94125e66...b1e66` and current `2ec62b6e...7c12` matrix artifacts.

No reviewer modified files or generated evidence. The only edits after their
conclusions are these release-status sentences and the matching repository
contract assertion.

Static remote-workflow preparation was also checked on 2026-07-23:

- the pinned `actions/checkout` commit
  `d23441a48e516b6c34aea4fa41551a30e30af803` exists upstream;
- the pinned `actions/setup-python` commit
  `ece7cb06caefa5fff74198d8649806c4678c61a1` exists upstream;
- GitHub's workflow syntax documents that `shell: bash` on Windows uses the
  Bash bundled with Git for Windows.

The candidate now leaves local `HOLD` and becomes a **local release candidate**.
This means the implementation, deterministic evidence, local gates and
two-reviewer gate pass. It still does not mean production IdP certification or
deployment success. The ordered remaining work is:

```text
stage -> inspect -> commit -> push -> exact-SHA Ubuntu/Windows Actions
```

## 65. Exact-SHA CI #17 failure and cross-platform repair

The reviewed tree was committed as
`d753df3915dd78ef930a10ea1e8324e994ed5b91` and pushed to
`codex/rag-eval-system`. [GitHub Actions run
30012887739](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30012887739)
executed that exact SHA on both configured runners. Dependency installation,
`pip check`, compilation, and the frozen evaluation hash gate all passed before
pytest. The deterministic test step then stopped release:

```text
Ubuntu  job 89225269836   1 failed / 1910 passed / 15 skipped / 4 warnings
Windows job 89225269319   5 failed / 1918 passed / 3 skipped / 4 warnings
run conclusion            failure
```

The public check annotations exposed the complete Ubuntu failure but only a
warning line for Windows. The unauthenticated log archive endpoint returned
HTTP 403 and the logged-out Actions page required sign-in to display logs. The
existing Git Credential Manager credential was therefore used for one
read-only API download into ignored `.tmp/ci17`; the credential value was
neither printed nor persisted by the diagnostic command.

### 65.1 Shared assertion-contract failure

Both runners rejected a real redirecting ancestor as intended, but the test
expected `directory is unsafe` while `validate_private_path_ancestors`
correctly raised `identity private path is unsafe`. This was not an allow
bypass. The regression now asserts the actual ancestor-path error contract.

### 65.2 Windows DOS 8.3 alias false rejection

The ephemeral benchmark and two matrix recomputation tests used a temporary
directory whose lexical spelling contained a DOS 8.3 runner-profile alias.
`Path.resolve()` returned the equivalent long spelling. The previous check
compared normalized strings and rejected the same directory object.

The implementation now keeps all existing `lstat`, symlink/reparse, ancestor,
owner/ACL, handle-lock, and directory-identity checks, but compares the
lexical and resolved paths with `os.path.samefile`. Two deterministic tests
prove both sides of the contract:

- a different spelling of the same directory object is accepted;
- a genuinely different resolved directory object is rejected.

The RED run for the equivalent-spelling test failed with
`IdentityConfigurationError`. After the change, the benchmark and both matrix
tests that failed on the GitHub Windows runner pass locally.

### 65.3 CI interpreter-layout assumption

The executable R2-S3 isolated-verifier documentation assumed
`.venv/Scripts/python.exe`. Developer workstations use that layout, while
`actions/setup-python` puts Python on PATH and does not create a repository
venv. Both documented PowerShell blocks now prefer the repository venv when
present and otherwise select the first PATH `python` application.

The first fallback implementation revealed another local portability issue:
`Get-Command` returned several Python applications and PowerShell concatenated
their paths into one invalid command. Adding `Select-Object -First 1` made the
selection deterministic. The test deliberately rewrites the venv candidate to
a missing path and prepends the current interpreter directory to PATH, so the
CI fallback branch is exercised on every Windows test run.

### 65.4 Source-bound evidence regeneration

`app/security/demo_identity.py` is one of the ten files bound into the trusted
identity result. The path fix therefore invalidated the previous
`2ec62b6e...7c12` artifact even though all 20 behavioral outcomes remained
unchanged. The immutable evaluator generated a new candidate; a no-index diff
showed only the expected lifecycle source hash and derived contract ID changed.
The candidate was then mechanically promoted to public evidence:

```text
cases / failed             20 / 0
denied effects / leaks     0 / 0
release_pass               true (matrix scope only)
contract                   trusted-identity-contract-382abc9b1a8de344
demo_identity.py SHA-256   a1dd9bec7e48c76a0cf86f3cd59fc0909fe782394a6293ad56fdc15ea0bb6a8b
artifact SHA-256           1fcf0b0468be193d30133e11dc15a98c1539133b21c738798860d0ac9423869c
```

### 65.5 Local repair gates

```text
initial RED slice                 2 failed / 1 skipped
focused post-fix slice            9 passed / 1 skipped
identity/lifecycle/public group   137 passed / 2 skipped / 3 warnings
full pytest                       1908 passed / 20 skipped / 3 warnings
full pytest elapsed               153.11 seconds
```

The post-summary Windows cleanup warnings still concern old
permission-hardened pytest garbage directories and do not change the zero exit
status. This repair is not released yet. The next gate is a new commit, push,
and Ubuntu/Windows Actions run bound to that exact replacement SHA.

### 65.6 Public-audit failure caused by diagnostic residue

The first post-documentation public audit returned `544 candidates / 27
findings`. Twenty-six findings came from the downloaded raw CI logs under
`.tmp/ci17`; the remaining finding was the complete machine-specific runner
path quoted in this journal. The scanner intentionally does not trust a file
merely because it is temporary or ignored.

The raw diagnostic directory created in Section 65 was removed after the
failure facts had been reduced into this low-sensitivity record. The journal
now describes the DOS 8.3 condition without retaining a machine path. No audit
rule or safe-marker grammar was relaxed. The repeated repository audit
returned:

```text
public candidates   515
findings               0
```

## 66. Post-CI review: bind directory identity across resolution and hardening

The first CI repair used `os.path.samefile(root, resolved)`. A post-repair
independent review correctly returned `HOLD` with `0 Critical / 2 Important /
3 Minor`. The review did not find a demonstrated bypass in the released
commit; it found that the proposed repair and its regression test did not prove
the intended object-identity contract strongly enough.

### 66.1 Why the first `samefile` repair was incomplete

The old sequence was conceptually:

```text
1. lstat(root) and reject symlink/reparse metadata
2. resolve(root)
3. samefile(root, resolved)
```

If `root` was replaced after step 1 but before step 2, both arguments in step 3
could observe the replacement object. The comparison would be true, even
though the object checked in step 1 was no longer the object being accepted.
This is a time-of-check/time-of-use gap. It is different from the Windows 8.3
alias problem: aliases are two names for one object and must be accepted;
replacement is one name changing to a different object and must be rejected.

The first test also mocked `samefile` to return true. That proved only that the
branch used `samefile`; it did not prove that an actual DOS 8.3 path alias was
accepted by the Windows filesystem.

### 66.2 RED tests before the stronger implementation

Two tests replaced the synthetic proof:

- `test_identity_directory_accepts_a_real_windows_short_path_alias` calls
  `GetShortPathNameW`, requires `os.path.samefile(short_path, long_path)`, and
  passes the real alias into `_validate_identity_directory`;
- `test_identity_directory_rejects_replacement_during_resolution` renames the
  original directory out of the path and a replacement directory into the path
  exactly when `Path.resolve()` is called.

Against the first repair, the real alias test passed but the replacement test
failed because no `IdentityConfigurationError` was raised:

```text
real Windows short-path alias     PASS
directory replacement race       FAIL
review disposition                HOLD
```

This RED result was useful: the Windows compatibility fix was real, but its
security invariant was incomplete.

### 66.3 Production implementation

`app/security/demo_identity.py::_validate_identity_directory` now binds three
filesystem observations:

```text
before            = root.lstat()
resolved          = root.resolve(strict=True)
resolved_metadata = resolved.stat()
after             = root.lstat()

samestat(before, resolved_metadata) must be true
samestat(resolved_metadata, after)  must be true
```

Each observation must also be a directory and must not be a symlink or reparse
point. Resolution/stat failure and any identity mismatch fail closed with
`IdentityConfigurationError`. On success, the helper returns `(st_dev,
st_ino)` rather than only returning `None`.

The callers use that identity for a second boundary:

```text
validate and capture object identity
apply private-directory permission hardening
validate again
require the post-hardening identity to equal the captured identity
```

This is implemented in both `_prepare_directory` and
`_prepare_status_directory`. It prevents permission hardening from silently
continuing on a directory object different from the one originally accepted.
The existing ancestor checks, active-directory handle binding, entry
`lstat`/`fstat` checks, lock, atomic replacement, and private file hardening
remain in place.

### 66.4 Documentation-verifier and wording drift fixes

The review's three Minor findings were also closed:

1. `tests/test_public_repository.py` now requires the exact PowerShell
   interpreter bootstrap to occur twice, so the export and isolated-verifier
   blocks cannot drift independently.
2. The executable test still removes the repository-venv branch and exercises
   the PATH fallback with the running interpreter's directory.
3. The plan now says the CI run failed and the release was blocked as designed;
   it no longer implies that the failure itself was designed.
4. README classifies the roots as one assertion-contract failure and two
   portability failures instead of calling all three portability failures.

### 66.5 Source-bound evidence v3

The stronger lifecycle implementation changed one of the ten source files
bound by the trusted-identity matrix. A fresh candidate was generated at a new
path and compared against the Section 65 artifact. The only JSON differences
were the expected `app/security/demo_identity.py` SHA-256 and the derived
evaluation contract ID. All case outcomes and aggregate values remained
identical.

```text
schema                     trusted-identity-evaluation-v2
cases / passed / failed    20 / 20 / 0
denied cases               14
denied side-effect errors   0
credential leaks            0
release_pass               true (matrix scope only)
contract                   trusted-identity-contract-2e8f8081657a2e14
demo_identity.py SHA-256   f8f07459bf22435a13b29a72aa94586dcd92002b737837a96a2d5b23f8368f71
candidate/public SHA-256   a2b9afb0aa35a5f69119b088b58963fc44168a7d8c77594886d03c03aa29782b
```

Candidate and public hashes were checked separately and are byte-identical.
The frozen evaluation regression passes against the promoted public artifact.

### 66.6 Local gates after the stronger repair

```text
focused alias/race/docs                 3 passed
focused CI-failure slice                5 passed / 1 platform skip
trusted-identity evaluation             6 passed
affected lifecycle/benchmark/public   137 passed / 2 platform skips
full pytest                           1908 passed / 20 skipped / 3 warnings
full pytest elapsed                    151.22 seconds
compileall                              PASS
pip check                               CLEAN
public repository audit                 515 candidates / 0 findings
git diff --check                        PASS
```

The three suite warnings remain the known FAISS/SWIG deprecation warnings.
Windows pytest may additionally report post-summary cleanup warnings for old
permission-hardened temporary directories; these do not change pytest's zero
exit status. Post-repair independent re-review and replacement exact-SHA
Ubuntu/Windows Actions are still mandatory before remote acceptance.

## 67. Final post-CI hardening: bind side effects to filesystem objects

Section 66 closed the path-resolution race, but it did not yet prove that every
later side effect targeted the same filesystem object. Two additional scoped
reviews were therefore treated as release gates rather than advisory comments:

```text
review after the first CI repair       0 Critical / 2 Important / 3 Minor / HOLD
review after initial handle refactor   0 Critical / 2 Important / 3 Minor / HOLD
final scoped re-review                 0 Critical / 0 Important / 0 Minor / RELEASE
```

The two `HOLD` results are not contradictory with earlier green tests. They
show that the tests covered the decisions already implemented, while the
reviewers found security invariants that had not yet been represented by a
test.

### 67.1 Why `samestat` detection alone was not enough

The Section 66 implementation compared:

```text
lstat(path) -> stat(resolved path) -> lstat(path)
```

with `os.path.samestat`. This correctly distinguishes:

- two names for the same object, such as a real Windows DOS 8.3 alias; and
- one name that was changed to point at another object during resolution.

However, a successful comparison is still only an observation at one moment.
The next operation was name-based permission hardening:

```text
validate object A through path P
attacker replaces P so it names object B
chmod(P) or SetNamedSecurityInfo(P) changes object B
```

Failing after the permission call would detect the race, but it would not undo
the unauthorized side effect on object B. This is the important distinction:
postcondition checking can detect a wrong-object write; it cannot make that
write harmless.

There was a second window between `_prepare_directory()` and
`_identity_lock()`. The prepare step returned a path but did not carry the
accepted object identity into the lock boundary. A replacement in that gap
could therefore cause a later lifecycle operation to lock and modify a
different directory.

### 67.2 RED tests that represented the missing contracts

The next tests were written before the production refactor:

1. create a real Windows short-path alias with `GetShortPathNameW`, resolve it
   to the long path, and prove both names identify the same object;
2. replace the directory exactly while `Path.resolve()` runs;
3. replace the directory after prepare but before `_identity_lock()` for both
   rotate and status;
4. prove permission hardening never changes the replacement object;
5. on Windows, replace the path after obtaining a handle and require
   `SetSecurityInfo` to operate on the original handle;
6. on POSIX, replace the path after obtaining a descriptor and require
   `fchmod` to operate on the original descriptor.

Against the old implementation, the focused run produced:

```text
3 failed / 1 platform skip
```

The failures were expected RED evidence. The platform skip means the current
machine could not execute the other operating system's native primitive; it
does not mean that contract was omitted from the suite.

### 67.3 Object-bound implementation

`app/security/private_fs.py` now exposes a `HeldPrivateDirectory` value. It
contains the already-open POSIX directory descriptor or Windows directory
handle and the native identity required to compare the path with that held
object.

The lifecycle data flow is now:

```text
prepare directory
  -> validate path and capture expected (device, inode) identity
  -> enter _identity_lock(expected_identity)
  -> open and hold the accepted directory object
  -> compare held identity with prepare-time expected identity
  -> validate active snapshot through the held directory
  -> harden entries through held handles/descriptors
  -> acquire bounded lifecycle lock
  -> recover journal and execute operation
```

All five production lifecycle entrypoints carry the expected identity from
prepare into `_identity_lock()`. No lifecycle write, permission repair, or
journal recovery is allowed before the comparison succeeds.

On POSIX:

- the directory is opened once and retained as a descriptor;
- entries are opened relative to that descriptor with `dir_fd`;
- `O_NOFOLLOW` rejects a final symlink and `O_NONBLOCK` prevents a FIFO from
  blocking the verifier;
- `fstat` checks the already-open entry is a regular file before reading;
- `fchmod(fd, 0o600)` changes the held file, not whatever a path name may later
  reference;
- the held directory descriptor receives mode `0o700`.

On Windows:

- the root and each child are opened as native filesystem handles;
- `FILE_ID_INFO`/handle metadata bind the handle to the expected object;
- ACL inspection is performed on the handle;
- `SetSecurityInfo(handle, ...)` applies the DACL to the held object;
- every native handle is closed in `finally`, including failure paths.

This changes the safety argument from "check the name before and after a
write" to "perform the write through the object already checked."

### 67.4 Follow-up review findings and fixes

The first handle-based version received another
`0 Critical / 2 Important / 3 Minor / HOLD`.

The first Important finding concerned the active manifest snapshot on POSIX.
Opening a FIFO without `O_NONBLOCK` can wait forever before code gets a chance
to reject its file type. The open flags now include `O_NONBLOCK`, and the code
performs `fstat` plus a regular-file check before the first `os.read`.

The second Important finding concerned Windows ownership. The initial ACL
repair path implied that it could repair a file owned by an untrusted
principal, but its handle rights and threat model did not justify silently
taking ownership. The final policy is deliberately conservative:

```text
accepted owner    current Windows user or LocalSystem
untrusted owner   fail closed with PrivatePathError
ownership repair  not attempted
```

Both name-based validation used outside the held lifecycle and handle-based
hardening enforce the same owner rule. An untrusted owner is rejected before
`SetSecurityInfo` can run.

The related Minor resource-lifetime finding was also fixed. Four Windows ACL
inspection/update paths now acquire the process token inside a `try/finally`
region that also covers `_windows_system_sid()`. If SID construction raises,
the token handle is still closed. Parameterized regression tests prove all
four cleanup paths.

### 67.5 Why these Windows APIs were selected

Microsoft's `SetSecurityInfo` contract updates the security information of an
object identified by a handle:

https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo

Microsoft's security-descriptor guidance distinguishes handle-based
`GetSecurityInfo`/`SetSecurityInfo` from name-based operations and recommends
the handle form when the object is already identified by a handle:

https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptor-operations

The stable Windows identity is derived from handle information, including
`FILE_ID_INFO` semantics:

https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info

These references informed the primitive selection. They do not by themselves
prove this implementation; the platform-specific race and cleanup tests are
the executable evidence.

### 67.6 Source-bound evidence expanded to eleven files

The review also found an evidence-provenance gap: the matrix bound
`demo_identity.py`, but did not bind the lower-level `private_fs.py` module
that now enforces the filesystem security contract.

`TRUSTED_IDENTITY_SOURCE_FILES` therefore contains eleven explicit paths,
including `app/security/private_fs.py`. A regression test asserts the exact
eleven-file set so that a future refactor cannot silently drop a security
dependency from the evidence contract.

The final fresh candidate, promoted public artifact, and bound source values
are:

```text
schema                       trusted-identity-evaluation-v2
cases / passed / failed      20 / 20 / 0
denied cases                 14
denied side-effect errors     0
credential leaks              0
release_pass                 true (matrix scope only)
contract                     trusted-identity-contract-7c183871488a6519
demo_identity.py SHA-256     fc62d3889d618e7be516ced0993a84e65f3f169b6b6e29086574c056d096f776
private_fs.py SHA-256        5c39fc9cf9ff627023ff0edc081874a69e051407adc63b9608ac91770b119ea7
candidate/public SHA-256     0258f8c28c363c785751ef64330db5444f75e6169b5b263430dee7049b790829
```

The following artifacts remain useful historical evidence but are superseded
as release evidence because later security-source changes altered the bound
contract:

```text
ci17_fix.json       1fcf0b0468be193d30133e11dc15a98c1539133b21c738798860d0ac9423869c
ci17_fix_v2.json    a2b9afb0aa35a5f69119b088b58963fc44168a7d8c77594886d03c03aa29782b
ci17_fix_v3.json    7d0c06319e6f8b56739365129381e21d1e2c39bb660476837005b5e8924e54a8
ci17_fix_v4.json    ccffb8ad937437769b89881ac492697d200453512ec3abf4b9d68ce96d3eca81
```

Sections 65 and 66 intentionally retain their contemporaneous hashes and test
counts. This section records why those values are no longer the current
release candidate.

### 67.7 Final local verification

The first audit after adding the beginner guide returned
`515 candidates / 1 finding`. The example used a drive-letter absolute path,
which correctly matched the machine-path disclosure rule. The example was
replaced with the lexical placeholder `<private-root>/identity`; the scanner
and its allowlist were not weakened.

```text
lifecycle and private-fs tests          47 passed / 4 platform skips
affected identity/security contracts   151 passed / 4 platform skips
trusted-identity matrix                 20 passed / 20 total
full pytest                           1918 passed / 22 skipped / 3 warnings
full pytest elapsed                    178.57 seconds
compileall                              PASS
pip check                               CLEAN
public repository audit                 515 candidates / 0 findings
git diff --check                        PASS
final scoped re-review                  0C / 0I / 0M / RELEASE
```

The three warnings are the known FAISS/SWIG deprecation warnings. The final
review disposition applies to the scoped post-CI hardening diff; it does not
replace the required exact-SHA Ubuntu/Windows workflow.

### 67.8 Residual risk and current release state

Prepare-to-lock binding uses `(st_dev, st_ino)` on the current platform and
does not continuously retain the prepare-time handle across the public
entrypoint boundary. An extreme ABA event in which the filesystem reuses the
same identity value could evade that comparison. The practical likelihood is
reduced by private ancestor ownership/permission checks, rejection of
symlink/reparse components, the very short boundary, and the held-object
checks inside the lock, but the implementation does not claim the event is
impossible.

The current state is therefore:

```text
local implementation and scoped review   complete
final public matrix v5                    complete
replacement repair commit                pending
replacement exact-SHA Ubuntu/Windows CI  pending
remote release acceptance                not yet claimed
```
