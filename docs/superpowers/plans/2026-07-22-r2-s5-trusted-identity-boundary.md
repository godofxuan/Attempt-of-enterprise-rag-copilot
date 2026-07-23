# R2-S5 Trusted Identity Boundary Implementation Plan

Status: implementation authorized

Method: vertical TDD slices

Design: `docs/superpowers/specs/2026-07-22-r2-s5-trusted-identity-boundary-design.md`

Progress snapshot, 2026-07-23: Tasks 1-9 are implemented and the local portion
of Task 10 is complete. The frozen standalone evaluation matrix reports 20/20
passing cases, the isolated benchmark remains below its local target, and the
repaired full working tree reports 1,906 passing tests, 20 platform skips, and
three known warnings. Two independent reviewers report zero
Critical/Important. Commit/push and exact-SHA Ubuntu/Windows CI remain. This is
not a production IdP result.

## Delivery rules

- One observable behavior per RED/GREEN slice.
- Do not weaken the existing tenant/region/group `AccessPolicy`.
- No LLM is used for authentication or authorization.
- No private key or bearer token is tracked by Git.
- Every failure and correction is appended to the R2-S5 engineering journal.
- Do not claim real IdP or production readiness.

## Task 1: Dependency and configuration contract

Status: **implemented; local release gates passed**

Files:

- modify `requirements.txt`
- modify `app/config.py`
- modify `.env.example`
- add `tests/security/test_identity_config.py`

Behavior slices:

1. Settings expose canonical local JWKS path, fixed issuer/audience/algorithm,
   token type, maximum token size, lifetime, and clock skew.
2. Unsafe algorithms, empty issuer/audience, noncanonical or public-directory
   private material, and invalid bounds fail validation.
3. Dependency versions are pinned and `pip check` remains clean.

Additional frozen review work:

4. Audience and operator role are strict non-empty configuration values; the
   algorithm and token type remain literal allowlists.
5. Update exact dependency snapshot tests for PyJWT, cryptography, cffi, and
   pycparser; run `pip check` and Ubuntu/Windows CI before completion.

Evidence recorded: strict defaults, issuer/audience/operator validation,
private-path resolution, repository-path rejection, exact dependency snapshots,
and the focused configuration matrix pass. Final environment consistency and
Ubuntu/Windows CI remain part of Task 10.

## Task 2: Principal and bounded JWKS snapshot

Status: **implemented; full regression passed**

Files:

- add `app/security/identity.py`
- add `tests/security/test_identity_jwks.py`

Behavior slices:

1. A valid in-memory generated RSA public JWKS becomes an immutable key ring.
2. File size/key count/duplicate JSON key/duplicate `kid` limits fail closed.
3. Unsupported/private/small RSA keys and symlink/reparse paths fail closed.
4. Descriptor/path replacement tests verify snapshot consistency.

Evidence recorded: bounded immutable RSA public-JWKS loading, malformed and
duplicate input rejection, private/small/unsupported key rejection, unsafe-file
rejection, and rotation overlap/retirement behavior are covered by focused
tests. The final full-suite repetition passed as part of Task 10.

## Task 3: JWT verification and mapping

Status: **implemented; full regression passed**

Files:

- extend `app/security/identity.py`
- add `tests/security/test_identity_jwt.py`

Behavior slices:

1. One valid RS256 access token produces the exact strict `Principal`.
2. `Principal` maps deterministically to `UserContext`, excluding all service
   roles from the Agent context.
3. Header, signature, issuer, audience, time, lifetime, and claim negative
   cases return one safe authentication error category.
4. Unknown/retired `kid` fails; old/new overlap succeeds during rotation.
5. 1,000 warm verification performance test records p50/p95.

Strict-token review slices:

6. Pre-parse exactly three compact segments with bounded base64url decoding
   and duplicate-key-rejecting JSON for both header and payload.
7. Allow only `alg`, `kid`, and `typ`; reject remote-key, certificate,
   critical-extension, and compression members.
8. Require bounded printable-ASCII `kid`, scalar exact audience, and integer
   `iat`/`exp`/optional `nbf`; reject booleans and floats.

Evidence recorded: valid token mapping, malformed Bearer input, signature/kid/
type/header/issuer/audience/time/lifetime/claim cases, duplicate JSON keys,
service-role isolation, rotation overlap/retirement, and the separate local
1,000-verification benchmark pass. Current source-bound p95 is 0.0904 ms against the local
10 ms evidence target.

## Task 4: Service container and readiness

Status: **implemented; full regression passed**

Files:

- modify `app/runtime/resources.py`
- modify `tests/api_v2/helpers.py`
- modify readiness/resource tests

Behavior slices:

1. Service container owns the verifier; app factories do not accept runtime
   caller identity overrides.
2. Readiness includes only `identity: ok|error`.
3. Missing or malformed local JWKS does not leak path/key details and fails
   protected service operations closed.
4. Readiness also checks availability of the independent feedback-actor HMAC
   key without exposing its path or contents.

Evidence recorded: the service container owns both verifier and feedback actor
hasher; readiness exposes only `identity: ok|error`. A temporary failure caused
by omitting `readiness.identity` from the typed span allowlist was corrected and
covered by focused readiness tests. Database initialization now occurs only
during controlled `start()`; public refreshes use a serialized SQLite
`mode=ro` probe. Model readiness performs one actual embedding call and empty
Ollama preload calls for each distinct generation model, rather than treating
`/api/tags` membership as proof that model bytes can load.

## Task 5: Secure API boundary

Status: **implemented; full regression passed**

Files:

- add `app/api/identity.py`
- modify `app/main.py`
- modify `app/schemas.py`
- update `tests/agent_v2/test_api_v2.py`
- add `tests/api_v2/test_identity_api.py`

Behavior slices:

1. `/agent/v2/chat` requires Bearer and receives mapped identity.
2. Body `user_context` is rejected and never reaches the runner.
3. `/identity/me` returns only the safe mapped identity.
4. `/feedback` requires any principal.
5. metrics and trace require `rag.operator`; valid non-operator gets 403.
6. health endpoints remain public and low sensitivity.
7. Legacy compatibility does not weaken secure-route authentication.
8. Authenticate before body parsing; missing/invalid token plus malformed body
   returns 401 rather than a 422 schema oracle.
9. Preserve `WWW-Authenticate: Bearer`; return 403 only for a valid principal
   lacking the exact operator role; return generic retryable
   `503 identity_unavailable` when verifier material is unavailable.
10. Duplicate Authorization headers fail closed.

Evidence recorded: the identity API suite reported 17 passing tests, and one
real RS256 token integration test crossed the HTTP middleware into the API.
Authentication runs before body validation; exact 401/403/503 behavior and the
Bearer challenge are exercised.

## Task 6: Feedback actor binding and zero-leak observability

Status: **implemented; full regression passed**

Files:

- modify `app/db.py`
- modify feedback/observability/security tests

Behavior slices:

1. Chat issues a server HMAC receipt over the verified actor, target request
   ID, and keyed question/answer digests; feedback must return that receipt.
2. Existing SQLite tables migrate idempotently.
3. Token, claims, subject, tenant, groups, roles, key ID, and key path do not
   appear in errors, traces, metrics, logs under test, or persisted rows.
4. Denied requests have zero retrieval/model/feedback/trace-read side effects.
5. Low-sensitivity denial telemetry may contain route/status/latency/code and
   `model_calls=0`, but creates no Agent trace or trace-lookup side effect.
6. `/identity/me` is the sole documented identity-disclosure exception;
   `rag.operator` is global service authorization and never Agent authority.

Evidence recorded: feedback uses independent domain-separated actor/content
HMACs and a constant-time verified response receipt. Persistence stores no raw
question/answer or enumerable ordinary SHA-256. Migration is idempotent, drops
legacy plaintext, and only clears its durable erasure marker after VACUUM and a
complete WAL checkpoint. Actor/target replay is an atomic latest-rating upsert.

## Task 7: Local identity tooling

Status: **implemented; full regression passed**

Files:

- add `app/security/demo_identity.py`
- add `scripts/manage_demo_identity.py`
- add `tests/security/test_demo_identity_lifecycle.py`
- modify `.gitignore` only if current `.private/` coverage is insufficient

Behavior slices:

1. `init` atomically generates RSA private key and public JWKS without stdout
   secret leakage or overwrite.
2. `init` issues bounded synthetic persona and separate operator token
   artifacts without printing credential values.
3. `rotate` stages a pending public key without changing active client tokens;
   after API restart, `activate` proves the exact pending key through loopback
   `/identity/me` before publishing new tokens.
4. old/new overlap is persisted and enforced; ordinary retirement cannot
   delete a still-overlapping key, while an exact-confirmation emergency path
   leaves an audit event.
5. Unsafe paths, symlinks, malformed facts, duplicate users, and accidental
   tracked destinations fail closed.
6. Generate a bounded ignored persona bundle for synthetic demo users and a
   separate operator-token artifact; Streamlit never reads the private key.

Evidence recorded: `init`, `rotate`, `activate`, `retire`, and `status` are
implemented; old-snapshot denial, pending-key activation, enforced old/new
overlap, exact-confirmation emergency audit, one-step journal rejection,
cancel, crash recovery, and retired-key denial pass focused lifecycle tests. A Windows
`WinError 32` caused by replacing a temporary file while its handle was still
open was fixed by closing the handle before `os.replace` and retaining atomic
cleanup. The final implementation also uses a manifest commit point, journaled
crash recovery, write-through replacement, owner/mode/DACL/hardlink checks,
bounded cross-platform lock wait, semantic/final-byte journal validation,
POSIX root-identity binding, and explicit pending/restart status.

## Task 8: Streamlit/API client migration

Status: **implemented; full regression passed**

Files:

- modify `streamlit_app/api_client.py`
- modify `streamlit_app/shell.py`
- modify `streamlit_app/pages/1_Ask.py`
- modify `streamlit_app/pages/2_Trace.py`
- update UI tests

Behavior slices:

1. Client obtains a bounded token from env or a configured ignored file for
   every protected request.
2. Authorization is sent to chat, identity, trace, metrics, and feedback and
   never logged or included in exceptions.
3. Ask UI removes editable identity fields and selects a server-issued persona.
4. Missing/expired token produces a safe authentication state.
5. Local API base URL is one exact numeric-loopback origin with no userinfo,
   path, query, or fragment; disable environment proxies and redirects.
6. Reject simultaneous env-token and token-file configuration. Read a bounded
   regular no-symlink/reparse token file on each request and never place a
   token in session state, logs, or exceptions.
7. Select user persona tokens per scenario and use an explicitly separate
   operator token for metrics/trace.
8. Migrate `scripts/load_profile.py` to the same user/operator token providers,
   remove body identity, and never persist or print credentials.

Evidence recorded: the combined UI/load-profile checkpoint reported 54 passed.
Persona and operator credentials are separate, files are reread per request,
the local client accepts only canonical `http://127.0.0.1[:port]`, and requests
disable proxy inheritance and redirects. Public/persona/operator channels use
separate cookie-rejecting sessions; Streamlit binds to `127.0.0.1` and keeps a
feedback receipt only until the current answer has been rated.

## Task 9: Fixed R2-S5 security evaluation

Status: **implemented; deterministic gate passed**

Files:

- add `data/v2/security/r2_s5_identity_matrix_v1.json`
- add `scripts/eval_trusted_identity.py`
- add evaluation tests

Behavior slices:

1. Frozen matrix identity and SHA-256 are verified before execution.
2. Valid and negative rows report only case IDs, decision codes, timings, and
   side-effect counters.
3. Gate requires all negative cases denied, valid ACL cases correct, zero
   leakage, and zero denied side effects.
4. Output is immutable and public-safe; no raw token, key, or claims.
5. Add client-origin, redirect/proxy, token-source, persona/operator separation,
   HMAC-enumeration, compatibility-app, and strict JWT confusion cases.
6. Record 1,000 warm verifications, p50/p95, hardware, OS, and method in a
   dedicated local artifact. Treat p95 <= 10 ms as local evidence, not a
   shared-CI wall-clock gate.

Implemented evidence: the frozen matrix hash is
`fe5fdddd9cd4d067930b971ca0658a22deb63778723c31597df7f7fab70b4e2f`.
Its immutable evaluator reports 20/20 passing cases, 14 denied negative cases,
zero denied side effects, and zero credential leaks. A fresh result and the
checked-in public artifact are byte-identical with SHA-256
`2ec62b6e8eda35531b43a67263cec16dc42fb07e207ec2b43d22d1cfb6227c12`.
Evaluation schema v2 also binds a deterministic contract ID and ten source
SHA-256 values without adding cross-platform timestamps.
The current source-bound local benchmark records 1,000 warm verifications at
p95 0.0904 ms.

## Task 10: Documentation, review, and release gates

Status: **LOCAL PASS; two-reviewer 0/0 complete, commit/push and exact-SHA CI pending**

Files:

- maintain `docs/security/r2_s5/01_engineering_journal.md`
- maintain `docs/security/r2_s5/02_implementation_and_interview_guide.md`
- maintain `docs/security/r2_s5/03_results.md`
- update README, architecture, known limitations, roadmap, handoff, and
  interview guide

Gates:

1. Focused identity/API/UI/security suites.
2. Full historical suite.
3. `compileall`, `pip check`, frozen evaluation hash, and `git diff --check`.
4. Public repository audit and secret/token/key scans.
5. Independent whole-diff security review with zero Critical/Important.
6. Commit/push only after exact local gates; exact-SHA Ubuntu/Windows CI is the
   remote acceptance gate.
7. Keep OpenAPI, `/docs`, and `/redoc` public as intentional low-sensitivity
   schema endpoints and verify they contain no secrets or runtime identity.
8. Remove the compatibility factory from the production module; historical
   baselines remain below the HTTP deployment boundary and are never a
   production rollback target.

## Security-review work register

The independent review produced zero Critical, ten Important, and three Minor
items. Every item is assigned above; none is silently accepted as complete:

| Finding | Assigned task | Current state |
|---|---:|---|
| I-1 client origin/redirect/proxy exfiltration | 8 | implemented; focused tests pass |
| I-2 exact API 401/403/503 plus challenge header | 5 | implemented; focused tests pass |
| I-3 strict JWT parser and claim types | 3 | implemented; focused tests pass |
| I-4 service-role isolation | 3/5 | implemented through HTTP boundary |
| I-5 persona bundle and credential separation | 7/8 | implemented; focused tests pass |
| I-6 `load_profile.py` migration | 8 | implemented; focused tests pass |
| I-7 HMAC actor and feedback target | 4/6 | implemented; migration/privacy tests pass |
| I-8 observability/side-effect semantics | 5/6 | implemented; frozen evaluator reports zero denied side effects/leaks |
| I-9 compatibility-app deployment restriction | 5/10 | explicit acknowledgement and deployment docs implemented |
| I-10 strict config and dependency snapshots | 1 | implemented locally; Ubuntu/Windows CI pending |
| M-1 local-only timing evidence | 3/9 | source-bound ephemeral benchmark p95 0.0904 ms |
| M-2 public docs/OpenAPI decision | 10 | API proof and public audit pass locally |
| M-3 exclusive safe token source | 8 | implemented; focused tests pass |

A later two-reviewer candidate pass added seven Important findings: bounded
request-stream count/time, completed-journal postconditions, exact response-mode
documentation, single-source release evidence, benchmark exit/source gates,
credential-scanner blind spots, and the intentional `/identity/me` disclosure
contract. Their working-tree fixes are implemented, but only a fresh
zero-Critical/zero-Important review may close this register.
