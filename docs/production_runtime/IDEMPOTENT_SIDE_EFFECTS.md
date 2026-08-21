# Idempotent Side Effects

## Supported effect

Only `create_access_request_draft` is implemented. Its output is always:

- status `DRAFT`;
- `acl_changed = false`;
- hashed tenant, requester, session, and resource identifiers;
- a deterministic draft ID.

There is no code path to grant a group, update a document ACL, or activate the
request.

## Idempotency key

```text
SHA-256(canonical JSON(
  tenant_id + user_id + run_id + tool_name + normalized_arguments_sha256
))
```

The SQLite transaction writes `side_effect_commands` and
`access_request_drafts` together. A retry first reads the committed command and
returns its stored typed result. Therefore the tested draft effect does not
duplicate across repeated resume or restart.

## Failure boundaries

- Before commit: transaction rolls back; retry creates one draft.
- After commit but before response: retry sees the committed command and returns
  the same draft.
- Concurrent/process-wide distributed execution: not established. SQLite
  `BEGIN IMMEDIATE` serializes writers on one shared database file, but this is
  not a distributed idempotency service.
- External email, ticketing, IAM, and message delivery are not implemented. They
  would require destination-supported idempotency or a real outbox dispatcher.
