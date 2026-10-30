"""Conversation projection; the existing runtime executes all turns."""
from fastapi import APIRouter
from pydantic import BaseModel,Field,ConfigDict
from app.domain.evidence import AnswerResponse
from app.api.product_routes import PublishedAnswerView, ProposalView, ReceiptView


class CreateConversation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(default='新会话',max_length=200)
    kb_id:str|None=None


class ConversationMessage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    message_id:str=Field(min_length=1,max_length=100)
    text:str=Field(min_length=1,max_length=2000)
    detailed:bool=False


class ConversationSummary(BaseModel):
    id: str
    title: str | None = None
    kb_id: str | None = None
    task_id: str | None = None
    updated_at: str | None = None


class TurnPayload(BaseModel):
    model_config = ConfigDict(extra='allow')
    knowledge: PublishedAnswerView | None = None
    result: AnswerResponse | None = None
    id: str | None = None
    preview: ProposalView | None = None
    receipt: ReceiptView | None = None
    task_id: str | None = None
    facts: dict | None = None


class TurnView(BaseModel):
    id: str
    role: str
    kind: str
    text: str
    status: str
    payload: TurnPayload | None = None
    run_id: str | None = None


class ConversationView(ConversationSummary):
    active_task_id: str | None = None
    task_history: list[str]
    turns: list[TurnView]


def conversation_router(workspace,service_call):
    router=APIRouter(prefix='/api/conversations')

    @router.get('', response_model=list[ConversationSummary])
    def conversations():return workspace.conversations.list()

    @router.post('')
    def create(payload:CreateConversation):
        if payload.kb_id:workspace.library.require(payload.kb_id)
        return workspace.conversations.create(payload.kb_id,payload.title)

    @router.get('/{cid}', response_model=ConversationView)
    def get(cid:str):return service_call(lambda:workspace.conversations.get(cid))

    @router.post('/{cid}/turns',status_code=202)
    async def turn(cid:str,payload:ConversationMessage):
        workspace.conversations.get(cid)
        return service_call(lambda:workspace.runs.start('conversation',{'conversation_id':cid,**payload.model_dump()}))

    @router.post('/{cid}/tasks/{task_id}')
    def bind(cid:str,task_id:str):return service_call(lambda:workspace.conversations.bind(task_id,cid))

    return router
