"""Typed product read models; OpenAPI is their frontend schema source."""

from typing import Any
from pydantic import BaseModel, ConfigDict, field_serializer
from app.domain.evidence import AnswerResponse


class PublishedAnswerView(BaseModel):
    id: str
    question: str = ""
    kb_id: str = ""
    conversation_id: str = ""
    result: AnswerResponse
    source_notices: list[str] = []

    @field_serializer("result")
    def public_answer(self, value):
        return value.model_dump(exclude={"trace"})


class RunView(BaseModel):
    id: str
    kind: str
    target: str | None = None
    status: str
    conversation_id: str | None = None
    turn_id: str | None = None
    input_json: str = "{}"
    result_json: str | None = None
    result: Any = None
    error: str | None = None
    created_at: str | None = None


class FieldView(BaseModel):
    name: str
    label: str
    type: str = "text"
    required: bool = False
    value: Any = None


class TicketView(BaseModel):
    model_config = ConfigDict(extra="allow")
    ticket_id: str
    asset_id: str
    status: str
    version: int
    parameters: dict[str, Any]
    next_step: str


class ProposalContent(BaseModel):
    model_config = ConfigDict(extra="allow")
    target: str
    parameters: dict[str, Any]
    rule_version: str
    effect_notice: str | None = None
    notice: str | None = None
    next_step: str | None = None


class ProposalView(BaseModel):
    proposal_id: str
    content_digest: str
    content: ProposalContent
    expires_at: float


class ReceiptView(BaseModel):
    model_config = ConfigDict(extra="allow")
    ticket_id: str
    command_id: str
    ticket: TicketView


class OutcomeView(BaseModel):
    model_config = ConfigDict(extra="allow")
    answer: str = ""
    next_step: str = ""


class TurnDeliveryView(BaseModel):
    turn_id: str
    status: str
    pending: list[str]
    items: dict[str, Any]
    retryable: bool
    next_action: str | None = None
    action_kind: str | None = None


class NextActionView(BaseModel):
    kind: str
    label: str
    detail: str
    fields: list[str] = []


class TaskView(BaseModel):
    id: str
    conversation_id: str | None = None
    kind: str
    title: str
    status: str
    status_label: str
    closed: bool = False
    next_step: str
    ceiling: str
    revision: int
    fields: list[FieldView]
    preview: ProposalView | None = None
    receipt: ReceiptView | None = None
    current_ticket: TicketView | None = None
    knowledge: PublishedAnswerView | None = None
    outcome: OutcomeView | None = None
    pending_update: dict[str, str] | None = None
    last_error: str | None = None
    can_edit: bool
    can_run: bool
    can_cancel: bool
    can_submit: bool
    turn_delivery: TurnDeliveryView | None = None
    next_action: NextActionView | None = None
