from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.agent import AgentBudget, BudgetState
from app.domain.queries import FindRequest, OpenRequest, SearchRequest, UserContext
from app.domain.retrieved_security import GuardedToolPayload, SecurityCounters


ToolName = Literal["search", "find", "open"]
ToolContractErrorCode = Literal[
    "invalid_args",
    "unauthorized",
    "identity_mismatch",
    "stale_context",
    "not_found",
    "permission",
    "timeout",
    "budget",
    "system",
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ToolDefinition(_StrictFrozenModel):
    name: ToolName
    description: str = Field(min_length=1, max_length=500)
    request_schema: Literal["SearchRequest", "FindRequest", "OpenRequest"]
    read_only: Literal[True] = True


class ToolContext(_StrictFrozenModel):
    session_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=200)
    identity: UserContext
    acl_scope: tuple[str, ...] = Field(min_length=1, max_length=50)
    allowed_tools: tuple[ToolName, ...] = ("search", "find", "open")
    budget: AgentBudget = Field(default_factory=AgentBudget)
    issued_at_ms: float = Field(ge=0)
    expires_at_ms: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_context(self) -> ToolContext:
        if self.expires_at_ms <= self.issued_at_ms:
            raise ValueError("tool context expiry must follow issue time")
        if len(self.acl_scope) != len(set(self.acl_scope)):
            raise ValueError("ACL scope must be unique")
        if not set(self.identity.groups).issubset(self.acl_scope):
            raise ValueError("ACL scope cannot omit authenticated identity groups")
        if len(self.allowed_tools) != len(set(self.allowed_tools)):
            raise ValueError("allowed tools must be unique")
        return self

    def identity_fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "user_id": self.identity.user_id,
                "tenant_id": self.identity.tenant_id,
                "region": self.identity.region,
                "groups": sorted(self.identity.groups),
                "roles": sorted(self.identity.roles),
                "acl_scope": sorted(self.acl_scope),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


ToolArguments = SearchRequest | FindRequest | OpenRequest


class ToolRequest(_StrictFrozenModel):
    tool: ToolName
    sequence: int = Field(ge=1)
    purpose: str = Field(min_length=1, max_length=500)
    aspect: str | None = Field(default=None, max_length=500)
    arguments: ToolArguments

    @model_validator(mode="after")
    def validate_arguments(self) -> ToolRequest:
        expected = {
            "search": SearchRequest,
            "find": FindRequest,
            "open": OpenRequest,
        }[self.tool]
        if not isinstance(self.arguments, expected):
            raise ValueError("tool arguments do not match the selected tool")
        return self


class ToolError(_StrictFrozenModel):
    code: ToolContractErrorCode
    retryable: bool = False
    safe_message: str = Field(min_length=1, max_length=500)


class ToolResult(_StrictFrozenModel):
    session_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=200)
    tool: ToolName
    sequence: int = Field(ge=1)
    status: Literal["ok", "error"]
    payload: GuardedToolPayload | None = None
    error: ToolError | None = None
    budget_state: BudgetState
    security_counters: SecurityCounters | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> ToolResult:
        if self.status == "ok" and (self.payload is None or self.error is not None):
            raise ValueError("successful tool result requires payload only")
        if self.status == "error" and (self.error is None or self.payload is not None):
            raise ValueError("failed tool result requires error only")
        return self


TOOL_DEFINITIONS = (
    ToolDefinition(
        name="search",
        description="Search visible, versioned enterprise evidence.",
        request_schema="SearchRequest",
    ),
    ToolDefinition(
        name="find",
        description="Find a pattern inside one visible document.",
        request_schema="FindRequest",
    ),
    ToolDefinition(
        name="open",
        description="Open a visible chunk, parent chunk, or document.",
        request_schema="OpenRequest",
    ),
)


__all__ = [
    "TOOL_DEFINITIONS",
    "ToolArguments",
    "ToolContext",
    "ToolContractErrorCode",
    "ToolDefinition",
    "ToolError",
    "ToolName",
    "ToolRequest",
    "ToolResult",
]

