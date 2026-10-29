"""Product service projection over the existing transactional ServiceDeskStore."""
from datetime import datetime, timedelta, timezone
import json
from typing import Literal

from app.security.identity import Principal
from app.service_desk.contracts import GuidedTaskRequest
from app.service_desk.store import ServiceDeskStore, ServiceError, encoded, digest
from pydantic import BaseModel, ConfigDict, Field
from app.service_desk.contracts import UserFacts


class ParameterChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    field: Literal['loan_start','loan_end','purpose']
    value: str | None
    quote: str


class MessageInterpretation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    updates: list[ParameterChange] = Field(max_length=3)
    execution_ceiling: Literal['READ_ONLY','PREVIEW_ONLY','SUBMIT_AFTER_CONFIRMATION'] | None = None
    scope_quote: str = ''


def local_actor():
    now=datetime.now(timezone.utc)
    return Principal(subject='local-owner',tenant_id='local',region='local',groups=['employees','local-owner'],
        roles=['employee'],issuer='esa-local-owner',audience='esa-workbench',key_id='local',
        issued_at=now,expires_at=now+timedelta(days=1))


def seed_sample(root):
    """Only explicit init --sample provisions the synthetic backend."""
    store=ServiceDeskStore(root/'app.sqlite3',writes_enabled=True);store.seed_demo(local_actor())
    with store.transaction() as db:
        db.execute('CREATE TABLE IF NOT EXISTS asset_details(tenant TEXT,asset_id TEXT,payload TEXT,PRIMARY KEY(tenant,asset_id))')
        for asset_id,memory,location in [('loan-laptop-1',8,'A区服务台'),('loan-laptop-2',16,'B区服务台'),('loan-laptop-3',32,'A区服务台')]:
            db.execute('INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?)',('local',asset_id,'laptop',1,1))
            db.execute('INSERT OR IGNORE INTO asset_details VALUES(?,?,?)',('local',asset_id,encoded({'memory_gb':memory,'pickup_location':location,'origin':'SYNTHETIC_SAMPLE_ASSET'})))


class TaskService:
    def __init__(self,workspace):
        self.workspace=workspace
        self.store=ServiceDeskStore(workspace.db_path,writes_enabled=workspace.config.sample_data)
        with self.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS workbench_messages(id TEXT PRIMARY KEY,task_id TEXT,
                text TEXT,status TEXT,result TEXT)''')
            # Recover only this product's interrupted task execution, not historical experiments.
            for row in db.execute('SELECT payload FROM agent_tasks').fetchall():
                task=json.loads(row['payload'])
                if task.get('product_runtime') and task.get('active_run_id'):
                    task.update(active_run_id=None,status='BLOCKED',last_error='PROCESS_INTERRUPTED',
                                run_fence=task.get('run_fence',0)+1)
                    self.store._save(db,task)

    def create(self,request,kb_id=None):
        request=GuidedTaskRequest.model_validate(request)
        task=self.store.create_task(local_actor(),'',guided_request=request.model_dump(mode='json'))
        with self.store.transaction() as db:
            current=self.store._task(db,local_actor(),task['task_id'])
            current.update(product_runtime=True,kb_id=kb_id,run_fence=0)
            self.store._save(db,current)
        return self.view(task['task_id'])

    def list(self):
        actor=local_actor()
        with self.store.transaction() as db:
            ids=[r['task_id'] for r in db.execute('SELECT task_id FROM agent_tasks WHERE tenant=? AND owner=?',(actor.tenant_id,actor.subject))]
        return [self.view(task_id) for task_id in reversed(ids)]

    def view(self,task_id):
        actor=local_actor();task=self.store.get_task(actor,task_id)
        proposal=self.store.proposal(actor,task_id) if task.get('pending_proposal_id') else None
        return {**task,'preview':proposal,'events':self.store.events(actor,task_id)[-40:],
                'missing_fields':[k for k in ('loan_start','loan_end','purpose') if not task['facts'].get(k)],
                'next_step':'待审批，不等于已批准、已分配或已预留。' if task.get('receipt') else
                    '请核对当前完整预览并精确确认' if proposal and task['user_execution_ceiling']=='SUBMIT_AFTER_CONFIRMATION' else
                    '仅预览，不可提交' if proposal else '补充信息或继续运行'}

    def facts(self,task_id,changes,revision):
        previous=self.store.get_task(local_actor(),task_id)
        self.store.update_facts(local_actor(),task_id,changes,expected_facts_revision=revision)
        if previous['facts']!={**previous['facts'],**changes}:
            affected=set()
            for key in changes:affected.update({'loan_start':['assets.search','tickets.propose_create'],
                'loan_end':['assets.search','tickets.propose_create'],'purpose':['tickets.propose_create']}.get(key,[]))
            self.store.record(local_actor(),task_id,'field_impact',{'changed_fields':list(changes),'invalidated':sorted(affected),
                'retained_if_current':['loan_policy','tickets.list_mine'],'authority':'HOST_DEPENDENCY_TABLE'})
        return self.view(task_id)

    def valid_observations(self,task):
        actor=local_actor();valid={}
        current_assets=self.store.assets(actor);current_tickets={'tickets':self.store.list_tickets(actor)}
        for row in task['observations']:
            if row['result'].get('status')!='ok':continue
            meta=row.get('dependency_context',{})
            if self.store.clock()-meta.get('observed_at',0)>60:continue
            name=row['tool'];data=row['result']['data']
            if name=='assets.search' and meta.get('facts_revision')==task['facts_revision'] and data==current_assets:
                valid['assets_search']=data
            if name=='tickets.list_mine' and data==current_tickets:valid['tickets_list_mine']=data
        try:
            rule=self.store.rule(actor)
            policy=next((e for e in task.get('knowledge',{}).values()
                         if e.get('need_refs')==['loan_policy'] and e['version_id']==rule['version'] and e['text']==rule['content']),None)
            if policy:valid['loan_policy']=policy
        except ServiceError:pass
        return valid

    async def message(self,task_id,text,message_id,expected_facts_revision):
        actor=local_actor();task=self.store.get_task(actor,task_id)
        with self.store.transaction() as db:
            known=db.execute('SELECT * FROM workbench_messages WHERE id=?',(message_id,)).fetchone()
        if known:
            if known['task_id']!=task_id or known['text']!=text:raise ServiceError('MESSAGE_ID_CONFLICT')
            if known['status']!='APPLIED':raise ServiceError('MESSAGE_NOT_APPLIED')
            return self.view(task_id)
        if task.get('receipt') or task['status']=='CANCELLED':raise ServiceError('TASK_BUSY_OR_SUBMITTED')
        if task['facts_revision']!=expected_facts_revision:raise ServiceError('TASK_CHANGED')
        with self.store.transaction() as db:
            existing=db.execute('SELECT * FROM workbench_messages WHERE id=?',(message_id,)).fetchone()
            if existing:
                if existing['task_id']!=task_id or existing['text']!=text:raise ServiceError('MESSAGE_ID_CONFLICT')
                if existing['status']!='APPLIED':raise ServiceError('MESSAGE_NOT_APPLIED')
            else:db.execute('INSERT INTO workbench_messages VALUES(?,?,?,?,?)',(message_id,task_id,text,'PENDING',None))
        if existing:return self.view(task_id)
        prompt=('Interpret only explicit parameter changes in this user message. Missing keys mean no change; '
            'null means the user explicitly clears that field. Preserve all existing facts and prohibitions otherwise. '
            'For every changed field give its exact supporting substring in sources. Interpret relative dates using '
            'the supplied reference date. Scope may only tighten based on an exact user quote; never grant submission. '
            'Use updates, an array of field/value/quote records. Allowed fields: loan_start (start date YYYY-MM-DD), '
            'loan_end (end date YYYY-MM-DD), purpose (only the purpose verbatim, without dates or operations). '
            'One record per explicitly changed field; quote is the exact supporting user substring. '
            'Return JSON updates/execution_ceiling/scope_quote. Current facts and scope: '+
            json.dumps({'facts':task['facts'],'scope':task['user_execution_ceiling'],'reference_date':str(self.store.today())},ensure_ascii=False))
        response=await self.workspace.models.chat([{'role':'system','content':prompt},{'role':'user','content':text}],
            response_format=MessageInterpretation.model_json_schema(),max_tokens=500)
        interpreted=MessageInterpretation.model_validate_json(response['content'])
        changes={row.field:row.value for row in interpreted.updates}
        sources={row.field:row.quote for row in interpreted.updates}
        if len(changes)!=len(interpreted.updates) or any(not q or q not in text for q in sources.values()):
            raise ServiceError('UNBOUND_PARAMETER_UPDATE')
        if changes.get('purpose') and changes['purpose'] not in sources['purpose']:
            raise ServiceError('UNBOUND_PARAMETER_UPDATE')
        UserFacts.model_validate(changes)
        if interpreted.execution_ceiling and interpreted.execution_ceiling!=task['user_execution_ceiling']:
            order=['READ_ONLY','PREVIEW_ONLY','SUBMIT_AFTER_CONFIRMATION']
            scope=interpreted.execution_ceiling
            if scope not in order or order.index(scope)>order.index(task['user_execution_ceiling']):
                raise ServiceError('SCOPE_CHANGE_REQUIRES_USER_FORM')
            if not interpreted.scope_quote or interpreted.scope_quote not in text:raise ServiceError('UNBOUND_SCOPE_CHANGE')
            self.store.change_execution_scope(actor,task_id,scope,[],message_id,text,scope_confirmed=True,
                expected_facts_revision=expected_facts_revision)
            task=self.store.get_task(actor,task_id)
        if changes:self.facts(task_id,changes,task['facts_revision'])
        with self.store.transaction() as db:
            current=self.store._task(db,actor,task_id)
            if message_id not in {m['id'] for m in current['messages']}:
                current['messages'].append({'id':message_id,'text':text,'origin':'USER_MESSAGE'})
            for field,quote in sources.items():
                current.setdefault('fact_sources',{})[field]={'origin':'USER_MESSAGE','source_message_id':message_id,
                    'quote':quote,'start':text.index(quote),'end':text.index(quote)+len(quote)}
            self.store._save(db,current)
            db.execute("UPDATE workbench_messages SET status='APPLIED',result=? WHERE id=?",(interpreted.model_dump_json(),message_id))
            self.store._event(db,task_id,'message_parameters',{'message_id':message_id,'text':text,'interpretation':interpreted.model_dump(mode='json')})
        return self.view(task_id)

    def alternatives(self,task_id):
        task=self.store.get_task(local_actor(),task_id)
        data=self.store.assets(local_actor())
        with self.store.transaction() as db:
            has_details=db.execute("SELECT 1 FROM sqlite_master WHERE name='asset_details'").fetchone()
            details={r['asset_id']:json.loads(r['payload']) for r in db.execute('SELECT * FROM asset_details WHERE tenant=?',(local_actor().tenant_id,))} if has_details else {}
        return [{'asset_id':a['asset_id'],'category':a['category'],'version':a['version'],
                 'available':bool(a['available']),'parameters':task['facts'],
                 'details':details.get(a['asset_id'],{}),
                 'difference':'不同的实际设备；日期和用途保持不变','notice':'不预留；后端没有未来排期数据，不承诺未来日期有货'}
                for a in data['assets'] if a['category']=='laptop'][:3]

    def choose_asset(self,task_id,asset_id,revision):
        actor=local_actor()
        with self.store.transaction() as db:
            task=self.store._task(db,actor,task_id);self.store._live(task)
            if task.get('receipt') or task.get('active_run_id'):raise ServiceError('TASK_BUSY_OR_SUBMITTED')
            if task['facts_revision']!=revision:raise ServiceError('TASK_CHANGED')
            if not db.execute('SELECT 1 FROM assets WHERE tenant=? AND asset_id=? AND available=1 AND category=?',(actor.tenant_id,asset_id,'laptop')).fetchone():
                raise ServiceError('RESOURCE_CHANGED')
            if task.get('preferred_asset_id')==asset_id:return {'selected_asset_id':asset_id,'unchanged':True}
            task.update(preferred_asset_id=asset_id,facts_revision=task['facts_revision']+1,
                        pending_proposal_id=None,status='NEW')
            self.store._invalidate_derived(db,task,'user_asset_selection')
            self.store._save(db,task)
            self.store._event(db,task_id,'user_asset_selection',{'asset_id':asset_id,'authority':'USER_UI'})
        return self.view(task_id)

    def submit(self,task_id,payload):
        actor=local_actor();task=self.store.get_task(actor,task_id)
        # A committed command is read back even after client response loss; no new consent fabricated.
        with self.store.transaction() as db:
            committed=db.execute('SELECT 1 FROM command_ledger WHERE command_id=?',('loan:'+payload['proposal_id'],)).fetchone()
        if not committed:
            if payload['expected_facts_revision']!=task['facts_revision']:raise ServiceError('TASK_CHANGED')
            self.store.confirm(actor,task_id,payload['proposal_id'],payload['content_digest'],payload['accepted'])
        self.store.submit(actor,task_id,payload['proposal_id'])
        self.store.readback(actor,task_id,payload['proposal_id'])
        return self.view(task_id)

    def policy(self,task_id):
        actor=local_actor();rule=self.store.rule(actor)
        ref='local-policy-'+digest(rule)[:16]
        evidence={'ref':ref,'document_id':'synthetic-loan-policy','version_id':rule['version'],
                  'text':rule['content'],'need_refs':['loan_policy'],'source_path':'local SQLite loan_rules',
                  'authority':'SYNTHETIC_BUSINESS_RULE_NOT_AN_UPLOADED_POLICY'}
        self.store.remember_knowledge(actor,task_id,[evidence])
        return evidence

    async def run(self,task_id,run_id):
        from app.agent_runtime.workbench_agent import build_service_agent
        return await build_service_agent(self).run(task_id,run_id)
