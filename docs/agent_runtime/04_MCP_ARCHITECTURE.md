# MCP Architecture

## Decision

The project uses the official Python MCP SDK `2.0.0`. MCP is an interoperability
transport, not a security boundary and not a retrieval implementation.

```text
MCP client
  -> official MCPServer search/find/open schema
  -> opaque server-issued session handle
  -> MCPContextBroker
  -> ToolGateway
  -> existing V2ToolRegistry
  -> navigator -> ACL -> retrieval -> admission/Guard
```

The adapter has no navigator, SQL, FAISS, SQLite, index, or filesystem handle.
Its only executable dependency is `ToolGateway`.

## Identity model

MCP tool arguments deliberately exclude tenant, user, groups, roles, and ACL
scope. Before a client can call a tool, the trusted host creates `ToolContext`
from authenticated server state and asks `MCPContextBroker` for a random opaque
handle. The broker stores only a SHA-256 digest of the handle and maps it to the
server-owned context.

Possession of the handle selects an existing context; it cannot alter that
context. Revocation removes the mapping and closes the gateway session. A real
network deployment must deliver the handle only after its existing OAuth/JWT
boundary authenticates the caller. The repository does not claim that stdio
transport alone establishes enterprise identity.

## Protocol behavior

The official server publishes exactly three read-only tools: `search`, `find`,
and `open`. SDK validation handles the outer MCP schema. The adapter builds the
existing strict request models using the resolved identity. Domain validation
failures become a fixed safe `invalid_args` result; raw arguments and exceptions
are not reflected.

Successful and failed calls serialize the same `ToolResult` used by non-MCP
orchestrators. Stateful budget, expiry, authorization, ACL, timeout, admission,
and content limits therefore remain below the protocol.

## Limits

- Session bootstrap is an application-host responsibility; the MCP client
  cannot self-assert identity.
- Timeouts are cooperative, as documented in the Tool Contract.
- This stage verifies in-process official MCP dispatch. A production network
  transport, TLS termination, OAuth resource metadata, and deployment SLO are
  not claimed.
- MCP does not improve retrieval or answer quality by itself.

## Tests

`tests/agent_runtime/test_mcp_adapter.py` dispatches through the official server
and verifies tool discovery, authorized search/open, invalid and revoked
sessions, malformed arguments, budget exhaustion, backend permission denial,
and stale sessions. ToolGateway tests separately cover forged identity,
cross-tenant arguments, timeout, and exact server-context matching.

