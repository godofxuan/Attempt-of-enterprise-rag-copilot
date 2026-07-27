# R2-S9 Minimal Linux Deployment and Rollback Specification

Status: implementation complete locally; exact-commit Linux container CI is
pending until this change is pushed.

## 1. Problem

The secure API, immutable index lifecycle, and local identity boundary worked
on the developer machine, but the project had no reproducible service image or
operator rollback contract. Starting the Python process by hand did not bind
the running code to an immutable image or to the active index manifest.

R2-S9 addresses that operational gap. It does not claim production readiness,
high availability, Kubernetes support, a real identity provider, or production
traffic evidence.

## 2. Deployment Boundary

The admitted target is one Linux x86-64 host:

```text
host loopback
  |- local model service on 127.0.0.1:11434
  `- API container on 127.0.0.1:8000
       |- read-only application image
       |- writable /var/lib/rag data mount
       `- read-only /run/secrets/rag-identity mount
```

The API container uses host networking because the existing model trust
boundary accepts only an exact HTTP loopback origin. The API itself binds only
to numeric IPv4 loopback. This is a deliberate single-host design, not a
general container-network design.

## 3. Threat Model

In scope:

- a mutable image tag silently changing between deploys;
- `.env`, `.private`, model weights, databases, or generated indexes entering
  the image build context;
- the process running as root or writing into the application directory;
- Linux capabilities or privilege escalation remaining enabled;
- a deployed image loading an index other than the release-bound run/hash;
- a crash after the index pointer changes but before the release pointer
  changes;
- a failed candidate remaining active after readiness failure;
- probes being redirected to a remote URL;
- an operator mistaking liveness for readiness.

Out of scope:

- compromise of the Docker daemon or Linux root account;
- network isolation against arbitrary malicious application code;
- registry signing and remote attestation;
- multi-host scheduling, rolling updates, and automatic failover;
- real IdP integration and secret-manager integration.

## 4. Frozen Invariants

1. A release image is accepted only as `name@sha256:<64 lowercase hex>`.
2. A release is append-only and binds the exact Git commit, runtime contract
   hash, index run ID, and index manifest SHA-256.
3. A normal activation must extend the current release linearly.
4. A rollback target is the current release's recorded predecessor.
5. Release and index pointer updates are journaled. A remaining
   `pending.json` blocks normal operations until explicit recovery.
6. Readiness fails if `DEPLOYMENT_EXPECTED_INDEX_*` does not match the loaded
   index.
7. Every production model call validates the endpoint as an exact local HTTP
   origin.
8. The runtime uses UID/GID 10001, a read-only root filesystem, dropped
   capabilities, `no-new-privileges`, resource bounds, and separate
   data/identity mounts.
9. `/health/live` proves only that the process responds. Promotion requires
   `/health/ready` and the expected index run ID.
10. Kubernetes, service mesh, vector service, and durable telemetry remain
    deferred until a measured single-host limitation appears.

## 5. Release State Machine

```text
register append-only release
        |
        v
validate image/git/runtime/index binding
        |
        v
write pending transaction
        |
        v
atomically activate index pointer
        |
        v
atomically activate deployment pointer
        |
        v
delete pending transaction
```

If the process stops between the two pointer writes, verification fails closed.
The operator chooses one explicit recovery:

- `restore_previous`: restore the pre-transaction index and release pointers;
- `complete_target`: revalidate and finish the target pointer update.

## 6. Acceptance Gates

Local deterministic gates:

- model endpoint validation and canonicalization;
- release append-only and chain enforcement;
- release/index binding verification;
- injected mid-activation failure and both recovery strategies;
- rollback of release and index together;
- probe loopback restriction;
- image/Compose/.dockerignore contract checks;
- deterministic smoke fixtures and SPDX SBOM schema.

Linux CI gates:

- build the pinned test and runtime image targets;
- run compile, pip, frozen evaluation, corpus quality, full pytest, and public
  audit inside the test image;
- start the runtime as UID 10001 with a read-only root;
- pass liveness and readiness against a private synthetic index/identity setup;
- prove the code directory is not writable;
- activate an intentionally incompatible index and prove readiness fails;
- execute rollback, restart, and prove the previous index is ready again;
- upload a Python-package SPDX 2.3 SBOM.

## 7. Evidence Semantics

Local tests prove Python behavior and checked-in deployment contracts. They do
not prove that the Dockerfile builds. Docker is not installed on the Windows
development host.

Only a successful GitHub `linux-container-contract` job on the exact commit can
establish the image build and runtime drill. Even that remains a synthetic
single-host CI exercise, not production deployment evidence.

## 8. Primary References

- [Docker host networking](https://docs.docker.com/engine/network/drivers/host/)
- [Docker Compose service controls](https://docs.docker.com/reference/compose-file/services/)
- [Docker build context and `.dockerignore`](https://docs.docker.com/build/concepts/context/)
- [Pinned Python 3.11 Linux/amd64 image manifest](https://hub.docker.com/layers/library/python/3.11-slim-bookworm/images/sha256-28255a3ace7eb4c48bc1b57b90af29e1bc82b4fd6c60614a8e3dce61b87ff941)
