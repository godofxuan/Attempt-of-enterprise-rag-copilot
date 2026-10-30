"""Local TEST processing actions reuse proposals, exact confirmations and command ledger."""
from dataclasses import dataclass
from datetime import date
import json
from uuid import uuid4
from .store import ServiceError,encoded,digest
from .catalog import SERVICES
from . import scheduling

@dataclass(frozen=True)
class ActionSpec:
    name:str
    label:str
    states:tuple
    target:str

ACTIONS={
 'loan':(ActionSpec('approve','批准并预留',('PENDING_APPROVAL',),'RESERVED'),
         ActionSpec('reject','拒绝申请',('PENDING_APPROVAL',),'REJECTED'),
         ActionSpec('withdraw','撤回待审批申请',('PENDING_APPROVAL',),'CANCELLED'),
         ActionSpec('cancel','取消并释放预留',('RESERVED',),'CANCELLED'),
         ActionSpec('checkout','登记领用',('RESERVED',),'CHECKED_OUT'),
         ActionSpec('return','登记归还',('CHECKED_OUT',),'RETURNED'),
         ActionSpec('extend','续借预览',('CHECKED_OUT',),'CHECKED_OUT')),
 'repair':(ActionSpec('start','开始处理',('OPEN',),'IN_PROGRESS'),
           ActionSpec('resolve','登记解决',('IN_PROGRESS',),'RESOLVED'),
           ActionSpec('close','关闭报修',('RESOLVED',),'CLOSED'),
           ActionSpec('reopen','重新打开',('RESOLVED','CLOSED'),'OPEN'))}
NOTICES={'PENDING_APPROVAL':'等待审批，未分配或预留。','RESERVED':'服务台已批准并预留，尚未领用。',
 'CHECKED_OUT':'已登记领用，使用后请归还。','RETURNED':'已归还，日期预留已释放。','CANCELLED':'已取消，未占用日期预留。',
 'REJECTED':'申请已拒绝，未分配设备。','OPEN':'等待服务台受理，尚未解决。','IN_PROGRESS':'服务台处理中，尚未解决。',
 'RESOLVED':'已登记解决，可核对后关闭。','CLOSED':'报修已关闭；没有修改借用资格记录。'}

class Lifecycle:
    def __init__(self,store):self.store=store

    def _enabled(self,actor):
        self.store.authorize(actor)
        if not self.store.writes_enabled:raise ServiceError('TEST_BACKEND_REQUIRED')

    def _ticket(self,db,actor,kind,ticket_id):
        if kind not in SERVICES:raise ServiceError('INVALID_ARGUMENTS')
        row=db.execute(f'SELECT payload FROM {SERVICES[kind].ticket_table} WHERE ticket_id=? AND tenant=? AND owner=?',
            (ticket_id,actor.tenant_id,actor.subject)).fetchone()
        if not row:raise ServiceError('NOT_FOUND')
        return json.loads(row['payload'])

    def list(self,actor):
        self._enabled(actor)
        with self.store.transaction() as db:
            result=[]
            for kind,service in SERVICES.items():
                for row in db.execute(f'SELECT payload FROM {service.ticket_table} WHERE tenant=? AND owner=? ORDER BY rowid DESC',(actor.tenant_id,actor.subject)):
                    ticket=json.loads(row['payload']);result.append(self.view(kind,ticket))
            reservations=[dict(r) for r in db.execute('SELECT * FROM asset_reservations WHERE tenant=?',(actor.tenant_id,))]
        return {'origin':'LOCAL_SYNTHETIC_TEST_ONLY','tickets':result,'reservations':reservations}

    @staticmethod
    def view(kind,ticket):
        return {'kind':kind,'ticket':ticket,'notice':NOTICES.get(ticket['status'],ticket.get('next_step')),
            'actions':[{'name':a.name,'label':a.label} for a in ACTIONS[kind] if ticket['status'] in a.states]}

    def _validate(self,db,actor,content):
        kind=content['kind'];ticket=self._ticket(db,actor,kind,content['ticket_id'])
        if digest(ticket)!=content['ticket_digest']:raise ServiceError('TICKET_CHANGED')
        spec=next((a for a in ACTIONS[kind] if a.name==content['action'] and ticket['status'] in a.states),None)
        if not spec:raise ServiceError('INVALID_TRANSITION')
        if kind=='repair' and spec.name=='reopen':
            if db.execute("SELECT 1 FROM it_repair_tickets WHERE tenant=? AND owner=? AND ticket_id!=? AND json_extract(payload,'$.asset_id')=? AND status IN ('OPEN','IN_PROGRESS','RESOLVED')",
                (actor.tenant_id,actor.subject,ticket['ticket_id'],ticket['asset_id'])).fetchone():raise ServiceError('EXISTING_TICKET')
        if kind=='loan' and spec.name in ('approve','extend'):
            candidate={**ticket,'parameters':content['parameters']}
            scheduling.check_resource(db,actor,ticket['asset_id'],candidate['parameters'],ticket['ticket_id'])
            rule=db.execute('SELECT * FROM loan_rules WHERE tenant=?',(actor.tenant_id,)).fetchone()
            if (not rule or rule['version']!=content['rule_version'] or digest(dict(rule))!=content['rule_digest']):raise ServiceError('POLICY_CHANGED')
            start=date.fromisoformat(ticket['parameters']['loan_start']);end=date.fromisoformat(content['parameters']['loan_end'])
            if not 1<=(end-start).days+1<=rule['max_days']:raise ServiceError('INVALID_EXTENSION')
            if spec.name=='extend' and end<=date.fromisoformat(ticket['parameters']['loan_end']):raise ServiceError('INVALID_EXTENSION')
            if spec.name=='approve':
                eligibility=db.execute('SELECT active FROM repairs WHERE tenant=? AND owner=?',(actor.tenant_id,actor.subject)).fetchone()
                if not eligibility or not eligibility['active']:raise ServiceError('NOT_ELIGIBLE')
        return ticket,spec

    def propose(self,actor,kind,ticket_id,action,expected_version,*,note='',loan_end=None):
        self._enabled(actor)
        with self.store.transaction() as db:
            ticket=self._ticket(db,actor,kind,ticket_id)
            if ticket['version']!=expected_version:raise ServiceError('TICKET_CHANGED')
            if not note.strip():raise ServiceError('ACTION_NOTE_REQUIRED')
            parameters=dict(ticket['parameters'])
            if action=='extend':
                if kind!='loan' or not loan_end:raise ServiceError('INVALID_EXTENSION')
                parameters['loan_end']=loan_end;scheduling.interval(parameters)
            elif loan_end is not None:raise ServiceError('INVALID_ARGUMENTS')
            content={'operation':'lifecycle','kind':kind,'ticket_id':ticket_id,'ticket_digest':digest(ticket),
                'action':action,'parameters':parameters,'note':note,'tenant':actor.tenant_id,'owner':actor.subject,
                'auth_digest':self.store.auth_digest(actor),'expires_at':self.store.clock()+600}
            if kind=='loan' and action in ('approve','extend'):
                rule=dict(db.execute('SELECT * FROM loan_rules WHERE tenant=?',(actor.tenant_id,)).fetchone())
                content.update(rule_version=rule['version'],rule_digest=digest(rule))
            _,spec=self._validate(db,actor,content);content['target_status']=spec.target
            pid=uuid4().hex
            db.execute('INSERT INTO action_proposals VALUES(?,?,?,?,?)',(pid,ticket['task_id'],encoded(content),digest(content),content['expires_at']))
            self.store._event(db,ticket['task_id'],'lifecycle_preview',{'proposal_id':pid,'content':content})
            return {'proposal_id':pid,'content':content,'content_digest':digest(content),'expires_at':content['expires_at']}

    def commit(self,actor,proposal_id,content_digest,accepted):
        self._enabled(actor)
        if accepted is not True:raise ServiceError('CONFIRMATION_REQUIRED')
        command_id='lifecycle:'+proposal_id
        with self.store.transaction() as db:
            row=db.execute('SELECT * FROM action_proposals WHERE proposal_id=?',(proposal_id,)).fetchone()
            if not row:raise ServiceError('NOT_FOUND')
            content=json.loads(row['content'])
            if (content.get('operation')!='lifecycle' or digest(content)!=row['content_digest'] or content_digest!=row['content_digest']):raise ServiceError('PROPOSAL_CHANGED')
            if content['auth_digest']!=self.store.auth_digest(actor):raise ServiceError('AUTH_DENIED')
            self._ticket(db,actor,content['kind'],content['ticket_id'])
            prior=db.execute('SELECT receipt FROM command_ledger WHERE command_id=?',(command_id,)).fetchone()
            if prior:return json.loads(prior['receipt'])
            if self.store.clock()>=content['expires_at']:raise ServiceError('CONFIRMATION_EXPIRED')
            ticket,spec=self._validate(db,actor,content)
            confirmation_id=uuid4().hex
            db.execute('INSERT INTO confirmations VALUES(?,?,?,?,?,?)',(confirmation_id,proposal_id,content_digest,self.store.auth_digest(actor),1,self.store.clock()))
            ticket.update(status=spec.target,version=ticket['version']+1,parameters=content['parameters'],next_step=NOTICES[spec.target])
            if content['kind']=='loan':
                if spec.name in ('approve','extend'):scheduling.reserve(db,actor,ticket)
                elif spec.name in ('return','cancel','withdraw','reject'):
                    db.execute('UPDATE asset_reservations SET active=0 WHERE ticket_id=?',(ticket['ticket_id'],))
            table=SERVICES[content['kind']].ticket_table
            db.execute(f'UPDATE {table} SET status=?,version=?,payload=? WHERE ticket_id=?',(ticket['status'],ticket['version'],encoded(ticket),ticket['ticket_id']))
            receipt={'command_id':command_id,'proposal_id':proposal_id,'content_digest':content_digest,'ticket':ticket,'origin':'LOCAL_SYNTHETIC_TEST_ONLY'}
            db.execute('INSERT INTO command_ledger VALUES(?,?,?)',(command_id,content_digest,encoded(receipt)))
            db.execute('INSERT INTO ticket_events VALUES(?,?,?,?)',(uuid4().hex,ticket['ticket_id'],spec.name,encoded({'note':content['note'],'receipt':receipt,'confirmation_id':confirmation_id})))
            self.store._event(db,ticket['task_id'],'lifecycle_committed',receipt)
            actual=self._ticket(db,actor,content['kind'],ticket['ticket_id'])
            if actual!=ticket:raise ServiceError('READBACK_MISMATCH')
            return receipt
