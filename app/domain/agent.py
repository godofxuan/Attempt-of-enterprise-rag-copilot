from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.queries import FindRequest, OpenRequest, SearchRequest


AnswerMode = Literal[
    "answered",
    "partial",
    "not_found",
    "permission",
    "unsafe",
    "system",
    "budget",
    "security_filtered",
]
AgentStopReason = Literal[
    "completed",
    "partial_evidence",
    "no_match",
    "not_found",
    "permission",
    "unsafe",
    "system",
    "system_error",
    "budget",
    "budget_exhausted",
    "evidence_filtered",
]
AgentToolName = Literal["search", "find", "open", "answer", "refuse", "stop"]
ToolErrorCode = Literal[
    "invalid_args",
    "not_found",
    "permission",
    "timeout",
    "budget",
    "system",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentBudget(StrictModel):
    max_search_calls: int = Field(default=3, ge=1, le=10)
    max_find_calls: int = Field(default=2, ge=1, le=10)
    max_open_calls: int = Field(default=4, ge=1, le=20)
    max_steps: int = Field(default=12, ge=1, le=50)
    max_context_chars: int = Field(default=12_000, ge=100, le=100_000)
    deadline_ms: int = Field(default=15_000, ge=100, le=300_000)


class BudgetState(StrictModel):
    budget: AgentBudget = Field(default_factory=AgentBudget)
    search_calls: int = Field(default=0, ge=0)
    find_calls: int = Field(default=0, ge=0)
    open_calls: int = Field(default=0, ge=0)
    steps: int = Field(default=0, ge=0)
    context_chars: int = Field(default=0, ge=0)
    deadline_at_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_limits(self) -> BudgetState:
        checks = (
            ("search", self.search_calls, self.budget.max_search_calls),
            ("find", self.find_calls, self.budget.max_find_calls),
            ("open", self.open_calls, self.budget.max_open_calls),
            ("steps", self.steps, self.budget.max_steps),
            ("context", self.context_chars, self.budget.max_context_chars),
        )
        for label, used, limit in checks:
            if used > limit:
                raise ValueError(f"{label} budget exceeded: {used} > {limit}")
        return self


class ToolError(StrictModel):
    code: ToolErrorCode
    retryable: bool
    safe_message: str = Field(min_length=1, max_length=500)


class AgentAction(StrictModel):
    sequence: int = Field(ge=1)
    tool: AgentToolName
    purpose: str = Field(min_length=1, max_length=500)
    aspect: str | None = Field(default=None, max_length=500)
    search_request: SearchRequest | None = None
    find_request: FindRequest | None = None
    open_request: OpenRequest | None = None

    @model_validator(mode="after")
    def validate_request_matches_tool(self) -> AgentAction:
        requests = {
            "search": self.search_request,
            "find": self.find_request,
            "open": self.open_request,
        }
        present = [name for name, request in requests.items() if request is not None]
        if self.tool in requests:
            if requests[self.tool] is None:
                raise ValueError(f"{self.tool}_request is required for {self.tool} action")
            if present != [self.tool]:
                raise ValueError("action request must match its tool")
        elif present:
            raise ValueError("terminal action cannot carry tool requests")
        return self


__all__ = [
    "AgentAction",
    "AgentBudget",
    "AgentStopReason",
    "AgentToolName",
    "AnswerMode",
    "BudgetState",
    "ToolError",
    "ToolErrorCode",
]
