# R2-S9 Minimal Linux Deployment Runbook

This runbook targets one Linux x86-64 host with Docker Engine, Docker Compose
v2, and the required local models already served on
`http://127.0.0.1:11434`.

## 1. Build and Test

```bash
docker build --target test -t enterprise-rag-test:"$(git rev-parse HEAD)" .
docker run --rm enterprise-rag-test:"$(git rev-parse HEAD)" \
  python -m pytest -q
docker build --target runtime \
  -t registry.example/enterprise-rag:"$(git rev-parse HEAD)" .
docker push registry.example/enterprise-rag:"$(git rev-parse HEAD)"
```

Resolve the registry manifest digest after push. Registration rejects a tag
without `@sha256:<digest>`.

## 2. Prepare Host State

```bash
sudo install -d -o 10001 -g 10001 /srv/enterprise-rag/data
sudo install -d -o 10001 -g 10001 /srv/enterprise-rag/identity
```

Populate `/srv/enterprise-rag/data/indexes_v2` with a validated versioned index
and active pointer. Generate the local identity source into the identity
directory:

```bash
python -m scripts.manage_demo_identity \
  --directory /srv/enterprise-rag/identity init
```

Do not commit or copy that directory into the image.

## 3. Register and Activate a Release

```bash
python -m scripts.manage_deployment register \
  --release-id release-20260727-01 \
  --image-reference registry.example/enterprise-rag@sha256:<manifest-digest> \
  --index-run-id <validated-index-run-id> \
  --source-commit "$(git rev-parse HEAD)"

python -m scripts.manage_deployment activate \
  --release-id release-20260727-01

python -m scripts.manage_deployment render-env \
  --output .private/deployment/active.env
```

For the next release, add `--previous-release-id release-20260727-01`.

Copy `deploy/runtime.env.example` to an ignored operator environment file and
set the two absolute host paths. It contains no release identity; that comes
from the generated `active.env`.

## 4. Start and Promote

```bash
docker compose \
  --env-file .private/deployment/runtime.env \
  --env-file .private/deployment/active.env \
  -f deploy/compose.yaml up -d --wait

python -m scripts.probe_deployment \
  --expected-index-run-id <validated-index-run-id>
```

`docker compose --wait` uses liveness. The second command is the promotion gate
because it requires full readiness and the expected active index.

## 5. Roll Back

If the candidate fails readiness:

```bash
python -m scripts.manage_deployment rollback
python -m scripts.manage_deployment render-env \
  --output .private/deployment/active.env --force

docker compose \
  --env-file .private/deployment/runtime.env \
  --env-file .private/deployment/active.env \
  -f deploy/compose.yaml up -d --wait

python -m scripts.probe_deployment \
  --expected-index-run-id <previous-index-run-id>
```

The rollback changes both deployment and index pointers before the service is
restarted. Readiness verifies that the restarted service loaded the restored
index.

## 6. Recover an Interrupted Pointer Transaction

Normal commands fail with `deployment transaction recovery is required` when
`pending.json` exists.

Restore the state from before the interrupted operation:

```bash
python -m scripts.manage_deployment recover \
  --strategy restore_previous
```

Or finish the already-validated target:

```bash
python -m scripts.manage_deployment recover \
  --strategy complete_target
```

After either action, run `verify`, render the environment again, restart the
container, and rerun the readiness probe.

## 7. Inspect

```bash
python -m scripts.manage_deployment verify
docker compose -f deploy/compose.yaml ps
docker inspect enterprise-rag-api-1 --format '{{.Config.User}}'
```

Expected runtime user: `10001:10001`.

The GitHub `linux-container-contract` job publishes
`enterprise-rag-python-runtime-sbom`. It is an SPDX 2.3 inventory of installed
Python distributions. It is not a complete OS vulnerability attestation.
