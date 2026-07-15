from typing import Any, Literal

from pydantic import BaseModel, Field


RouteName = Literal[
    "policy_qa",
    "comparison",
    "process",
    "no_answer_check",
    "unsafe_request",
]


class RouteDecision(BaseModel):
    route: RouteName
    reason: str


class PlanStep(BaseModel):
    tool: str
    reason: str


class ToolTraceStep(BaseModel):
    tool: str
    status: Literal["ok", "error"]
    latency_ms: float
    output_summary: str


class EvidenceTraceRecord(BaseModel):
    attempt: int = Field(ge=1)
    search_query: str
    verdict: Literal["sufficient", "insufficient", "error"]
    reason: str
    rewritten_query: str | None = None
    rewrite_source: Literal["model", "fallback"] | None = None


class AgentTrace(BaseModel):
    route: RouteName
    route_reason: str
    plan: list[PlanStep] = Field(default_factory=list)
    steps: list[ToolTraceStep] = Field(default_factory=list)
    retrieval_attempts: int = 0
    evidence_history: list[EvidenceTraceRecord] = Field(default_factory=list)
    final_outcome: Literal[
        "answered",
        "grounded_no_answer",
        "refused",
        "error",
    ] | None = None


class AgentChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    trace: AgentTrace
