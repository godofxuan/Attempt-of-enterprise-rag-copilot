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

The durable workflow SQLite transaction writes `side_effect_commands`,
`access_request_drafts`, one `durable_completion_outbox` envelope, and the
terminal `durable_approvals` result together. A retry reads the terminal result
and returns the same typed draft. The standalone `SQLiteSideEffectStore` API is
retained, but the durable workflow uses the caller-owned transaction helper.

## Failure boundaries

- Before commit: transaction rolls back; retry creates one draft.
- After commit but before response: retry sees the committed command and returns
  the same draft.
- Concurrent callers on one shared SQLite database are serialized with
  `BEGIN IMMEDIATE`, then fenced by owner token and version. This is not a
  distributed idempotency service or multi-host HA design.
- Completion trajectory is outside the workflow transaction. It is delivered
  from an immutable outbox with stable event idempotency keys.
- External email, ticketing, IAM, and message delivery are not implemented. They
  would require destination-supported idempotency or a real outbox dispatcher.
