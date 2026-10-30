"""Conversation projection; the existing runtime executes all turns."""
from fastapi import APIRouter
from pydantic import BaseModel,Field,ConfigDict


class CreateConversation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(default='新会话',max_length=200)
    kb_id:str|None=None


class ConversationMessage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    message_id:str=Field(min_length=1,max_length=100)
    text:str=Field(min_length=1,max_length=2000)


def conversation_router(workspace,service_call):
    router=APIRouter(prefix='/api/conversations')

    @router.get('')
    def conversations():return workspace.conversations.list()

    @router.post('')
    def create(payload:CreateConversation):
        if payload.kb_id:workspace.library.require(payload.kb_id)
        return workspace.conversations.create(payload.kb_id,payload.title)

    @router.get('/{cid}')
    def get(cid:str):return service_call(lambda:workspace.conversations.get(cid))

    @router.post('/{cid}/turns',status_code=202)
    async def turn(cid:str,payload:ConversationMessage):
        workspace.conversations.get(cid)
        return service_call(lambda:workspace.runs.start('conversation',{'conversation_id':cid,**payload.model_dump()}))

    @router.post('/{cid}/tasks/{task_id}')
    def bind(cid:str,task_id:str):return service_call(lambda:workspace.conversations.bind(task_id,cid))

    return router
