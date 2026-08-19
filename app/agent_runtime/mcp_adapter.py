from __future__ import annotations

import hashlib
import secrets
from threading import RLock
from typing import Any

from mcp.server import MCPServer

from app.agent_runtime.tool_contract import ToolContext, ToolRequest
from app.agent_runtime.tool_gateway import ToolGateway
from app.domain.queries import FindRequest, OpenRequest, SearchRequest


class MCPContextBroker:
    """Maps opaque capabilities to server-owned tool contexts."""

    def __init__(self, gateway: ToolGateway) -> None:
        self._gateway = gateway
        self._contexts: dict[str, ToolContext] = {}
        self._sequences: dict[str, int] = {}
        self._lock = RLock()

    def issue(self, context: ToolContext) -> str:
        handle = secrets.token_urlsafe(32)
        digest = _handle_digest(handle)
        self._gateway.start_session(context)
        with self._lock:
            self._contexts[digest] = context
            self._sequences[digest] = 0
        return handle

    def resolve_call(self, handle: str) -> tuple[ToolContext, int] | None:
        if not isinstance(handle, str) or len(handle) < 32 or len(handle) > 256:
            return None
        digest = _handle_digest(handle)
        with self._lock:
            context = self._contexts.get(digest)
            if context is None:
                return None
            sequence = self._sequences[digest] + 1
            self._sequences[digest] = sequence
            return context, sequence

    def revoke(self, handle: str) -> None:
        digest = _handle_digest(handle)
        with self._lock:
            context = self._contexts.pop(digest, None)
            self._sequences.pop(digest, None)
        if context is not None:
            self._gateway.close_session(context.session_id)


class EnterpriseKnowledgeMCP:
    """Official MCP transport adapter backed only by ToolGateway."""

    def __init__(self, gateway: ToolGateway, broker: MCPContextBroker) -> None:
        self._gateway = gateway
        self._broker = broker
        self.server = MCPServer(
            "enterprise-knowledge",
            description=(
                "Read-only enterprise knowledge tools. Identity and ACL are "
                "resolved by the host, not accepted as tool arguments."
            ),
            version="1.0.0",
        )
        self._register_tools()

    def _register_tools(self) -> None:
        @self.server.tool(
            name="search",
            description="Search visible versioned enterprise evidence.",
            structured_output=True,
        )
        def search(
            session_handle: str,
            query: str,
            purpose: str,
            top_k: int = 5,
            candidate_k: int = 20,
            mode: str = "hybrid",
            include_parent: bool = True,
        ) -> dict[str, Any]:
            resolved = self._broker.resolve_call(session_handle)
            if resolved is None:
                return _mcp_session_error("The MCP session is invalid or revoked.")
            context, sequence = resolved
            try:
                arguments = SearchRequest(
                    request_id=context.request_id,
                    user=context.identity,
                    query=query,
                    purpose=purpose,
                    top_k=top_k,
                    candidate_k=candidate_k,
                    mode=mode,
                    include_parent=include_parent,
                )
                request = ToolRequest(
                    tool="search",
                    sequence=sequence,
                    purpose=purpose,
                    aspect=purpose,
                    arguments=arguments,
                )
            except Exception:
                return _mcp_arguments_error()
            return self._execute(request, context)

        @self.server.tool(
            name="find",
            description="Find a pattern inside one visible document.",
            structured_output=True,
        )
        def find(
            session_handle: str,
            doc_id: str,
            pattern: str,
            max_results: int = 5,
        ) -> dict[str, Any]:
            resolved = self._broker.resolve_call(session_handle)
            if resolved is None:
                return _mcp_session_error("The MCP session is invalid or revoked.")
            context, sequence = resolved
            try:
                arguments = FindRequest(
                    request_id=context.request_id,
                    user=context.identity,
                    doc_id=doc_id,
                    pattern=pattern,
                    max_results=max_results,
                )
                request = ToolRequest(
                    tool="find",
                    sequence=sequence,
                    purpose="find evidence inside a visible document",
                    arguments=arguments,
                )
            except Exception:
                return _mcp_arguments_error()
            return self._execute(request, context)

        @self.server.tool(
            name="open",
            description="Open a visible chunk, parent chunk, or document.",
            structured_output=True,
        )
        def open_evidence(
            session_handle: str,
            target_type: str,
            target_id: str,
            max_chars: int = 4000,
        ) -> dict[str, Any]:
            resolved = self._broker.resolve_call(session_handle)
            if resolved is None:
                return _mcp_session_error("The MCP session is invalid or revoked.")
            context, sequence = resolved
            try:
                arguments = OpenRequest(
                    request_id=context.request_id,
                    user=context.identity,
                    target_type=target_type,
                    target_id=target_id,
                    max_chars=max_chars,
                )
                request = ToolRequest(
                    tool="open",
                    sequence=sequence,
                    purpose="open visible enterprise evidence",
                    arguments=arguments,
                )
            except Exception:
                return _mcp_arguments_error()
            return self._execute(request, context)

    def _execute(self, request: ToolRequest, context: ToolContext) -> dict[str, Any]:
        result = self._gateway.execute(request, context)
        return result.model_dump(mode="json", exclude_none=True)


def _handle_digest(handle: str) -> str:
    return hashlib.sha256(handle.encode("utf-8")).hexdigest()


def _mcp_session_error(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {
            "code": "stale_context",
            "retryable": False,
            "safe_message": message,
        },
    }


def _mcp_arguments_error() -> dict[str, Any]:
    return {
        "status": "error",
        "error": {
            "code": "invalid_args",
            "retryable": False,
            "safe_message": "The MCP tool arguments are invalid.",
        },
    }


__all__ = ["EnterpriseKnowledgeMCP", "MCPContextBroker"]
