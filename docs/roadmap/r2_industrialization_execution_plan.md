# R2 Industrialization Execution Plan

Status: current after R2-S4 Task 8.

R2-S4 published a `CONSISTENT_OBSERVATION` across two frozen local chat models
on the same visible synthetic dev cohort. That observation is useful evaluation
operations evidence, but it is not a release pass and not cross-model
generalization. The remaining implementation sequence is therefore deliberately
narrow.

## Priority

Only admitted next implementation: R2-S5 Trusted Identity Boundary.

Rank 2: reproducible minimal Linux deploy/rollback.

Rank 3: durable privacy-bounded telemetry.

These are not parallel approvals. R2-S5 must be designed and gated first because
the serving API still trusts request-body identity.

## R2-S5 Trusted Identity Boundary

### Trigger

`/agent/v2/chat` accepts a caller-supplied `UserContext`. ACL and retrieval
guards validate data flow, but they do not prove tenant, group, or user identity
came from a trusted issuer.

### User value

Enterprise users need tenant and group isolation that does not depend on a
browser or API caller self-reporting identity fields correctly.

### Minimal architecture

Add a pinned issuer/audience/algorithm token verifier at the API boundary.
The contract path is Bearer -> pinned JWT verifier -> Principal -> deterministic UserContext -> existing AccessPolicy.
Derive a server-owned `Principal`, map it deterministically to `UserContext`,
and reject before query analysis, retrieval, model calls, traces, or feedback
when identity is absent or invalid. Protect chat, trace, metrics, and feedback
with the same derived principal.

### Contracts

- `/agent/v2/chat` removes and rejects body-supplied `user_context`; it cannot
  override the server-derived principal. Any compatibility factory remains
  offline-only and cannot be enabled by a runtime request field.
- Tenant, region, groups, and user id come from server-derived claims.
- Deny-before-retrieval and deny-before-model-call are mandatory.
- Trace and metrics access require a server-derived operator role; feedback
  uses the authenticated user principal.
- liveness remains public; readiness remains low-sensitivity and does not expose
  tenant, group, user, token, claim, or key material.
- The JWT negative matrix covers invalid signature, alg=none, algorithm confusion, expired token, nbf in future, unknown kid, wrong issuer, wrong audience, missing tenant claim, missing subject claim, oversized token, and JWKS outage.
- Key rotation and issuer/audience changes are explicit config events; key cache and rotation fail closed.

### Local gates

- Valid token permits only matching tenant/group documents.
- 100% negative tokens return 401/403 before retrieval/model, and
  retrieval/model counters stay zero.
- 0/N unauthorized docs, citations, and traces.
- 0 token/claim leaks in traces, metrics, errors, feedback, or public evidence.
- 1000 warm verifications p95 <= 10ms with reported hardware.
- full historical/security/public audit exact-SHA Linux CI.

### Security

Use an allowlisted algorithm, pinned issuer, pinned audience, bounded clock
skew, and key-id based JWKS lookup or local pinned keys. The key cache is
bounded; unknown key ids and JWKS outage fail closed unless an explicit tested
last-known-good window is configured. Treat token validation errors as
authentication failures, not model-visible content.

### Rollback

Keep the current local-demo profile behind an explicit development flag. Roll
back by disabling the trusted-identity route and restoring the local-only
profile. Rollback must not restore public body-supplied identity. The real IdP integration remains outside the local contract.

### Deferred tech-stacking

LangGraph, vector DB, Kubernetes, Redis, Kafka, multi-Agent delegation,
long-term memory, broad model registries, and rerankers are deferred. None of
them fixes the identity trust boundary, and none is admitted by the R2-S4
result.

## Rank 2: Reproducible Minimal Linux Deploy/Rollback

Trigger: R2-S5 passes locally and a non-Windows staging or pilot environment is
needed.

User value: operators can reproduce a minimal service image, inspect its SBOM,
run health checks, and roll back without preserving local developer state.

Minimal architecture: pinned Python image, non-root process, explicit runtime
env contract, mounted model endpoint config, health/readiness probes, and a
documented rollback command.

Contracts: same frozen tests, public audit, compile/pip checks, and security
gates run inside the image before promotion.

Local gates: image build, smoke API, readiness, rollback drill, no secret leak,
and exact public audit.

Security: no baked secrets, no writable code directory, least-privilege runtime
user, and explicit model endpoint allowlist.

Rollback: stop new image, restore previous immutable image tag and active index
pointer, then rerun readiness and smoke tests.

Deferred tech-stacking: Kubernetes and service mesh remain deferred until there
is a measured orchestration failure that a single-host minimal deployment cannot
handle.

## Rank 3: Durable Privacy-Bounded Telemetry

Trigger: local bounded in-memory traces are insufficient for staging operations,
incident review, or cross-process correlation.

User value: operators can investigate failures without storing prompts,
answers, canaries, credentials, or raw document content.

Minimal architecture: OpenTelemetry-compatible events with redaction,
retention, access controls, request ids, run ids, and trace-to-evaluation
links.

Contracts: telemetry records hashes, counts, timings, decision labels, and
artifact ids only; sensitive content remains out of scope.

Local gates: redaction tests, retention tests, trace correlation tests,
sampling tests, and public audit.

Security: least-privilege collector credentials, no raw content, and tenant
isolation on trace lookup.

Rollback: disable exporter and keep local in-memory traces while preserving API
behavior.

Deferred tech-stacking: Kafka, Redis, queueing, long-term memory, and analytics
warehouses remain deferred until telemetry volume and retention requirements
justify them.

## Still Not Run

```text
independent holdout         NOT RUN
semantic judge calibration NOT RUN
human double review        NOT RUN
production traffic         NOT RUN
real IdP                   NOT RUN
deployment                 NOT RUN
```
