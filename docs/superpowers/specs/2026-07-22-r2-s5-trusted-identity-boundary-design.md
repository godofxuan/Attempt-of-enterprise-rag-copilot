# R2-S5 Trusted Identity Boundary Design

Status: approved; implementation and local release gates complete on
2026-07-23; exact-SHA CI #17 failed, repair is locally green, and replacement
Ubuntu/Windows CI acceptance is pending

Selected option: self-contained local RSA JWT/JWKS identity source

Delivery boundary: local reproducible security contract, not a real IdP claim

Implementation status vocabulary used in this document:

- `implemented`: code exists and the named focused test evidence has passed;
- `partial`: part of the contract exists, but one or more listed gates remain;
- `planned`: design is frozen, but implementation evidence does not yet exist;
- `pending verification`: implementation may exist, but the required gate has
  not yet been recorded.

## 1. Problem

Before R2-S5, `/agent/v2/chat` accepted a caller-provided `user_context`.
`UserContext` and `AccessPolicy` validate shape and enforce tenant, region, and
group matching, but they cannot prove who supplied those values. A caller can
therefore self-assert another tenant or group before the otherwise-correct ACL
logic runs. `/feedback`, `/observability/metrics`, and trace lookup are also
unauthenticated.

R2-S5 moves identity authority to the server boundary:

```text
Authorization: Bearer JWT
    -> pinned local JWKS verifier
    -> server-owned Principal
    -> deterministic UserContext
    -> existing AccessPolicy
```

No LLM participates in authentication or authorization.

## 2. Goals

1. Remove and reject body-supplied identity on the secure V2 route.
2. Verify a signed access token with a fixed issuer, audience, algorithm,
   explicit token type, bounded lifetime, and key ID.
3. Derive `Principal` and then `UserContext` only from verified claims.
4. Reject invalid identity before query analysis, retrieval, model calls,
   feedback persistence, metric disclosure, or trace lookup.
5. Require `rag.operator` for metrics and trace access.
6. Keep liveness public and readiness public but low sensitivity.
7. Provide a usable local bootstrap and token-issue workflow without checking
   a private key or bearer token into Git.
8. Bind feedback to a one-way actor identifier without storing raw subject,
   tenant, groups, roles, token, question, or answer.
9. Add deterministic security, privacy, rotation, and warm-latency gates.
10. Keep the existing ACL engine and Agent workflow unchanged after the new
    identity adapter.

## 3. Non-goals

- Real SSO, browser login, authorization-code flow, refresh tokens, logout,
  token revocation, SCIM, policy administration, or an identity database.
- Remote OIDC discovery or runtime JWKS HTTP fetching in this stage.
- Trusting reverse-proxy identity headers.
- Encrypting JWT claims. JWTs are signed credentials and must not contain
  secrets.
- Replacing document ACLs with role shortcuts. `roles` do not bypass groups.
- Adding LangGraph, Kubernetes, Redis, Kafka, a vector service, multi-Agent
  delegation, or long-term memory.

## 4. Standards and dependency decision

The design was checked against primary standards and current agent-security
guidance. The mapping is explicit so these references remain engineering input,
not decorative citations:

| Source | Guidance used | Concrete project decision |
|---|---|---|
| [IETF RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html) | Verify an application-configured algorithm; validate issuer/audience; use explicit typing and mutually exclusive rules to prevent cross-JWT confusion | Exact `RS256` allowlist, exact issuer/scalar audience, exact `typ=at+jwt`, closed header and required-claim sets |
| [IETF RFC 9068](https://www.rfc-editor.org/rfc/rfc9068.html) | Signed JWT access-token profile, asymmetric signatures, explicit access-token type | Public RSA JWKS only; API keeps no signing key; demo issuer emits `at+jwt` tokens |
| [NIST SP 800-207](https://csrc.nist.gov/pubs/sp/800/207/final) | Network location grants no implicit trust; authenticate and authorize before resource access | Loopback is only an egress restriction, never identity; middleware authenticates before body parsing and Agent/resource work |
| [OWASP LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) | Execute tools in the user's authorization context with minimum permissions | Verified tenant/region/groups enter the existing ACL; service operator roles never enter Agent `UserContext` |

The verifier therefore never takes algorithm authority from an untrusted
header; claims are not trusted until signature and validation complete; and an
access token cannot be substituted with another JWT kind accepted under a
broader parser profile.

Use `PyJWT==2.13.0` and `cryptography==49.0.0`. They are mature domain
libraries; cryptographic parsing and signature verification will not be
hand-written. PyJWT receives an exact one-element algorithm allowlist.

This mapping is not a claim of NIST/OWASP certification, OAuth conformance, or
production IdP integration. R2-S5 deliberately implements a local reproducible
resource-server boundary; discovery, revocation, login, key custody, and
enterprise policy administration remain non-goals.

## 5. Trust model

Trusted for this stage:

- local operator and filesystem permissions;
- reviewed Python environment and pinned dependencies;
- private key under ignored `.private/identity/`;
- checked configuration for issuer, audience, token type, clock skew, and
  lifetime;
- public JWKS loaded from the configured local file at service construction.

Untrusted:

- all HTTP headers and body fields;
- JWT header and claims before successful verification;
- `kid`, `typ`, `alg`, subject, tenant, region, groups, and roles from a token;
- request IDs, questions, feedback text, and trace IDs;
- any key file outside the configured canonical path.

Out of scope:

- compromised host, Python runtime, private key, or trusted local operator;
- hardware-backed keys and external attestation;
- real IdP availability and remote cache behavior.

## 6. Components

### 6.1 `Principal`

A strict immutable model owned by `app.security.identity`:

```text
subject       non-empty bounded string
tenant_id     non-empty bounded string
region        non-empty bounded string
groups        1..50 unique bounded strings
roles         0..50 unique bounded strings
issuer        exact configured issuer
audience      exact configured audience
key_id        validated configured JWKS key ID
issued_at     UTC timestamp
expires_at    UTC timestamp
```

Only the verifier creates a `Principal`. It is not accepted by request models.

### 6.2 `IdentityVerifier`

A narrow protocol:

```python
verify_bearer(authorization_header: str | None) -> Principal
ready() -> None
```

`LocalJwtIdentityVerifier` implements it. A fail-closed unavailable verifier is
used when configuration cannot be loaded so module import remains safe while
readiness reports identity failure.

### 6.3 `LocalJwksKeyProvider`

At construction, read one bounded JWKS file into an immutable key map. Limits:

- maximum file size: 64 KiB;
- maximum keys: 8;
- unique non-empty `kid` values;
- RSA public keys only;
- `alg` exactly `RS256`;
- `use` absent or `sig`;
- `key_ops` absent or containing only `verify`;
- modulus at least 2048 bits;
- no private RSA members;
- regular file only, no symlink/reparse point, canonical path required;
- duplicate JSON object keys rejected before typed parsing.

Unknown `kid`, malformed JWKS, unreadable file, replacement during snapshot,
or unsupported key metadata fails closed. Rotation is an explicit config event:
the JWKS may contain old and new public keys during overlap, then the service is
restarted to adopt the immutable snapshot.

### 6.4 `PrincipalMapper`

The mapper performs a pure deterministic conversion:

```text
Principal.subject   -> UserContext.user_id
Principal.tenant_id -> UserContext.tenant_id
Principal.region    -> UserContext.region
Principal.groups    -> UserContext.groups
[]                  -> UserContext.roles
```

`Principal.roles` is a service-boundary authorization input only. It may grant
access to API operations such as metrics and trace lookup, but it is never
forwarded into the Agent's `UserContext`, retrieval policy, prompt, or model.
This prevents a deployment role such as `rag.operator` from becoming a
document-access shortcut. No request value, query-analysis output, model
output, or fallback default may change this mapping.

### 6.5 FastAPI identity boundary

Authentication must run before FastAPI body validation so a missing or invalid
token plus a malicious body returns the authentication decision rather than a
schema oracle. A boundary middleware reads exactly one `Authorization` header,
calls the service-container verifier, and stores the verified `Principal` in
request-local state. Route dependencies retrieve that principal and enforce
the exact configured operator role. Every denied request must leave query
analysis, retrieval, model, trace-read, and feedback-write counters at zero for
the protected operation.

The API error abstraction must preserve response headers. The fixed status
contract is:

- missing, malformed, or invalid token: `401`, with
  `WWW-Authenticate: Bearer`;
- valid token without the exact operator role: `403`;
- verifier/JWKS unavailable: generic `503 identity_unavailable` with
  `retryable=true` and no filesystem or key detail.

## 7. Token contract

Before signature verification, the compact token is bounded and parsed with a
duplicate-key-rejecting JSON decoder. It must contain exactly three non-empty
base64url segments. Both decoded header and payload must be JSON objects.

Header requirements are an exact allowlist:

```json
{"alg":"RS256","kid":"<known-key-id>","typ":"at+jwt"}
```

Required claims:

```json
{
  "iss": "<configured issuer>",
  "aud": "<configured audience>",
  "sub": "<user id>",
  "iat": 0,
  "exp": 0,
  "tenant_id": "<tenant>",
  "region": "<region>",
  "groups": ["<group>"],
  "roles": []
}
```

`nbf` is optional but validated when present. `exp - iat` must be positive and
no greater than the configured maximum, default 900 seconds. Clock skew is
bounded, default 30 seconds. Strings and collection counts reuse the
`UserContext` limits. Unknown claims are ignored, never propagated or logged.

Additional fail-closed rules:

- duplicate JSON keys in either header or payload are rejected;
- `jku`, `jwk`, `x5u`, `x5c`, `crit`, `zip`, and every other unlisted header
  member are rejected;
- `kid` is bounded printable ASCII and must identify exactly one pinned key;
- `aud` is one exact scalar string, not an audience array;
- `iat`, `exp`, and optional `nbf` are integers, with booleans and floats
  rejected;
- the algorithm is fixed by configuration as `RS256`, never selected from an
  untrusted token;
- private-key members and remote key references are never accepted.

## 8. Route policy

| Route | Authentication | Authorization |
|---|---|---|
| `GET /health/live` | public | public |
| `GET /health` | public deprecated compatibility | public |
| `GET /health/ready` | public | low-sensitivity status only |
| `GET /identity/me` | bearer | any valid principal |
| `POST /agent/v2/chat` | bearer | any valid principal |
| `POST /feedback` | bearer | any valid principal |
| `GET /observability/metrics` | bearer | `rag.operator` |
| `GET /observability/traces/{request_id}` | bearer | `rag.operator` |

The original design retained a named local compatibility factory. Final
independent review rejected that control because an ASGI factory cannot prove
the socket chosen by an external wrapper. The implemented boundary therefore
removes the factory from the production module entirely. Legacy `/ingest`,
`/chat`, and `/agent/chat` remain historical code/evaluation concepts below
the deployable HTTP boundary. Production rollback never restores those routes
or body-supplied identity.

## 9. Request and response contracts

`AgentV2ChatRequest` becomes:

```json
{"question":"...","top_k":5}
```

`user_context` remains forbidden. `/identity/me` returns exactly `subject`,
`tenant_id`, `region`, `groups`, `roles`, `issuer`, `audience`, and `key_id` so
the local UI can display the authenticated profile and the lifecycle CLI can
prove that a restarted API snapshot accepts the pending key. Issuer and
audience are already claims in the caller's validated token, while key ID is
already in its protected header; none is private key material. The endpoint
never returns timestamps, raw tokens, token hashes, key paths, JWK values, or
additional claims.

Error precedence and safe responses:

- missing Authorization produces `401 authentication_required`;
- malformed Authorization or bad signature/header/claims/time/issuer/audience/
  kid: `401 invalid_token`;
- valid principal without operator role: `403 insufficient_role`;
- valid token plus forbidden body identity: `422` schema failure;
- unavailable local key configuration: `503 identity_unavailable`,
  `retryable=true`; readiness identity status is `error`, without path/key
  details.

All 401 responses include `WWW-Authenticate: Bearer`. No response distinguishes
unknown key, bad signature, expired token, or claim failure.

## 10. Readiness and observability

Readiness adds an `identity` check. It reports only `ok` or `error`; it does not
expose issuer, audience, path, key count, key IDs, claims, or exception text.

Low-sensitivity denied-request telemetry may record route, HTTP status,
latency, decision code, and `model_calls=0`. It must not create an Agent trace,
perform trace lookup, run retrieval, or write feedback. Raw
Authorization headers, tokens, claims, subjects, tenants, groups, roles, JWKS,
or key paths never enter logs, traces, metrics, error bodies, feedback, or
public evidence.

The request-context middleware continues to record route/status/timing and
model-call counts. `/identity/me` is the sole intentional authenticated
identity-disclosure endpoint and returns only its documented safe fields.
`rag.operator` is a deployment-wide service role: it authorizes global metrics
and trace access, but never document retrieval or Agent behavior.

## 11. Feedback identity binding

Add a pseudonymous actor identifier to `feedback_events`. It is computed with
HMAC-SHA-256 and a dedicated server-side secret that is independent from the
JWT signing key:

```text
HMAC-SHA-256(actor_key,
  "r2-s5-feedback-actor-v1\0" + issuer + "\0" + subject)
```

Plain SHA-256 is forbidden because low-entropy subjects could be enumerated.
The HMAC key is loaded from bounded, ignored local secret material with the
same regular-file/no-symlink/hardlink and owner/permission discipline as other
identity material. The database never receives the bearer token, HMAC key, raw
claims, question, or answer. Migration is idempotent for an existing local
SQLite database. Historical rows receive a fixed non-identifying sentinel
rather than guessed identity.

Successful chat returns `X-Feedback-Receipt`, a domain-separated HMAC binding
the verified actor, issuer/audience, target request ID, and keyed
question/answer digests. Feedback must return the exact receipt; missing,
malformed, wrong-actor, wrong-target, or modified-content bindings are rejected
before persistence. The database stores only keyed digests and atomically
upserts one latest rating per actor/target/question-HMAC/answer-HMAC. This proves binding to bytes served
by this API instance; it is not a distributed durable answer registry.

## 12. Local demo workflow

`python -m scripts.manage_demo_identity init`:

- creates ignored RSA private-key material, `jwks.json`, an identity manifest,
  an independent feedback HMAC key, persona tokens, and separate load/operator
  token files atomically;
- refuses overwrite unless an explicit rotation command is used;
- restricts private-key permissions where the platform supports it;
- prints only non-secret status such as active/known key IDs and persona count,
  never private bytes or bearer values.

`python -m scripts.manage_demo_identity rotate` stages a pending RSA key and
adds its public key to JWKS, but leaves the active key and all client tokens
unchanged. After the API restarts with old + pending public keys,
`activate --kid <pending> --api-base-url http://127.0.0.1:8000` sends a short
pending-key probe to `/identity/me`. Only an HTTP 200 response carrying the
exact expected `key_id` permits active-key and token publication.

`python -m scripts.manage_demo_identity retire --kid <old-kid>` removes only a
non-active key after the overlap window; it can also cancel a pending stage.
Activation persists the old key's retirement deadline as maximum token
lifetime plus the maximum allowed verifier skew, so later configuration drift
cannot shorten the overlap. Normal retirement and journal recovery reject an
earlier deletion. Emergency retirement requires the exact break-glass
confirmation and appends a non-secret audit event. `status` prints
active/pending/keyring/deadline and emergency-count metadata without changing
an unrelated directory. Manifest commit, bounded journal recovery,
owner/permission/link checks, POSIX directory-identity binding, and bounded
Windows/POSIX locks fail closed.

The CLI also creates an ignored persona bundle for the checked-in synthetic
demo identities. Streamlit selects a server-issued token for the chosen
scenario; it never signs tokens or reads the private key. User-persona tokens
and operator tokens are separate so ordinary chat cannot silently inherit
global observability access.

### 12.1 Client transport and token contract

Local mode accepts only one canonical numeric-loopback API origin such as
`http://127.0.0.1:8000`: no userinfo, non-root path, query, fragment, hostname
alias, or redirect. The HTTP session disables environment proxy inheritance
(`trust_env=false`) and redirects (`allow_redirects=false`) so a bearer token
cannot be forwarded to another origin. Any future nonlocal mode requires an
explicit HTTPS origin allowlist and is outside this stage.

Public, persona, and operator traffic use distinct cookie-rejecting sessions.
The Streamlit server itself binds to `127.0.0.1`; it never exposes local demo
credentials on a LAN/WAN listener. A feedback receipt is transient state for
only the current answer and is cleared after a successful rating.

`RAG_BEARER_TOKEN` and `RAG_BEARER_TOKEN_FILE` are mutually exclusive. A token
file is read afresh for each request, is bounded, must be a regular
non-symlink/reparse file, and is never placed in Streamlit session state,
exceptions, or logs. Persona-bundle parsing applies the same file and
duplicate-JSON-key restrictions. The client sends Authorization only to
protected routes on the validated origin.

`scripts/load_profile.py` follows the same boundary: it no longer sends body
identity, uses separate user and operator token providers, never persists or
prints a token, and uses the operator credential only for metrics/trace reads.

## 13. Security evaluation matrix

The fixed negative matrix includes:

1. missing header;
2. wrong scheme and duplicate/ambiguous Authorization;
3. oversized token;
4. malformed compact JWT;
5. `alg=none`;
6. HS/RS algorithm confusion;
7. invalid signature;
8. missing/unknown/duplicate `kid`;
9. wrong `typ`;
10. expired token;
11. future `nbf`;
12. future `iat` beyond skew;
13. excessive lifetime;
14. wrong/missing issuer;
15. wrong/missing audience;
16. missing/empty subject;
17. missing/malformed tenant, region, groups, or roles;
18. duplicate or oversized groups/roles;
19. body identity override;
20. missing/unreadable/malformed/oversized JWKS;
21. duplicate JWKS JSON keys or duplicate key IDs;
22. private/small/unsupported JWK;
23. key rotation old/new overlap and retired-key rejection;
24. valid non-operator access to metrics/trace;
25. identity/token markers in errors, traces, metrics, feedback, or public audit.
26. duplicate JWT header or payload JSON keys;
27. remote-key or critical/compression header members;
28. scalar-versus-array audience and non-integer timestamp confusion;
29. client origin confusion, redirects, environment proxy inheritance, token
    source ambiguity, unsafe token file, and persona/operator credential mix;
30. enumerable feedback actor IDs, missing feedback target request IDs, missing
    receipt, receipt tampering, and modified answer content;
31. compatibility-app non-loopback/deployment use;
32. missing/uncommitted identity manifest, artifact digest mismatch, unsafe
    owner/mode/DACL, hardlink, and crash-recovery journal inconsistency;
33. incomplete WAL checkpoint, actor/target/content feedback replay, and
    caller-reused request IDs.

Every denied case must prove the protected side-effect counters remain zero.

## 14. Acceptance gates

- Valid JWT derives the exact expected `UserContext` and retrieves only matching
  tenant/region/group documents.
- Every negative token is denied before retrieval/model and exposes zero
  unauthorized documents, citations, traces, or feedback writes.
- Metrics and trace endpoints require `rag.operator`.
- Body `user_context` cannot override token claims.
- Staged key rotation, snapshot proof, old/new overlap, cancellation, crash
  recovery, and retirement behavior are deterministic.
- A dedicated local benchmark artifact records 1,000 warm verifications and
  p50/p95 with hardware and method; p95 <= 10 ms is a local evidence target,
  not a shared-CI wall-clock gate.
- No token/claim/key leakage in service outputs or repository audit.
- Focused identity/API/UI/security tests, full historical suite, compile, pip
  consistency, public audit, and exact-SHA Ubuntu/Windows CI pass.

OpenAPI, `/docs`, and `/redoc` remain public because they disclose only the
intended API schema; protected operations still require authentication.

## 15. Rollback

Rollback means reverting to a previous immutable service build that already
has a trusted identity boundary. Protected routes stay unavailable if no such
build is deployable. Retired legacy routes are not a production rollback
target and cannot be re-enabled through an app factory.
Restore the previous public JWKS snapshot, restart the secure service, check
readiness, then run valid/invalid token smoke tests.

## 16. Security-review disposition and implementation state

The completed design review reported zero Critical findings, ten Important
contracts, and three Minor contracts. Their disposition is frozen as follows:

| ID | Review contract | State on 2026-07-22 |
|---|---|---|
| I-1 | Exact local origin, no proxy inheritance or redirects | implemented; focused UI/load tests passed |
| I-2 | Preserve 401 challenge; exact 401/403/503 semantics | implemented; identity API suite passed |
| I-3 | Strict compact JWT, duplicate-key/header/audience/time rules | implemented; focused identity/JWT tests passed |
| I-4 | Keep service roles out of Agent `UserContext` | implemented; mapper and HTTP-boundary proof passed |
| I-5 | Ignored persona bundle and separate operator credential | implemented; lifecycle/client tests passed |
| I-6 | Migrate `scripts/load_profile.py` to token providers | implemented; focused load-profile tests passed |
| I-7 | HMAC actor and `target_request_id` | implemented; persistence and legacy SQLite migration tests passed |
| I-8 | Bounded denied telemetry and no Agent/lookup side effects | implemented; 20-case evaluator reports zero denied side effects/leaks |
| I-9 | Compatibility app is explicitly acknowledged and never a rollback target | production factory and legacy routes removed; historical evaluation remains below HTTP |
| I-10 | Strict audience/operator config and dependency snapshots | implemented; local `pip check` clean, Ubuntu/Windows CI pending |
| M-1 | Performance target is a local artifact, not shared-CI timing | source-bound ephemeral benchmark; 1,000 warm p95 = 0.0904 ms |
| M-2 | Keep public docs/OpenAPI as low-sensitivity schema | implemented; local public audit passed |
| M-3 | Exclusive, bounded, freshly read, no-symlink token source | implemented; focused token-source/client tests passed |

The pre-review `1,835 passed / 20 skipped`, old matrix result, and earlier
timing results are historical inputs, not current release evidence. The current
source-bound benchmark run
`identity-benchmark-20260723T124717Z-668f464566bb` reports 1,000 warm
verifications at p95 0.0904 ms and the current public audit reports 515/0.
The fresh source-bound matrix passes `20/20`, the repaired whole tree passes
`1,918 / 22 skipped / 3 known warnings`; post-CI scoped re-review reports
zero Critical/Important/Minor. Exact-SHA CI #17 rejected commit `d753df3`;
the original three failures and later TOCTOU/handle findings are repaired and
pass the affected local contract group. A replacement commit and exact-SHA Ubuntu/Windows CI remain mandatory
for remote acceptance. Even a complete gate establishes the local contract,
not a production IdP or deployment certification.

## 17. Claims boundary

On completion the project may claim a deterministic local trusted-identity
boundary with synthetic RSA JWT/JWKS, route authorization, privacy tests, key
rotation tests, and local/CI evidence. It may not claim real SSO, production IAM,
remote JWKS availability, revocation, user lifecycle management, public cloud
deployment, or production readiness.
