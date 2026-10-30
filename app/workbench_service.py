"""Product service projection over the existing transactional ServiceDeskStore."""
from datetime import datetime, timedelta, timezone
import json

from app.security.identity import Principal
from app.service_desk.contracts import GuidedTaskRequest
from app.service_desk.store import ServiceDeskStore, ServiceError, encoded, digest
from app.service_desk.catalog import SERVICES,service_for,seed_repairs


def local_actor():
    now=datetime.now(timezone.utc)
    return Principal(subject='local-owner',tenant_id='local',region='local',groups=['employees','local-owner'],
        roles=['employee'],issuer='esa-local-owner',audience='esa-workbench',key_id='local',
        issued_at=now,expires_at=now+timedelta(days=1))


def seed_sample(root):
    """Only explicit init --sample provisions the synthetic backend."""
    store=ServiceDeskStore(root/'app.sqlite3',writes_enabled=True);store.seed_demo(local_actor())
    seed_repairs(store,local_actor())
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
                pending=db.execute("SELECT id FROM workbench_messages WHERE task_id=? AND status IN ('PENDING','FAILED') ORDER BY rowid DESC LIMIT 1",(task['task_id'],)).fetchone()
                committed=db.execute(f'SELECT 1 FROM {self.store.ticket_table(task)} WHERE task_id=?',(task['task_id'],)).fetchone()
                if pending and not task.get('pending_user_update') and not task.get('receipt') and not committed and task['status']!='CANCELLED':
                    task.update(pending_user_update=pending['id'],status='WAITING_USER',last_error='USER_UPDATE_PENDING')
                    self.store._save(db,task)
                    self.store._event(db,task['task_id'],'pending_update_recovered',{'message_id':pending['id'],
                        'reason':'Existing unprocessed user input retained, not silently discarded'})

    def create(self,request,kb_id=None,conversation_id=None):
        request=GuidedTaskRequest.model_validate(request)
        task=self.store.create_task(local_actor(),'',guided_request=request.model_dump(mode='json'))
        with self.store.transaction() as db:
            current=self.store._task(db,local_actor(),task['task_id'])
            current.update(product_runtime=True,kb_id=kb_id,run_fence=0)
            self.store._save(db,current)
        if hasattr(self.workspace,'conversations'):self.workspace.conversations.bind(task['task_id'],conversation_id)
        return self.view(task['task_id'])

    @staticmethod
    def required_fields(task):
        if task['guided_request']['kind']=='knowledge' or task['user_execution_ceiling']=='READ_ONLY':return []
        return [field['name'] for field in service_for(task).field_specs() if field['required']]

    def assets(self,task_id):
        task=self.store.get_task(local_actor(),task_id)
        result=service_for(task).assets(self.store,local_actor(),task['facts'])
        return {**result,'alternatives':self.alternatives(task_id)} if task['guided_request']['kind']=='loan' else result

    def tickets(self,task_id):
        service=service_for(self.store.get_task(local_actor(),task_id))
        return self.store.list_tickets(local_actor(),kind=service.key)

    def ticket(self,task_id,ticket_id):
        service=service_for(self.store.get_task(local_actor(),task_id))
        return self.store.get_ticket(local_actor(),ticket_id,kind=service.key)

    def list(self):
        actor=local_actor()
        with self.store.transaction() as db:
            rows=db.execute('SELECT payload FROM agent_tasks WHERE tenant=? AND owner=? ORDER BY rowid DESC LIMIT 50',(actor.tenant_id,actor.subject)).fetchall()
        tasks=[json.loads(row['payload']) for row in rows]
        return [{key:task.get(key) for key in ('task_id','status','revision','facts_revision','goal','facts','guided_request')} for task in tasks]

    def view(self,task_id):
        actor=local_actor();task=self.store.get_task(actor,task_id)
        proposal=self.store.proposal(actor,task_id) if task.get('pending_proposal_id') else None
        pending=None
        if task.get('pending_user_update'):
            with self.store.transaction() as db:
                row=db.execute('SELECT id,text,status FROM workbench_messages WHERE id=?',(task['pending_user_update'],)).fetchone()
                pending=dict(row) if row else {'id':task['pending_user_update'],'text':'Unresolved user input','status':'UNRESOLVED'}
        current_ticket=self.ticket(task_id,task['receipt']['ticket_id']) if task.get('receipt') else None
        return {**task,'current_ticket':current_ticket,'preview':proposal,'pending_update':pending,'events':self.store.events(actor,task_id)[-40:],
                'missing_fields':[k for k in self.required_fields(task) if not task['facts'].get(k)],
                'next_step':current_ticket['next_step'] if current_ticket else
                    '补充内容尚未成功解释，请检查原文并明确当前任务范围；在此之前不继续办理' if pending else
                    '请核对当前完整预览并精确确认' if proposal and task['user_execution_ceiling']=='SUBMIT_AFTER_CONFIRMATION' else
                    '仅预览，不可提交' if proposal else
                    '本次任务已交付，可查看结果或新建任务' if task['status']=='COMPLETED' else
                    (task.get('outcome') or {}).get('next_step') or '补充信息或继续运行'}

    def facts(self,task_id,changes,revision):
        previous=self.store.get_task(local_actor(),task_id)
        self.store.update_facts(local_actor(),task_id,changes,expected_facts_revision=revision)
        if previous['facts']!={**previous['facts'],**changes}:
            affected=set()
            for key in changes:affected.update({'loan_start':['assets.search','tickets.propose_create'],
                'loan_end':['assets.search','tickets.propose_create'],'purpose':['tickets.propose_create'],
                'asset_id':['assets.search','tickets.propose_create'],'description':['tickets.propose_create'],
                'impact':['tickets.propose_create']}.get(key,[]))
            self.store.record(local_actor(),task_id,'field_impact',{'changed_fields':list(changes),'invalidated':sorted(affected),
                'retained_if_current':['loan_policy','tickets.list_mine'],'authority':'HOST_DEPENDENCY_TABLE'})
        return self.view(task_id)

    def valid_observations(self,task):
        if task['guided_request']['kind']=='knowledge':return {}
        service=service_for(task)
        actor=local_actor();valid={}
        current_assets=self.assets(task['task_id']);current_tickets={'tickets':self.store.list_tickets(actor,kind=service.key)}
        for row in task['observations']:
            if row['result'].get('status')!='ok':continue
            meta=row.get('dependency_context',{})
            if self.store.clock()-meta.get('observed_at',0)>60:continue
            name=row['tool'];data=row['result']['data']
            fields=('loan_start','loan_end','min_memory_gb','pickup_location','date_flex_days') if service.key=='loan' else ()
            bound_facts=(meta['facts_projection']=={field:task['facts'].get(field) for field in fields}
                if 'facts_projection' in meta else meta.get('facts_revision')==task['facts_revision'])
            if name=='assets.search' and bound_facts and data==current_assets:
                valid['assets_search']=data
            if name=='tickets.list_mine' and data==current_tickets:valid['tickets_list_mine']=data
        try:
            rule=service.rule(self.store,actor)
            policy=next((e for e in task.get('knowledge',{}).values()
                         if e.get('need_refs')==[service.rule_need] and e['version_id']==rule['version'] and e['text']==rule['content']),None)
            if policy:valid[service.rule_need]=policy
        except ServiceError:pass
        return valid

    async def message(self,task_id,text,message_id,expected_facts_revision,detailed=False):
        from app.conversations import ConversationService
        if not hasattr(self.workspace,'conversations'):
            self.workspace.conversations=ConversationService(self.workspace)
        return await self.workspace.conversations.task_turn(task_id,text,message_id,expected_facts_revision,detailed=detailed)

    def message_failed(self,task_id,message_id,error):
        actor=local_actor()
        with self.store.transaction() as db:
            task=self.store._task(db,actor,task_id)
            if task.get('pending_user_update')!=message_id:return
            db.execute("UPDATE workbench_messages SET status='FAILED',result=? WHERE id=? AND status='PENDING'",(error,message_id))
            task.update(status='WAITING_USER',last_error='USER_UPDATE_PENDING')
            self.store._save(db,task)
            self.store._event(db,task_id,'user_update_failed',{'message_id':message_id,'error':error})

    def message_cancelled(self,task_id,message_id):
        actor=local_actor()
        with self.store.transaction() as db:
            task=self.store._task(db,actor,task_id)
            if task.get('pending_user_update')!=message_id:return
            task.pop('pending_user_update',None)
            db.execute("UPDATE workbench_messages SET status='CANCELLED' WHERE id=? AND status='PENDING'",(message_id,))
            if task['status']!='CANCELLED':task.update(status='WAITING_USER',last_error='MESSAGE_CANCELLED')
            self.store._save(db,task)
            self.store._event(db,task_id,'user_update_cancelled',{'message_id':message_id,'applied':False})

    def resolve_update(self,task_id,ceiling,revision,reviewed):
        """Explicit user scope correction, separate from a submission confirmation."""
        if reviewed is not True:raise ServiceError('EXPLICIT_SCOPE_REVIEW_REQUIRED')
        actor=local_actor();task=self.store.get_task(actor,task_id)
        if not task.get('pending_user_update'):raise ServiceError('NO_PENDING_USER_UPDATE')
        order=['READ_ONLY','PREVIEW_ONLY','SUBMIT_AFTER_CONFIRMATION']
        if ceiling not in order:raise ServiceError('INVALID_ARGUMENTS')
        revoked=[digest(c) for c in task['task_goal']['constraint_sources']] if order.index(ceiling)>order.index(task['user_execution_ceiling']) else []
        message_id='scope-review-'+task['pending_user_update']
        self.store.change_execution_scope(actor,task_id,ceiling,revoked,message_id,
            '用户已查看未成功解释的补充原文，明确选择当前范围：'+ceiling,
            scope_confirmed=True,expected_facts_revision=revision)
        with self.store.transaction() as db:
            current=self.store._task(db,actor,task_id)
            pending=current.pop('pending_user_update')
            db.execute("UPDATE workbench_messages SET status='USER_RESOLVED' WHERE id=?",(pending,))
            self.store._save(db,current)
            self.store._event(db,task_id,'user_resolved_update',{'message_id':pending,'execution_ceiling':ceiling,
                'authority':'EXPLICIT_USER_SCOPE_REVIEW_NOT_SUBMISSION_CONSENT'})
        return self.view(task_id)

    def alternatives(self,task_id):
        task=self.store.get_task(local_actor(),task_id)
        if task['guided_request']['kind']=='repair':
            return [{'asset_id':a['asset_id'],'category':a['category'],'version':a['version'],'available':bool(a['active']),
                     'parameters':task['facts'],'details':{'owner':'当前用户','origin':'SYNTHETIC_OWNED_ASSET'},
                     'notice':'选择本人设备，不改变故障描述和影响程度；不是借用或分配设备'}
                    for a in service_for(task).assets(self.store,local_actor())['assets'] if a['active']][:3]
        from app.service_desk.scheduling import inventory
        from datetime import date
        result=[];facts=task['facts'];dated=bool(facts.get('loan_start') and facts.get('loan_end'))
        with self.store.transaction() as db:
            for shift in range((facts.get('date_flex_days') or 0)+1 if dated else 1):
                parameters=dict(facts)
                if shift:
                    for key in ('loan_start','loan_end'):parameters[key]=str(date.fromisoformat(facts[key])+timedelta(days=shift))
                for asset in inventory(db,local_actor(),parameters):
                    if asset['category']!='laptop':continue
                    result.append({**asset,'available':True,'parameters':parameters,'date_shift_days':shift,
                        'difference':f'日期推迟{shift}天；其余参数和偏好保持' if shift else '请求日期和用途不变；匹配真实规格及排期',
                        'notice':'这是当前可选方案，不是预留；批准时再次检查日期冲突。' if dated else '未提供完整日期，当前只显示规格，不保证日期可用。'})
                    if len(result)==3:return result
        return result

    def choose_asset(self,task_id,asset_id,revision,date_shift_days=0):
        actor=local_actor()
        task=self.store.get_task(actor,task_id)
        if task['guided_request']['kind']=='repair':
            assets=service_for(task).assets(self.store,actor)['assets']
            if not any(a['asset_id']==asset_id and a['active'] for a in assets):raise ServiceError('NOT_OWNED_ASSET')
            return self.facts(task_id,{'asset_id':asset_id},revision)
        with self.store.transaction() as db:
            task=self.store._task(db,actor,task_id);self.store._live(task)
            if task.get('receipt') or (task.get('active_run_id') and not self.store.owns_run(task)):raise ServiceError('TASK_BUSY_OR_SUBMITTED')
            if task['facts_revision']!=revision:raise ServiceError('TASK_CHANGED')
            if type(date_shift_days) is not int or not 0<=date_shift_days<=(task['facts'].get('date_flex_days') or 0):
                raise ServiceError('DATE_CHANGE_NOT_AUTHORIZED')
            if date_shift_days:
                from datetime import date
                from app.service_desk.goals import structured_goal_fields
                for key in ('loan_start','loan_end'):
                    if not task['facts'].get(key):raise ServiceError('INVALID_DATES')
                    task['facts'][key]=str(date.fromisoformat(task['facts'][key])+timedelta(days=date_shift_days))
                task['guided_request']['facts']=dict(task['facts'])
                self.store._refresh_guided(task)
                self.store._event(db,task_id,'user_candidate_dates',{'shift_days':date_shift_days,'authority':'EXPLICIT_USER_CANDIDATE_SELECTION','facts':task['facts']})
            from app.service_desk.scheduling import check_resource
            if task['facts'].get('loan_start') and task['facts'].get('loan_end'):
                check_resource(db,actor,asset_id,task['facts'])
            if not db.execute('SELECT 1 FROM assets WHERE tenant=? AND asset_id=? AND available=1 AND category=?',(actor.tenant_id,asset_id,'laptop')).fetchone():
                raise ServiceError('RESOURCE_CHANGED')
            if task.get('preferred_asset_id')==asset_id and not date_shift_days:return {'selected_asset_id':asset_id,'unchanged':True}
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
            committed=db.execute('SELECT 1 FROM command_ledger WHERE command_id=?',(self.store.command_id(task,payload['proposal_id']),)).fetchone()
        if not committed:
            if task.get('pending_user_update'):raise ServiceError('USER_UPDATE_PENDING')
            if payload['expected_facts_revision']!=task['facts_revision']:raise ServiceError('TASK_CHANGED')
            self.store.confirm(actor,task_id,payload['proposal_id'],payload['content_digest'],payload['accepted'])
        self.store.submit(actor,task_id,payload['proposal_id'])
        self.store.readback(actor,task_id,payload['proposal_id'])
        return self.view(task_id)

    def policy(self,task_id):
        actor=local_actor();task=self.store.get_task(actor,task_id);service=service_for(task);rule=service.rule(self.store,actor)
        ref='local-policy-'+digest(rule)[:16]
        evidence={'ref':ref,'document_id':'synthetic-'+service.key+'-policy','version_id':rule['version'],
                  'text':rule['content'],'need_refs':[service.rule_need],'source_path':'local SQLite '+('loan_rules' if service.key=='loan' else 'it_repair_rules'),
                  'authority':'SYNTHETIC_BUSINESS_RULE_NOT_AN_UPLOADED_POLICY'}
        self.store.remember_knowledge(actor,task_id,[evidence])
        return evidence

    async def run(self,task_id,run_id):
        if self.store.get_task(local_actor(),task_id).get('pending_user_update'):raise ServiceError('USER_UPDATE_PENDING')
        from app.agent_runtime.workbench_agent import build_service_agent
        return await build_service_agent(self).run(task_id,run_id)

    def finish_turn(self,task_id,text):
        actor=local_actor()
        with self.store.transaction() as db:
            task=self.store._task(db,actor,task_id)
            self.store._live(task)
            missing=[k for k in self.required_fields(task) if not task['facts'].get(k)]
            task['question']=service_for(task).questions(missing) if missing else None
            # Raw prose remains in model_response events. Business delivery is
            # assembled from actual changed facts, published knowledge and preview.
            parts=[]
            if task.get('knowledge_result'):parts.append(task['knowledge_result']['result']['answer'])
            if task.get('receipt'):parts.append('当前工单状态请见实际业务状态；原提交回执保持不变。')
            elif task.get('pending_proposal_id'):parts.append('当前完整预览已生成。请核对当前参数；仅当前精确确认才可提交。' if task['user_execution_ceiling']=='SUBMIT_AFTER_CONFIRMATION' else '已生成仅预览内容，不会提交。')
            elif missing:parts.append(service_for(task).questions(missing))
            else:parts.append('当前参数：'+encoded(task['facts'])+'。本回合没有生成新的业务回执。')
            task['assistant_text']='\n'.join(parts) if task['guided_request']['kind']!='knowledge' else text
            task['status']=('COMPLETED' if task.get('receipt') else 'WAITING_CONFIRMATION' if task.get('pending_proposal_id')
                and task['user_execution_ceiling']=='SUBMIT_AFTER_CONFIRMATION' else 'WAITING_USER' if missing else 'NEW')
            if task['guided_request']['kind']=='knowledge':
                answer=task.get('knowledge_result')
                task['status']='COMPLETED' if answer and answer['result']['mode']=='answered' else 'BLOCKED'
            self.store._save(db,task)
