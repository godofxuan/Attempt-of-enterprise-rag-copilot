# R2-S1 D5 Prompt Boundary and Security Observability Plan

> Status: D5 implemented and locally verified on 2026-07-17. D6 datasets, OFF/ON evaluation, and live model trials remain out of scope and `NOT RUN`.

## Goal

Close the remaining post-Guard trust boundaries on the default V2 service path:

1. frame admitted retrieved evidence as JSON data inside a per-build nonce envelope;
2. expose only frozen aggregate Guard counters in public Agent tool-step trace;
3. make the default FastAPI factory omit legacy `/ingest`, `/chat`, and `/agent/chat` routes;
4. reject an invalid detector policy during default container construction and report only `retrieved_guard=ready|error` at readiness time.

## Non-goals

- no new detector rules or detector-version change;
- no request field, environment switch, or public endpoint for `audit`/`off` mode;
- no raw, normalized, decoded, quarantined, document-identity, nonce, or canary data in trace;
- no D6 fixture generation, fake OFF/ON evaluator, live Ollama run, or security-rate claim;
- no changes to frozen R1 evaluation data.

## TDD Sequence

### 1. Prompt envelope

Modify tests first in `tests/agent_v2/test_generation_v2.py`.

- inject a deterministic nonce factory;
- assert exact matching begin/end/reminder lines;
- parse the enclosed evidence with `json.loads`;
- put quotes, newlines, role labels, and a forged delimiter in admitted test content and prove they remain inside one JSON string rather than becoming a host delimiter;
- assert trusted instructions are system-only and the nonce/evidence are not copied to response trace;
- assert malformed nonce output fails closed without calling the model;
- preserve bounded source mapping and one bounded structured-output retry.

Production owner: `app/agent/generation_v2.py`.

Implementation choice: default nonce is `secrets.token_urlsafe(24)` and must match `[A-Za-z0-9_-]{16,64}`. Tests inject a factory. One fresh nonce is created per actual model call, including the optional shape-only retry; duplicate factory output fails closed. This follows the frozen per-call wording while the admitted evidence records remain immutable across attempts.

### 2. Public security aggregate

Modify tests first in `tests/agent_v2/test_runner_v2.py` and `tests/security/test_indirect_injection_red_baseline.py`.

- assert every executed retrieval tool step has one `retrieved_content_security` object;
- assert the object has exactly the D1 allowlisted counters plus `stop_reason`;
- prove categories/rule IDs are sorted static values;
- prove raw text, paths, IDs, quarantine summaries, hashes, canaries, and nonce are absent;
- keep terminal steps free of a fabricated Guard aggregate;
- keep service-level `RequestTrace` body-free.

Production owners: `app/domain/retrieved_security.py` and `app/agent/runner_v2.py`.

Implementation choice: add a frozen `RetrievedContentSecurityTrace` projection derived from validated `SecurityCounters`; never serialize `QuarantineSummary` itself.

### 3. Secure service composition

Add RED tests in `tests/api_v2/test_service_profiles.py` and adjust only legacy regression tests to use the explicit compatibility factory.

- default `create_app()` must return 404 for `/ingest`, `/chat`, and `/agent/chat`;
- default app must retain `/agent/v2/chat`, health, feedback, metrics, and trace routes;
- `create_compatibility_app()` may register legacy routes for local regression;
- neither request schema nor `create_app()` exposes a guard-mode or include-legacy flag.

Production owners: `app/main.py` and route-template constants in `app/runtime/resources.py`.

Implementation choice: an internal `_create_application(..., compatibility=...)` composes routes, while the two public factories have unambiguous fixed profiles. `app` is built only from the secure factory.

### 4. Detector startup/readiness

Modify tests first in `tests/runtime/test_resources.py` and `tests/api_v2/test_health.py`.

- validate detector version, rule allowlist, ruleset digest, clean decision, and guard-error decision during default container construction;
- make an injected invalid validator abort container construction;
- add a runtime Guard probe to readiness;
- expose only `retrieved_guard: ready|error`, never exception text, local paths, rule source, or digest;
- readiness is `not_ready` when the probe fails, while the remaining probes still execute.

Production owners: `app/security/retrieved_content.py` and `app/runtime/resources.py`.

Implementation choice: static policy invalidity prevents service construction; later runtime probe failure produces a safe readiness status. This preserves both fail-fast startup and diagnosable low-sensitivity health behavior.

## Verification Gates

1. Run each new test alone and capture the expected RED reason before production edits.
2. Run focused generation, runner/security, API-profile, and runtime suites until GREEN.
3. Run the existing D2/D4 propagation and guarded-boundary tests.
4. Run the complete offline pytest suite.
5. Run compile, repository contract/public audit, frozen R1 hash, and Git/process boundary checks already used by the project.
6. Request an independent read-only review; convert valid findings into RED tests before fixes.
7. Update README, architecture, observability, limitations, R2-S1 results/journal, status, and decision ledger with measured D5 evidence only.
8. Commit D5 locally and stop at the explicit D6 approval gate. Do not push unless separately requested.
