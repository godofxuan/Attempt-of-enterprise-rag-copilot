# Tool Policy and Lifecycle Hooks

Normative implementation: `app/agent_runtime/tool_policy.py` and
`app/agent_runtime/tool_gateway.py`.

## Decision model

Precedence is fixed: `DENY > ASK > ALLOW`.

| Risk | Tools | Decision |
|---|---|---|
| `READ_ONLY` | `search`, `find` | `ALLOW` after context checks |
| `SENSITIVE_READ` | ACL-scoped `open` | `ALLOW` after context and ACL checks |
| `SIDE_EFFECT` | `export_evidence_bundle`, `create_access_request_draft` | `ASK` |
| `ADMIN_FORBIDDEN` | ACL mutation, unrestricted fetch, raw SQL, unknown tools | `DENY` |

ACL denial, identity override, expired authentication, expired deadline, or an
exhausted budget always denies even if the tool normally maps to `ASK` or
`ALLOW`. A model cannot submit a policy decision; it can only propose a tool
call that the gateway evaluates.

## Policy input

`ToolPolicyInput` binds tenant, user, sorted roles, session, run, tool, canonical
argument SHA-256, current ACL decision, budget state, deadline, authentication
expiry, risk, evaluation time, and `tool-policy.v1`. Raw arguments are not stored
in policy audit rows.

## Hooks

- `pre_tool_use`: receives the authoritative policy result and can only fail the
  call more closed. An exception becomes `DENY/pre_hook_failed`.
- `post_tool_use`: validates `ToolResult`, relies on the existing retrieved-content
  Guarded payload contract, emits only outcome type/status/hash metadata, and
  fails closed on an exception.
- `tool_error`: records a limited error code, never stack content or credentials.
- `run_stop`: observes trusted session closure.

Hooks are trusted in-process objects. There is no command string, shell, HTTP,
prompt, dynamic import, or model hook surface.

## Audit privacy

Tenant, user, session, and run are SHA-256 pseudonyms. Argument and output bodies
are represented by hashes. Keys containing authorization, token, cookie,
password, secret, or API-key semantics are redacted. This is pseudonymization,
not anonymity, and retention/access control are still deployment obligations.
