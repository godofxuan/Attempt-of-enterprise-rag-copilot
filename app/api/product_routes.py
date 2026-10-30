"""Small typed views for the product; domain operations retain their existing APIs."""
import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.service_desk.catalog import SERVICES
from app.service_desk.lifecycle import NOTICES
from app.service_desk.store import ServiceError
from app.domain.evidence import AnswerResponse


class PublishedAnswerView(BaseModel):
    id: str
    question: str = ''
    kb_id: str = ''
    conversation_id: str = ''
    result: AnswerResponse
    source_notices: list[str] = []


class FieldView(BaseModel):
    name: str
    label: str
    type: str = 'text'
    required: bool = False
    value: Any = None


class TicketView(BaseModel):
    model_config = ConfigDict(extra='allow')
    ticket_id: str
    asset_id: str
    status: str
    version: int
    parameters: dict[str, Any]
    next_step: str


class ProposalContent(BaseModel):
    model_config = ConfigDict(extra='allow')
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
    model_config = ConfigDict(extra='allow')
    ticket_id: str
    command_id: str
    ticket: TicketView


class OutcomeView(BaseModel):
    model_config = ConfigDict(extra='allow')
    answer: str = ''
    next_step: str = ''


class TaskView(BaseModel):
    id: str
    conversation_id: str | None = None
    kind: str
    title: str
    status: str
    status_label: str
    next_step: str
    ceiling: str
    revision: int
    fields: list[FieldView]
    preview: ProposalView | None = None
    receipt: ReceiptView | None = None
    current_ticket: TicketView | None = None
    knowledge: PublishedAnswerView | None = None
    outcome: OutcomeView | None = None
    can_edit: bool
    can_run: bool
    can_cancel: bool
    can_submit: bool


TASK_LABELS = {'CANCELLED': '已结束', 'COMPLETED': '本回合已交付', 'RUNNING': '正在处理',
               'WAITING_USER': '待补充', 'BLOCKED': '待继续', 'READY': '可继续', 'DRAFT': '待补充'}


def task_view(service, task_id):
    task = service.view(task_id)
    kind = task['guided_request']['kind']
    catalog = SERVICES.get(kind)
    ticket = task.get('current_ticket')
    cancelled = task['status'] == 'CANCELLED'
    editable = not cancelled and not task.get('receipt') and task['user_execution_ceiling'] != 'READ_ONLY'
    return TaskView(id=task_id, conversation_id=task.get('conversation_id'), kind=kind,
        title=catalog.title if catalog else '知识查询', status=ticket['status'] if ticket else task['status'],
        status_label=NOTICES.get(ticket['status'], ticket['status']) if ticket else TASK_LABELS.get(task['status'], '待处理'),
        next_step=task['next_step'], ceiling=task['user_execution_ceiling'], revision=task['facts_revision'],
        fields=[FieldView(**{k:v for k,v in field.items() if k in FieldView.model_fields}, value=task['facts'].get(field['name']))
                for field in catalog.field_specs()] if catalog else [],
        preview=task.get('preview'), receipt=task.get('receipt'), current_ticket=ticket,
        knowledge=task.get('knowledge_result'), outcome=task.get('outcome'),
        can_edit=editable, can_run=not cancelled and not task.get('active_run_id'),
        can_cancel=not cancelled and not task.get('receipt'),
        can_submit=editable and bool(task.get('preview')) and task['user_execution_ceiling']=='SUBMIT_AFTER_CONFIRMATION')


def product_router(workspace, service_call):
    router = APIRouter(prefix='/api/product')

    @router.post('/shutdown')
    def shutdown():
        callback=getattr(workspace,'request_shutdown',None)
        if callback is None:raise ServiceError('NOT_LAUNCHER_OWNED')
        callback()
        return {'stopping':True,'data_preserved':True}

    @router.post('/setup-demo')
    def setup_demo():
        from app.workbench_service import seed_sample
        if workspace.config.sample_data:return {'enabled':True}
        if workspace.service.list():raise ServiceError('EXISTING_TASKS_PREVENT_DEMO_SEED')
        workspace.save_settings({'sample_data':True})
        seed_sample(workspace.root)
        workspace.service.store.writes_enabled=True
        return {'enabled':True,'origin':'EXPLICIT_LOCAL_SYNTHETIC_SETUP'}

    @router.get('/answers/{answer_id}', response_model=PublishedAnswerView)
    def answer(answer_id: str):
        def read():
            result=next((a for a in workspace.library.answers() if a['id']==answer_id),None)
            if result is None:raise ServiceError('ANSWER_NOT_FOUND')
            return result
        return service_call(read)

    @router.get('/tasks', response_model=list[TaskView])
    def tasks():
        return [task_view(workspace.service, t['task_id']) for t in workspace.service.list()]

    @router.get('/tasks/{task_id}', response_model=TaskView)
    def task(task_id: str):
        return service_call(lambda: task_view(workspace.service, task_id))

    @router.post('/conversations/{cid}/turns/{turn_id}/retry', status_code=202)
    def retry(cid: str, turn_id: str):
        def start():
            workspace.conversations.get(cid)
            with workspace.conversations.db() as db:
                row = db.execute("SELECT * FROM conversation_turns WHERE id=? AND conversation_id=? AND role='user'", (turn_id,cid)).fetchone()
            if not row: raise ServiceError('TURN_NOT_FOUND')
            if row['status'] not in {'FAILED','CANCELLED','INTERRUPTED'}:raise ServiceError('TURN_NOT_RETRYABLE')
            return workspace.runs.start('conversation', {'conversation_id':cid,'text':row['text'],'message_id':turn_id})
        return service_call(start)

    @router.get('/conversations/{cid}/runs')
    def runs(cid: str):
        conversation=workspace.conversations.get(cid)
        targets=[cid,*conversation['task_history']]
        with workspace.runs.db() as db:
            rows=db.execute('SELECT * FROM workbench_runs WHERE target IN ('+','.join('?' for _ in targets)+') ORDER BY rowid DESC LIMIT 10',targets).fetchall()
        return [{'id':r['id'],'kind':r['kind'],'status':r['status'],'error':r['error']} for r in rows]

    return router
