# R2-S9 Engineering Journal

## 1. Initial Audit

The repository had:

- secure FastAPI liveness/readiness endpoints;
- an immutable versioned index and atomic `active.json` pointer;
- a local RS256/JWKS identity source;
- exact-SHA Ubuntu/Windows deterministic CI;
- no Dockerfile, Compose contract, deployment release ledger, SBOM, or
  container rollback exercise.

Docker was not installed on the Windows host. The implementation therefore
keeps local and remote claims separate: local contract tests are executable
now; image evidence must come from GitHub's Ubuntu runner.

## 2. Main Design Decisions

### 2.1 Why host networking

`127.0.0.1` inside a normal bridge-network container points to that container,
not to the Linux host. The existing security design intentionally rejects
remote or DNS model endpoints. A sidecar gateway would require a new network
trust design.

R2-S9 therefore uses Linux host networking, keeps the model at
`127.0.0.1:11434`, and binds the API to `127.0.0.1:8000`. This preserves the
loopback-only model contract with the smallest new operational surface.

### 2.2 Why two external mounts

The image contains application code only. Runtime state is separated into:

- `/var/lib/rag`: writable database, indexes, and lifecycle-private state;
- `/run/secrets/rag-identity`: read-only JWKS and feedback HMAC material.

This prevents a code rollback from silently restoring a developer database or
baking identity secrets into an image layer.

### 2.3 Why a release ledger is needed

An image digest alone does not identify the knowledge state. A
`DeploymentRelease` binds:

- immutable image reference;
- exact source commit;
- runtime contract SHA-256;
- exact index run ID and manifest SHA-256;
- predecessor release.

Readiness independently checks the expected index identity. This gives two
controls: operator-state validation before start and runtime validation after
start.

### 2.4 Why a pending transaction remains after failure

Updating two files cannot be one filesystem atomic operation. Silently deleting
the journal after a partial failure would hide a mixed release/index state.
R2-S9 leaves `pending.json`, blocks normal operations, and requires an explicit
restore-or-complete decision.

## 3. File-by-File Change Record

| File | Change | Reason |
|---|---|---|
| `app/security/model_endpoint.py` | One canonical parser for loopback model origins | Removed inconsistent URL handling across chat, embed, readiness, lifecycle, and OpenAI-compatible client paths |
| `app/clients.py`, `app/ollama_chat.py`, `app/retriever.py`, `app/lifecycle/pipeline.py`, `app/runtime/resources.py` | Route model URLs through the common parser | A configured remote origin must fail before transport |
| `app/config.py` | Added all-or-nothing deployment release/index binding | Prevent partial or malformed runtime release identity |
| `app/deployment/releases.py` | Append-only releases, active pointer, transaction journal, activation, rollback, recovery, env rendering | Makes deployment state deterministic and auditable |
| `scripts/manage_deployment.py` | Operator CLI for register/activate/rollback/recover/verify/render | Keeps release operations reproducible and scriptable |
| `scripts/probe_deployment.py` | Bounded loopback liveness/readiness probe | Promotion checks readiness and exact index, not only process existence |
| `Dockerfile` | Digest-pinned Python base, test/runtime stages, UID 10001, health check | Reproducible least-privilege image |
| `.dockerignore` | Excludes Git data, local secrets, models, databases, indexes, generated runs | Prevents secret/state build-context leakage |
| `deploy/compose.yaml` | Single-host least-privilege runtime contract | Makes mounts, resources, host network, and release binding explicit |
| `scripts/init_deployment_smoke_fixture.py` | Creates private good/bad index fixtures and identity material | Enables a real readiness and rollback CI drill without production data |
| `scripts/deployment_model_stub.py` | CI-only loopback model protocol stub | Tests API readiness deterministically without downloading large models |
| `scripts/generate_deployment_sbom.py` | SPDX 2.3 Python package inventory | Produces inspectable dependency evidence without a third-party SBOM generator |
| `.github/workflows/ci.yml` | Added Linux image, in-image gates, runtime drill, rollback, SBOM artifact | Converts deployment claims into exact-commit evidence |

## 4. Problems Found During Implementation

### 4.1 Test fixture bypassed Pydantic validation

Observed result:

```text
25 passed, 1 failed
```

The immutable-image test used `model_copy(update=...)`. Pydantic does not
revalidate update values in that operation, so the test created an impossible
already-validated object and incorrectly concluded the validator did not run.

Fix: reconstruct the model from a raw dictionary with `model_validate`.

Lesson: tests for input rejection must enter through the same parsing boundary
as production input. Internal copy helpers can bypass that boundary.

### 4.2 Permanent probe configuration errors were retried

Observed result:

```text
30 passed, 1 failed
```

A remote probe URL was rejected, but the rejection happened inside the retry
loop. The caller waited until the deadline and received `RuntimeError` instead
of an immediate `ValueError`.

Fix: validate and close a connection object before entering the retry loop.
Only transient connection/readiness failures are retried.

Lesson: classify permanent configuration errors separately from transient
service availability errors.

### 4.3 Docker unavailable locally

The `docker` executable is absent on the Windows host. No local image build,
container readiness, or container rollback result is claimed. Static and
Python behavior tests run locally; the Ubuntu CI job is the execution boundary
for Docker evidence.

### 4.4 Full-suite provenance and roadmap drift

The first full run ended with:

```text
2415 passed, 30 skipped, 2 failed
```

One failure was expected provenance drift: adding deployment/index validation
to `app/runtime/resources.py` changed that file's SHA-256 and therefore the
R2-S5 trusted-identity evaluation contract ID. All 20 case outcomes and safety
metrics remained identical. The evidence was regenerated and only those two
provenance fields changed.

The other failure was a governance test that still required R2-S6 to be the
current roadmap stage. It was updated to require R2-S9 as current, durable
privacy-bounded telemetry as next candidate, and the two-person R2-S8 review as
explicitly `NOT RUN`.

### 4.5 First Linux container run exposed a read-only cache conflict

Exact-commit Actions run
[`30260525575`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30260525575)
passed both deterministic OS jobs but failed the first
`linux-container-contract` run:

```text
deterministic-ubuntu-latest   PASS
deterministic-windows-latest  PASS
linux-container-contract      FAIL at "Run deterministic gates inside the image"
```

The image built and its non-root identity checks passed. The gate then failed
within two seconds. The first write-capable operation in that gate was
`compileall`: Python normally places compiled bytecode beside source files,
while the contract intentionally mounts the test container root filesystem
read-only.

Fix: preserve the read-only filesystem and redirect `HOME`, XDG cache, and
Python bytecode cache to the bounded `/tmp` tmpfs. Disable pytest's repository
cache provider so the test runner also does not attempt to create
`.pytest_cache` in `/workspace`.

Lesson: a read-only container is an operational invariant, so build and test
tools must receive explicit ephemeral write locations. Making the container
writable would hide the conflict and weaken the contract.

## 5. Current Verification

Focused deployment/security suite:

```text
31 passed, 3 third-party SWIG deprecation warnings
```

Repository configuration plus deployment/security suite:

```text
36 passed, 3 third-party SWIG deprecation warnings
```

The warnings come from FAISS SWIG types and do not indicate a failed deployment
contract.

Final local gates after the provenance and roadmap repairs:

```text
compileall                         PASS
pip check                          PASS
pytest                             2417 passed / 30 skipped / 3 warnings
public repository audit            915 candidates / 0 findings
git diff --check                    PASS (one existing CRLF normalization notice)
```

Image-build, container runtime, rollback-drill, and SBOM artifact results are
recorded only after the exact-commit Ubuntu job runs.

## 6. Honest Residual Risks

- The application dependency SBOM does not enumerate every Debian OS package.
  The exact base-image digest binds that layer, but a fuller registry/release
  process should add an OS-aware SBOM and vulnerability policy.
- Host networking is appropriate only for this single-host loopback design.
- Registry signing, provenance attestation, image push/pull rollback, real
  secret manager, and real IdP remain unimplemented.
- SQLite and local FAISS remain single-host state.
- Human double review, semantic judge calibration, production traffic, and a
  real deployment remain `NOT RUN`.
