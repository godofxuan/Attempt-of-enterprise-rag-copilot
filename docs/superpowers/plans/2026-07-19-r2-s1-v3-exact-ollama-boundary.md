# R2-S1 V3 Exact Ollama Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and execute this plan inline. Do not dispatch or commit without explicit user approval.

**Goal:** Make `LocalOllamaOnlyBoundary` enforce the exact configured loopback host/address and port consistently for HTTP, `socket.connect`, and `socket.connect_ex`.

**Architecture:** Introduce one private immutable-in-practice origin policy that parses the already validated endpoint, canonicalizes literal IP addresses, and owns both URL and socket predicates. Keep the evaluator's process-global monkeypatch boundary, but protect activation with one non-blocking class lock so nested or concurrent boundaries fail closed instead of stacking patches.

**Tech Stack:** Python standard library (`ipaddress`, `socket`, `threading`, `urllib`), Requests, `unittest.mock.patch`, Pytest.

## Global Constraints

- Preserve the existing `LiveSecurityConfig` public schema and local HTTP-only endpoint requirement.
- Do not change Guard rules, retrieval behavior, model parameters, frozen datasets, the formal D7 run, or the V1 public package.
- Do not create real network side effects in tests; patch delegates before entering the boundary.
- Treat this as an evaluator call-graph boundary, not an operating-system sandbox.
- Reject explicit proxy configuration, redirects, credential-bearing URLs, alternate hosts, nested activation, and concurrent activation.
- Do not begin V4 metric semantics or V5 arm-order work.
- Do not commit, push, merge, or tag without separate approval.

---

## File Map

- Modify `app/evaluation/indirect_injection_live_runner.py`: exact origin policy, shared URL/socket predicates, proxy/redirect checks, activation lock, thread-safe counters.
- Modify `tests/evaluation/test_indirect_injection_live_runner.py`: all V3 RED/GREEN contract tests without real egress.
- Create `docs/security/r2_s1/13_v3_exact_ollama_boundary_engineering_journal.md`: implementation, failures, limitations, evidence, and interview explanations.
- Modify `README.md` and `PROJECT_STATUS.md`: current V3 status and measured verification only.

### Task 1: Freeze exact IPv4 and IPv6 policy with RED tests

**Interfaces:**

- Consumes: `LocalOllamaOnlyBoundary(endpoint: str)` as a context manager.
- Produces: one policy used by `_is_allowed_url()` and `_is_allowed_socket()`.

- [x] Add tests proving configured IPv4 HTTP/connect/connect_ex are delegated and counted.
- [x] Add tests proving `127.0.0.2`, `::1`, an external address, and a wrong port are blocked when configured for `127.0.0.1:11434`.
- [x] Add tests proving configured `::1:11434` works for HTTP/connect/connect_ex while IPv4 and other IPv6 addresses are blocked.
- [x] Run the tests and retain failures showing alternate loopback addresses are currently accepted.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/evaluation/test_indirect_injection_live_runner.py -k "boundary and (ipv4 or ipv6 or connect_ex)" -q
```

Expected RED: alternate loopback calls reach the fake delegate instead of raising `RuntimeError`.

### Task 2: Freeze HTTP, proxy, redirect, urllib, and accounting behavior

**Interfaces:**

- Consumes: Requests `Session.request`, urllib `urlopen`, and fake response objects.
- Produces: deterministic `allowed_http_request_count`, `allowed_socket_connect_count`, and `blocked_attempt_count` semantics.

- [x] Add a credential/alternate-host/explicit-proxy test; original request must not run.
- [x] Add a redirect test; original exact-origin request runs once with `allow_redirects=False`, then the 3xx response is blocked.
- [x] Add an urllib test; every `urlopen` call is blocked.
- [x] Assert exact counters after each scenario.
- [x] Run and retain RED failures for proxy handling or inaccurate counts.

Counter contract:

```text
allowed HTTP request that returns 3xx: allowed_http += 1 and blocked += 1
rejected URL/proxy/urllib: blocked += 1 only
allowed connect/connect_ex attempt: allowed_socket += 1 even if the fake delegate returns an error code
rejected socket: blocked += 1 only
```

### Task 3: Freeze global patch lifecycle behavior

**Interfaces:**

- Consumes: the process-global Requests/socket monkeypatches.
- Produces: fail-closed single-active-boundary lifecycle.

- [x] Add a nested context test and expect `RuntimeError` before the inner patches are installed.
- [x] Hold one boundary open and attempt a second activation from a worker thread; expect deterministic rejection and no hang.
- [x] Exit the outer boundary and prove a fresh boundary can activate, showing the lock is released.
- [x] Run and retain RED failures showing current nested/concurrent patch stacking.

### Task 4: Implement the minimal shared policy and lifecycle guard

**Interfaces:**

- Produce `_ExactLoopbackOriginPolicy.allows_url(value: str) -> bool`.
- Produce `_ExactLoopbackOriginPolicy.allows_socket(address: object) -> bool`.
- Keep `LocalOllamaOnlyBoundary._is_allowed_url()` and `_is_allowed_socket()` as thin delegates for compatibility.

- [x] Parse the endpoint once through `LiveSecurityConfig`.
- [x] Canonicalize numeric IPv4/IPv6 with `ipaddress.ip_address` and preserve exact hostname identity for `localhost`.
- [x] For `localhost`, resolve once and reject construction if any resolved address is non-loopback; direct alternate host spellings remain blocked.
- [x] Require exact HTTP scheme, configured host identity, configured port, no credentials, and no fragment.
- [x] Require exact socket host identity/address and port; reject booleans, malformed tuples, aliases, alternate families, and other loopback addresses.
- [x] Reject non-empty caller/session proxies and explicit Host overrides; force Requests environment proxy keys to `None` for the delegated local request.
- [x] Add a class-level non-blocking lock and exception-safe acquire/patch/release lifecycle.
- [x] Protect counters with a per-instance lock.
- [x] Run all V3 tests to GREEN, then rerun the entire live-runner file.

### Task 5: Regression, frozen evidence, and documentation

- [x] Run live/deterministic writer and security evaluator tests.
- [x] Run the full repository suite.
- [x] Run the V1 standalone verifier, public repository audit, compileall, pip check, and `git diff --check`.
- [x] Recompute dataset, fixture, freeze-manifest, and formal-run hashes and compare with V2 entry values.
- [x] Document RED evidence, exact code flow, counter semantics, scope limits, encountered failures, and interview questions.
- [x] Stop before V4.

## Acceptance Criteria

- A numeric IPv4 endpoint permits only the exact canonical IPv4 address and port.
- A numeric IPv6 endpoint permits only the exact canonical IPv6 address and port.
- HTTP and both socket methods consume the same configured policy.
- Wrong port, alternate loopback, external address, alternate hostname, credentials, proxy, redirect, and urllib are blocked.
- Nested and concurrent boundary activation fail deterministically and release cleanly.
- Every allowed/blocked counter matches the documented attempt semantics.
- Tests make no real network connection.
- Existing D7/V1 artifacts and frozen hashes are unchanged.
