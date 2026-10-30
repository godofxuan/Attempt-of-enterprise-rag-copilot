"""Two concrete local services sharing tasks, proposals, confirmation and commits."""
from dataclasses import dataclass
import json

from .contracts import UserFacts,RepairFacts


@dataclass(frozen=True)
class Service:
    key: str
    title: str
    facts_type: type
    fields: tuple
    ticket_table: str
    operation: str
    ticket_status: str
    next_step: str
    rule_need: str
    goal: str
    output_meanings: dict | None = None

    def bindings(self,rule,asset,extra):
        result={'asset_version':asset['version']}
        if self.key=='loan':result['repair_version']=extra['version']
        return result

    def rule(self,store,actor):
        from .store import ServiceError
        if self.key=='loan':return store.rule(actor)
        store.authorize(actor)
        with store.transaction() as db:row=db.execute('SELECT * FROM it_repair_rules WHERE tenant=?',(actor.tenant_id,)).fetchone()
        if not row:raise ServiceError('POLICY_NOT_CONFIGURED')
        return dict(row)

    def assets(self,store,actor,facts=None):
        if self.key=='loan':return store.assets(actor,facts)
        store.authorize(actor)
        with store.transaction() as db:
            return self.assets_in(db,actor)

    def assets_in(self,db,actor):
        rows=db.execute('SELECT * FROM it_assets WHERE tenant=? AND owner=? ORDER BY asset_id',(actor.tenant_id,actor.subject)).fetchall()
        return {'assets':[dict(r) for r in rows],'scope':'AUTHENTICATED_OWNED_IT_ASSETS','origin':'SYNTHETIC_TEST_BACKEND'}

    def validate(self,store,db,actor,task,asset_id,refs):
        from .store import ServiceError
        if self.key=='loan':return store._validate_business(db,actor,task,asset_id,refs)
        facts=task['facts'];missing=[k for k,_,_ in self.fields if not facts.get(k)]
        if missing:raise ServiceError('NEED_USER_FACT',data={'missing_fields':missing})
        if facts['asset_id']!=asset_id:raise ServiceError('USER_ASSET_SELECTION_MISMATCH')
        rule=db.execute('SELECT * FROM it_repair_rules WHERE tenant=?',(actor.tenant_id,)).fetchone()
        if rule is None:raise ServiceError('POLICY_NOT_CONFIGURED')
        asset=db.execute('SELECT * FROM it_assets WHERE tenant=? AND owner=? AND asset_id=?',
                         (actor.tenant_id,actor.subject,asset_id)).fetchone()
        if asset is None:raise ServiceError('NOT_OWNED_ASSET')
        if not asset['active']:raise ServiceError('RESOURCE_CHANGED')
        rows=db.execute("SELECT payload FROM it_repair_tickets WHERE tenant=? AND owner=? AND status IN ('OPEN','IN_PROGRESS','RESOLVED')",
                         (actor.tenant_id,actor.subject)).fetchall()
        existing=next((json.loads(r['payload']) for r in rows if json.loads(r['payload'])['asset_id']==asset_id),None)
        if existing:raise ServiceError('EXISTING_TICKET',data={'ticket_id':existing['ticket_id'],'ticket':existing,
            'next_actions':['tickets.get'],'message':'Read the existing owned repair ticket; do not create another for this asset.'})
        evidence=[e for r,e in task.get('knowledge',{}).items() if r in refs and e['version_id']==rule['version']
                  and e['text']==rule['content'] and e['need_refs']==[self.rule_need]]
        if not evidence:raise ServiceError('EVIDENCE_INSUFFICIENT')
        return dict(rule),dict(asset),{},evidence

    def check_preview(self,store,db,actor,content):
        from .store import ServiceError,digest
        if self.key=='loan':return store._check_loan_dependencies(db,actor,content)
        rule=db.execute('SELECT * FROM it_repair_rules WHERE tenant=?',(actor.tenant_id,)).fetchone()
        if rule is None or digest(dict(rule))!=content['rule_digest']:raise ServiceError('POLICY_CHANGED')
        asset=db.execute('SELECT * FROM it_assets WHERE tenant=? AND owner=? AND asset_id=?',
                         (actor.tenant_id,actor.subject,content['target'])).fetchone()
        if asset is None or not asset['active'] or asset['version']!=content['asset_version']:raise ServiceError('RESOURCE_CHANGED')

    def field_specs(self):
        """One definition for form labels, required facts and clarification."""
        fields=[{'name':name,'label':label,'type':kind,'required':True,
                 'question':f'请补充{label}。'} for name,label,kind in self.fields]
        if self.key=='loan':fields.extend([{'name':name,'label':label,'type':kind,'required':False,'question':''}
            for name,label,kind in [('min_memory_gb','最低内存 GB（可选）','integer'),('pickup_location','领用地点（可选）','text'),
                ('date_flex_days','可推迟天数 0—7（不填不改日期）','integer')]])
        return fields

    def questions(self,missing):
        specs={field['name']:field for field in self.field_specs()}
        return ' '.join(specs[name]['question'] for name in missing if name in specs)

    def public(self):return {'key':self.key,'title':self.title,'fields':self.field_specs(),
                            'ticket_status':self.ticket_status,'notice':self.next_step}


LOAN=Service('loan','临时电脑借用',UserFacts,(('loan_start','开始日期','date'),('loan_end','结束日期','date'),('purpose','用途','text')),
 'tickets','create_loan','PENDING_APPROVAL','Await service desk approval; no device has been allocated.','loan_policy',
 '临时电脑借用：查询本人维修资格、可用库存和本人申请。')
REPAIR=Service('repair','本地合成 IT 报修',RepairFacts,(('asset_id','本人设备编号','text'),('description','故障描述','text'),('impact','影响程度','impact')),
 'it_repair_tickets','create_repair','OPEN','待服务台受理，尚未完成维修；仅保存于本地合成 TEST 系统。','repair_policy',
 'IT报修：查询本人设备、报修规则和本人报修工单。',{'asset_status':'读取当前身份本人的有效IT设备，不查询借用库存。',
 'ticket_status':'读取当前身份本人的IT报修工单，包括正确的空列表。',
 'open_application':'按设备、描述和影响程度准备报修预览；用户精确确认后提交一次并读回OPEN待受理工单，不宣称维修完成。'})
SERVICES={service.key:service for service in (LOAN,REPAIR)}


def service_for(task):
    from .store import ServiceError
    key=task.get('guided_request',{}).get('kind','loan')
    if key not in SERVICES:raise ServiceError('NO_WRITE_GOAL')
    return SERVICES[key]


def by_operation(operation):
    from .store import ServiceError
    for service in SERVICES.values():
        if service.operation==operation:return service
    raise ServiceError('INVALID_OPERATION')


def initialize_tables(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS it_assets(tenant TEXT,owner TEXT,asset_id TEXT,category TEXT,active INTEGER,version INTEGER,
            PRIMARY KEY(tenant,asset_id));
        CREATE TABLE IF NOT EXISTS it_repair_rules(tenant TEXT PRIMARY KEY,version TEXT,content TEXT);
        CREATE TABLE IF NOT EXISTS it_repair_tickets(ticket_id TEXT PRIMARY KEY,tenant TEXT NOT NULL,owner TEXT NOT NULL,
            task_id TEXT NOT NULL,command_id TEXT UNIQUE NOT NULL,status TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS one_open_it_repair ON it_repair_tickets(tenant,owner,json_extract(payload,'$.asset_id'))
            WHERE status IN ('OPEN','IN_PROGRESS');
    ''')
    definition=db.execute("SELECT sql FROM sqlite_master WHERE name='one_open_it_repair'").fetchone()
    if definition and 'RESOLVED' not in definition[0]:db.execute('DROP INDEX one_open_it_repair')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_open_it_repair ON it_repair_tickets(tenant,owner,json_extract(payload,'$.asset_id')) WHERE status IN ('OPEN','IN_PROGRESS','RESOLVED')")


def seed_repairs(store,actor):
    with store.transaction() as db:
        db.execute('INSERT OR IGNORE INTO it_assets VALUES(?,?,?,?,?,?)',
            (actor.tenant_id,actor.subject,'employee-laptop-1','laptop',1,1))
        db.execute('INSERT OR IGNORE INTO it_repair_rules VALUES(?,?,?)',(actor.tenant_id,'synthetic-it-repair-v1',
            '合成演示规则：仅能为本人有效设备报修，需设备编号、故障描述及low/medium/high影响程度。'
            '同一设备已有未关闭报修时读取原工单，不重复创建。预览经用户精确确认后保存OPEN待受理工单；'
            '这不代表维修完成，也不修改借用资格的维修记录。'))


def finish_repair(store,actor,task_id):
    """Domain outcome from current SQLite observations, never model free prose."""
    from .store import ServiceError,digest
    with store.transaction() as db:
        task=store._task(db,actor,task_id);store._live(task)
        if task.get('pending_user_update'):raise ServiceError('USER_UPDATE_PENDING')
        query=store._current_ticket_query(db,actor,task);ticket=store._committed_ticket(db,actor,task)
        current_assets=REPAIR.assets_in(db,actor)
        asset_seen=any(o['tool']=='assets.search' and o['result'].get('status')=='ok'
                       and o['result'].get('data')==current_assets for o in task['observations'])
        status='BLOCKED';satisfied=False;answer='尚缺当前本人设备或工单查询；未提交报修。'
        if ticket:
            status='COMPLETED';satisfied=True;answer='已在本地 TEST 系统创建报修工单，当前为待受理，尚未维修。'+json.dumps(ticket,ensure_ascii=False)
        elif task.get('pending_proposal_id') and task['user_execution_ceiling']=='PREVIEW_ONLY':
            _,content=store._bound_proposal(db,actor,task,task['pending_proposal_id']);REPAIR.check_preview(store,db,actor,content)
            status='COMPLETED';satisfied=True;answer='已交付仅预览的报修内容，没有提交工单。'+json.dumps(content['parameters'],ensure_ascii=False)
        elif query and asset_seen:
            if task['user_execution_ceiling']=='READ_ONLY':
                status='COMPLETED';satisfied=True;answer=json.dumps({'owned_assets':current_assets,'owned_repairs':query['tickets'],'notice':'仅查询，未创建申请'},ensure_ascii=False)
            else:
                existing=[t for t in query['tickets'] if t['asset_id']==task['facts'].get('asset_id') and t['status'] in ('OPEN','IN_PROGRESS')]
                read=task.get('resolved_ticket_results',{})
                if existing and all(read.get(t['ticket_id'])==t for t in existing):
                    status='COMPLETED';satisfied=True;answer='已读取该设备已有报修，没有重复提交。'+json.dumps(existing,ensure_ascii=False)
        outcome={'outcome_kind':'repair_result','goal_satisfied':satisfied,'answer':answer,
                 'business_status':ticket['status'] if ticket else None,'next_step':REPAIR.next_step if ticket else '查看当前参数与工具结果',
                 'completed_outputs':task['task_goal']['required_outputs'] if satisfied else [],'missing_user_facts':[]}
        task.update(status=status,active_run_id=None,outcome=outcome,last_error=None if satisfied else 'GOAL_NOT_COMPLETE')
        store._save(db,task);store._event(db,task_id,'host.finish',outcome)
        return outcome
