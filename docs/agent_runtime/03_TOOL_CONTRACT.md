# Tool Contract

## Why this boundary exists

The original `V2ToolRegistry` already enforced typed actions, budgets,
deadlines, retrieved-content admission, and structured errors. It was designed
for the in-process bounded controller, however, so an external protocol adapter
needed a stable session and identity boundary before calling it.

The vNext contract adds five explicit objects:

- `ToolDefinition`: allowlisted metadata for `search`, `find`, and `open`.
- `ToolContext`: server-issued identity, ACL scope, correlation IDs, allowlist,
  budget, and validity interval.
- `ToolRequest`: one typed operation and its existing request schema.
- `ToolResult`: guarded payload or a structured safe error plus budget state.
- `ToolError`: stable error codes without backend exception or secret leakage.

## Execution path

```text
protocol/orchestrator request
  -> ToolGateway active-session lookup
  -> exact server-context and identity fingerprint comparison
  -> expiry, request correlation, and tool allowlist checks
  -> existing AgentAction schema
  -> existing V2ToolRegistry
  -> existing navigator / ACL / admission / Guard
  -> ToolResult
```

`ToolGateway` keeps mutable budget state on the server. Callers cannot reset a
budget by sending a new counter. The request's embedded `UserContext` must equal
the identity in the active server context, and request/session correlation must
match exactly.

`acl_scope` is a server-selected narrowing of the authenticated identity's
groups: `acl_scope ⊆ identity.groups`. Equal scope and narrower scope are valid;
an expanded or unrelated group fails contract validation before any backend
call. The scope is not a place for a caller to add entitlements.

## Failure behavior

Malformed input fails Pydantic validation. Unauthorized tools, forged identity,
cross-tenant arguments, stale sessions, exhausted budgets, timeout, and backend
permission denial all fail closed. Pre-execution failures do not call the
navigator. Backend errors are converted to safe structured errors.

Timeout remains cooperative because the existing Python call cannot forcibly
stop arbitrary synchronous backend code. A result completed after the deadline
is discarded. This is an explicit limitation, not a hard execution sandbox.

## Tests

`tests/agent_runtime/test_tool_contract.py` covers authorized execution,
allowlist denial, malformed requests, forged and cross-tenant identity, context
replacement, stale/closed sessions, stateful budget exhaustion, backend access
denial, timeout, equal/narrow ACL scopes, and rejected expanded/unrelated
scopes. Existing guarded-tool tests continue to own admission and
oversized-result behavior.
