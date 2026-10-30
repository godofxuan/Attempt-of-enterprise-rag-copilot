from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_endpoint: str | None = None
    chat_model: str | None = Field(default=None, min_length=1, max_length=200)
    embedding_model: str | None = Field(default=None, min_length=1, max_length=200)
    request_timeout_seconds: float | None = Field(default=None, ge=1, le=300)


class CreateKnowledgeBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class AskKnowledge(BaseModel):
    kb_id: str
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    detailed: bool = False


class CreateTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: dict
    kb_id: str | None = None
    answer_id: str | None = None
    use_original_parameters: bool = False
    conversation_id: str | None = None


class UpdateFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: dict
    expected_facts_revision: int = Field(ge=1)


class SubmitTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    content_digest: str
    accepted: bool = Field(strict=True)
    expected_facts_revision: int = Field(ge=1)


class TaskMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    message_id: str = Field(min_length=1, max_length=100)
    expected_facts_revision: int = Field(ge=1)
    detailed: bool = False


class SelectAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    expected_facts_revision: int = Field(ge=1)
    date_shift_days: int = Field(default=0, ge=0, le=7, strict=True)


class ResolveUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_ceiling: Literal["READ_ONLY", "PREVIEW_ONLY", "SUBMIT_AFTER_CONFIRMATION"]
    expected_facts_revision: int = Field(ge=1)
    reviewed: bool = Field(strict=True)


class DeskAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["loan", "repair"]
    ticket_id: str
    action: str
    expected_version: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=1000)
    loan_end: date | None = None


class DeskCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    content_digest: str
    accepted: bool = Field(strict=True)


class AddDirectory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_id: str
    path: str = Field(min_length=1, max_length=1000)


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=250)
    active: bool | None = None
    source_type: (
        Literal["policy", "wiki", "email", "ticket", "meeting", "table", "filing"] | None
    ) = None
    effective_from: date | None = None
    service_tags: list[Literal["loan", "repair"]] | None = None


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_kind: Literal["answer", "task"]
    target_id: str
    category: Literal["parse", "retrieval", "generation", "business", "ux", "other"]
    message: str = Field(min_length=1, max_length=2000)
