from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

_RUN_OWNER = ContextVar('service_run_owner',default=None)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


class ServiceError(RuntimeError):
    def __init__(self, code, *, data=None):
        super().__init__(code)
        self.code = code
        self.data = data or {}


class ServiceDeskStore:
    """Task state and business commands share one local SQLite transaction domain."""

    def __init__(self, path: Path, *, writes_enabled=False, clock=time.time, today=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.writes_enabled = writes_enabled
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.clock, self.today = clock, today or (lambda:datetime.now(ZoneInfo('Asia/Shanghai')).date())
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, owner TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, owner TEXT NOT NULL,
                    task_id TEXT NOT NULL, command_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
                    version INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS assets (
                    tenant TEXT NOT NULL, asset_id TEXT NOT NULL, category TEXT NOT NULL,
                    available INTEGER NOT NULL, version INTEGER NOT NULL, PRIMARY KEY(tenant,asset_id));
                CREATE TABLE IF NOT EXISTS repairs (
                    tenant TEXT NOT NULL, owner TEXT NOT NULL, active INTEGER NOT NULL,
                    version INTEGER NOT NULL, PRIMARY KEY(tenant,owner));
                CREATE TABLE IF NOT EXISTS loan_rules (
                    tenant TEXT PRIMARY KEY, version TEXT NOT NULL, content TEXT NOT NULL, max_days INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS rule_sources (
                    tenant TEXT PRIMARY KEY, document_id TEXT NOT NULL, index_run_id TEXT NOT NULL,
                    source_path TEXT NOT NULL, manifest_sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS action_proposals (
                    proposal_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, content TEXT NOT NULL,
                    content_digest TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS confirmations (
                    confirmation_id TEXT PRIMARY KEY, proposal_id TEXT UNIQUE NOT NULL,
                    content_digest TEXT NOT NULL, auth_digest TEXT NOT NULL, accepted INTEGER NOT NULL,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS command_ledger (
                    command_id TEXT PRIMARY KEY, content_digest TEXT NOT NULL, receipt TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ticket_events (
                    event_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_open_loan ON tickets(tenant,owner)
                    WHERE status IN ('PENDING_APPROVAL','IN_PROGRESS');
            ''')
            from app.service_desk.catalog import initialize_tables
            initialize_tables(db)
            from app.service_desk.scheduling import initialize
            initialize(db)

    @staticmethod
    def ticket_table(task):
        # Fixed host registry, never an SQL identifier supplied by the model.
        return 'it_repair_tickets' if task.get('guided_request',{}).get('kind')=='repair' else 'tickets'

    @staticmethod
    def command_id(task,proposal_id):
        return ('repair:' if task.get('guided_request',{}).get('kind')=='repair' else 'loan:')+proposal_id

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except sqlite3.OperationalError as exc:
            db.rollback()
            if 'locked' in str(exc).lower() or 'busy' in str(exc).lower():
                raise ServiceError('TRANSIENT_TOOL_FAILURE') from exc
            raise
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def authorize(self, actor):
        if actor.expires_at.timestamp() <= self.clock() or not {'employees','all_employees'}.intersection(actor.groups):
            raise ServiceError('AUTH_DENIED')

    def _task(self, db, actor, task_id):
        self.authorize(actor)
        row = db.execute('SELECT payload FROM agent_tasks WHERE task_id=? AND tenant=? AND owner=?',
                         (task_id, actor.tenant_id, actor.subject)).fetchone()
        if row is None:
            raise ServiceError('NOT_FOUND')
        task=json.loads(row['payload'])
        scope=self.auth_digest(actor)
        if ((task.get('auth_scope') and task['auth_scope']!=scope)
            or any(e.get('auth_digest') and e['auth_digest']!=scope for e in task.get('knowledge',{}).values())):
            raise ServiceError('AUTH_DENIED')
        if task.get('interaction_mode')=='guided':
            from app.service_desk.goals import user_structured_goal
            if not user_structured_goal(task):raise ServiceError('GUIDED_CONTRACT_CHANGED')
        return task

    def _save(self, db, task):
        task['revision'] += 1
        db.execute('UPDATE agent_tasks SET payload=? WHERE task_id=?', (encoded(task), task['task_id']))

    def _event(self, db, task_id, kind, payload):
        db.execute('INSERT INTO task_events(task_id,kind,payload,created_at) VALUES(?,?,?,?)',
                   (task_id, kind, encoded(payload), self.clock()))

    def _invalidate_derived(self, db, task, reason):
        if task.get('delivery') or task.get('outcome'):
            self._event(db,task['task_id'],'derived_invalidated',{
                'reason':reason,'delivery':task.get('delivery'),'outcome':task.get('outcome')})
        goal_review=None
        from app.service_desk.goals import separate_goal_review
        if separate_goal_review(task):
            from app.service_desk.goals import goal_review_fresh
            current=task.get('goal_coverage') or {}
            if goal_review_fresh(task,current):goal_review=current
        task.update(delivery=None,outcome=None,outcome_binding=None,source_plan=None,coverage_review=None,goal_coverage=goal_review)
        if task.get('status')=='COMPLETED':
            task.update(status='BLOCKED',last_error='GOAL_NOT_COMPLETE')

    def _answer_binding(self, db, actor, task, answers, *, knowledge_only=False):
        # Whole-dependency binding is conservative until per-need dependencies are proven.
        business={}
        for table in ('assets','repairs','tickets','loan_rules','rule_sources'):
            # Policy span proofs cannot cite live tickets. The final publisher still binds them.
            if knowledge_only and table=='tickets': continue
            personal=table in {'repairs','tickets'}
            rows=db.execute('SELECT * FROM '+table+' WHERE tenant=?'+(' AND owner=?' if personal else ''),
                (actor.tenant_id,actor.subject) if personal else (actor.tenant_id,)).fetchall()
            business[table]=sorted((dict(r) for r in rows),key=encoded)
        dependencies={key:task.get(key) for key in ('task_id','task_goal','facts_revision','facts','fact_sources',
            'messages','understanding_pending','knowledge','evidence_order','evidence_aliases','search_receipts',
            'runtime_fingerprint','runtime_index_manifest','runtime_index_version','time_context','ticket_query_receipt',
            'compact_facts_pending','compact_understanding','source_plan','coverage_review','semantic_review_contract',
            'agent_contract','goal_contract','goal_coverage')}
        dependencies['observations']=[o for o in task['observations'] if o['tool']!='host.finish']
        from app.service_desk.delivery import bounded_peer_reports
        reports=bounded_peer_reports(task)
        if reports: dependencies['bounded_peer_reports']=reports
        return {'version':'policy-dependency-v2' if knowledge_only else 'whole-dependency-v1','task_id':task['task_id'],
            'state_sha256':digest(dependencies),'business_sha256':digest(business),
            'auth_digest':self.auth_digest(actor),'candidate_sha256':digest(answers)}

    def _need_binding(self, db, actor, task, answer):
        refs={c['evidence_ref'] for c in answer['citations']}
        scoped={**task,'knowledge':{r:e for r,e in task.get('knowledge',{}).items() if r in refs},
            'evidence_order':[r for r in task.get('evidence_order',[]) if r in refs],
            'evidence_aliases':{a:r for a,r in task.get('evidence_aliases',{}).items() if r in refs},
            'search_receipts':{r:e for r,e in task.get('search_receipts',{}).items()
                               if r in answer.get('search_receipts',[])},
            'observations':[],'ticket_query_receipt':None,'source_plan':None,'coverage_review':None,'goal_coverage':None}
        # New search progress is not a dependency of an already reviewed claim.
        # Goal, facts, actor, runtime, selected source bytes and business versions remain bound.
        scope_absence=(task.get('agent_contract')=='obligation-v1'
            and task.get('routing_contract')=='request-outcomes-visible-v11'
            and answer.get('answer_disposition')=='not_found_in_checked_scope'
            and set(task['task_goal']['required_outputs']).intersection({'asset_status','ticket_status','open_application'}))
        return self._answer_binding(db,actor,scoped,[answer],
            knowledge_only=task.get('semantic_review_contract')=='clauses-disposition-v2' and not scope_absence)

    def _cached_delivery(self, db, actor, task):
        entries=task.get('verified_need_answers',{})
        if not entries: return None
        answers=[entries[n['id']]['answer'] for n in task['task_goal']['needs'] if n['id'] in entries]
        fresh={n for n,e in entries.items() if e.get('review_context')==self._review_context(task,e['answer'])}
        from app.service_desk.delivery import coverage_review_key
        coverage=task.get('coverage_review') or {}
        covered=(coverage.get('binding')==coverage_review_key(task) and coverage.get('complete',False)
            if task.get('semantic_review_contract')=='source-plan-v2' else True)
        if task.get('agent_contract')=='obligation-v1':
            from app.service_desk.goals import goal_mapping_complete
            covered=goal_mapping_complete(task)
        assessment={'faithful_to_source':len(fresh)==len(entries),'covers_user_needs':covered,
            'preserves_numbers_entities_negation_conditions':len(fresh)==len(entries),'unsupported_need_ids':[],
            'reason':'Retained individually validated and provisionally reviewed needs.',
            'need_assessments':[{'need_id':a['need_id'],'verdict':'supported' if a['need_id'] in fresh else 'review_uncertain',
                'reason':entries[a['need_id']]['reason'] if a['need_id'] in fresh else 'New admitted sources/search scope require reassessment; answer bytes retained.'}
                                for a in answers],
            'need_reviews':[entries[a['need_id']]['review'] for a in answers if a['need_id'] in fresh and entries[a['need_id']].get('review')]}
        return {'answers':answers,'assessment':assessment,'host_validated':True,'host_rejections':[],
            'semantic_review':'MODEL_PROVISIONAL_HUMAN_UNREVIEWED',
            'binding':self._answer_binding(db,actor,task,answers)}

    @staticmethod
    def _review_context(task, answer=None):
        if task.get('agent_contract')=='obligation-v1':
            # Ref aliases, ranks and repeated query IDs do not change source assertions.
            fields=('document_id','chunk_id','text','version_id','index_run_id','source_path',
                    'auth_digest','read_target_type','read_target_id','invalidated_by')
            sources=sorted({encoded({k:e.get(k) for k in fields})
                for e in task.get('knowledge',{}).values()})
            negative=not answer or answer.get('answer_disposition') in {
                'not_found_in_checked_scope','conflict','need_user_fact'}
            scope=None
            if (answer and answer.get('answer_disposition')=='not_found_in_checked_scope'
                and task.get('routing_contract')=='request-outcomes-visible-v11'):
                from app.service_desk.goals import model_business_review_context
                scope=model_business_review_context(task)
            context={'sources':sources,'search_receipts':task.get('search_receipts') if negative else None}
            if scope is not None:context['business_scope_counterevidence']=scope
            return digest(context)
        return digest({k:task.get(k) for k in ('knowledge','evidence_order','evidence_aliases','search_receipts','source_plan')})

    def create_task(self, actor, goal, *, facts=None, goal_kind='submit_loan', ticket_ref=None, execution_ceiling=None, guided_request=None):
        self.authorize(actor)
        guided=None
        if guided_request is not None:
            from app.service_desk.contracts import GuidedTaskRequest
            guided=GuidedTaskRequest.model_validate(guided_request).model_dump(mode='json',exclude_none=True)
            from app.service_desk.catalog import SERVICES
            goal=guided.get('question') or SERVICES[guided['kind']].goal
            facts=guided.get('facts',{});goal_kind='auto';ticket_ref=None
            execution_ceiling=guided['execution_ceiling']
        if not isinstance(goal,str) or not goal.strip() or len(goal) > 2000 or goal_kind not in {'submit_loan','track_approval','inspect','inspect_policy','inspect_ticket_status','auto'}:
            raise ServiceError('INVALID_ARGUMENTS')
        from app.service_desk.contracts import UserFacts, facts_from_goal
        form_facts = dict(facts or {})
        from app.service_desk.contracts import RepairFacts
        fact_type=RepairFacts if guided and guided['kind']=='repair' else UserFacts
        facts = fact_type.model_validate(form_facts if goal_kind=='auto' else facts_from_goal(goal,form_facts,self.today())).model_dump(mode='json',exclude_none=True)
        from app.service_desk.goals import task_goal
        bound_goal=task_goal(goal,goal_kind,ticket_ref)
        from app.service_desk.goals import CEILING_ORDER
        if execution_ceiling is not None and execution_ceiling not in CEILING_ORDER:
            raise ServiceError('INVALID_ARGUMENTS')
        task = {'task_id':uuid4().hex, 'tenant':actor.tenant_id, 'owner':actor.subject,
                'auth_scope':self.auth_digest(actor),
                'goal':goal, 'goal_kind':goal_kind, 'status':'NEW', 'revision':1,
                'facts':facts, 'facts_revision':1, 'observations':[], 'pending_proposal_id':None, 'receipt':None,
                'active_run_id':None, 'model_calls':0, 'tool_calls':0, 'last_error':None}
        if execution_ceiling is not None: task['user_execution_ceiling']=execution_ceiling
        task.update(task_goal=bound_goal,outcome=None,time_context={'reference_date':self.today().isoformat(),'timezone':'Asia/Shanghai'},
            messages=[{'id':'initial','text':goal}],fact_sources={k:{'source_message_id':'initial','text':goal,
            'start':0,'end':len(goal),'origin':'USER_FORM' if k in form_facts else 'LEGACY_TEXT'} for k in facts},
            understanding_pending=goal_kind in {'auto','inspect_policy','inspect'},delivery=None)
        if guided is not None:
            task.update(interaction_mode='guided',guided_request=guided,structured_event_id=uuid4().hex)
            self._refresh_guided(task)
        with self.transaction() as db:
            db.execute('INSERT INTO agent_tasks VALUES(?,?,?,?)',
                       (task['task_id'],actor.tenant_id,actor.subject,encoded(task)))
            self._event(db, task['task_id'], 'created', {'goal':goal, 'goal_kind':goal_kind})
            if guided is not None:self._event(db,task['task_id'],'user_structured_task',{
                'event_id':task['structured_event_id'],'actor':actor.subject,'tenant':actor.tenant_id,
                'auth_scope':task['auth_scope'],'request':guided,'contract_sha256':task['goal_contract']['sha256'],
                'authority':'USER_CONFIRMED_STRUCTURED_NOT_SUBMISSION_CONSENT'})
        return task

    @staticmethod
    def _refresh_guided(task):
        from app.service_desk.goals import structured_goal_fields
        goal,contract,request=structured_goal_fields(task)
        task.update(task_goal=goal,goal_contract=contract,user_execution_ceiling=request['execution_ceiling'],
            understanding_pending=False,compact_facts_pending=False,goal_coverage=None,goal_kind='guided')
        task['fact_sources']={k:{'origin':'USER_CONFIRMED_STRUCTURED','form_event_id':task.get('guided_field_events',{}).get(k,task['structured_event_id']),
            'field':'facts.'+k,'value':v} for k,v in task['facts'].items()}

    def seed_demo(self, actor):
        """Explicit synthetic setup only; no automatic seed on API requests."""
        self.authorize(actor)
        content = ('Employees with an active repair may request a temporary laptop for 1 to 14 days. '
                   'The start date must not be in the past. Available stock does not reserve a device. '
                   'An employee may have one open loan request. Submission creates PENDING_APPROVAL; '
                   'approval and allocation require the service desk and are not performed by this Agent.')
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO loan_rules VALUES(?,?,?,?)',
                       (actor.tenant_id,'loan-policy-v1',content,14))
            db.execute('INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?)',
                       (actor.tenant_id,'loan-laptop-1','laptop',1,1))
            db.execute('INSERT OR IGNORE INTO repairs VALUES(?,?,?,?)',
                       (actor.tenant_id,actor.subject,1,1))

    def change_execution_scope(self, actor, task_id, ceiling, revoked_constraints, source_message_id, text, *, scope_confirmed=False, expected_facts_revision=None):
        """Authenticated explicit scope change; never invoked by the model registry."""
        from app.service_desk.goals import CEILING_ORDER
        if ceiling not in CEILING_ORDER or not text.strip() or len(text)>2000:
            raise ServiceError('INVALID_ARGUMENTS')
        with self.transaction() as db:
            task=self._task(db,actor,task_id);self._live(task)
            if expected_facts_revision is not None and task['facts_revision']!=expected_facts_revision:
                raise ServiceError('TASK_CHANGED')
            if (task.get('receipt') or task.get('active_run_id') or task['status']=='RECONCILING'
                or db.execute(f'SELECT 1 FROM {self.ticket_table(task)} WHERE task_id=?',(task_id,)).fetchone()):
                raise ServiceError('TASK_BUSY_OR_COMMITTED')
            if task.get('interaction_mode')=='guided':
                if scope_confirmed is not True:raise ServiceError('GUIDED_SCOPE_CONFIRMATION_REQUIRED')
                old=task['user_execution_ceiling']
                required={digest(c) for c in task['task_goal']['constraint_sources']}
                raising=CEILING_ORDER.index(ceiling)>CEILING_ORDER.index(old)
                if set(revoked_constraints)!=(required if raising else set()):
                    raise ServiceError('EXPLICIT_CONSTRAINT_REVOCATION_REQUIRED')
                if source_message_id in {m['id'] for m in task['messages']}:raise ServiceError('MESSAGE_ID_CONFLICT')
                task.setdefault('constraint_history',[]).append({'sources':task['task_goal']['constraint_sources'],
                    'revoked_ids':revoked_constraints,'previous_ceiling':old})
                task['guided_request']['execution_ceiling']=ceiling
                task['structured_scope_event_id']=source_message_id
                self._refresh_guided(task)
                task['messages'].append({'id':source_message_id,'text':text,'origin':'USER_CONFIRMED_STRUCTURED'})
                task['facts_revision']+=1
                self._invalidate_derived(db,task,'explicit_user_scope_changed')
                task.update(pending_proposal_id=None,status='NEW',last_error=None)
                self._save(db,task)
                self._event(db,task_id,'user_execution_scope_changed',{'origin':'USER_CONFIRMED_STRUCTURED',
                    'previous_ceiling':old,'ceiling':ceiling,'revoked_constraint_ids':revoked_constraints,
                    'source_message_id':source_message_id,'text':text,'requires_new_preview_and_confirmation':True})
                return task
            sources=task['task_goal'].get('constraint_sources',[])
            blocked=[c for c in sources if c.get('operation')=='submit' or c.get('execution_ceiling')=='PREVIEW_ONLY']
            if ceiling=='SUBMIT_AFTER_CONFIRMATION':
                required={digest(c) for c in blocked}
                if set(revoked_constraints)!=required or ('submit' in task['task_goal']['forbidden_operations'] and not required):
                    raise ServiceError('EXPLICIT_CONSTRAINT_REVOCATION_REQUIRED')
                task['task_goal']['forbidden_operations']=[o for o in task['task_goal']['forbidden_operations'] if o!='submit']
            elif revoked_constraints: raise ServiceError('INVALID_ARGUMENTS')
            if source_message_id in {m['id'] for m in task['messages']}:raise ServiceError('MESSAGE_ID_CONFLICT')
            task.setdefault('constraint_history',[]).append({'sources':sources,'revoked_ids':revoked_constraints})
            task['revoked_constraint_ids']=list(dict.fromkeys(task.get('revoked_constraint_ids',[])+revoked_constraints))
            task['task_goal']['constraint_sources']=[c for c in sources if digest(c) not in revoked_constraints]
            task['messages'].append({'id':source_message_id,'text':text})
            task['user_execution_ceiling']=ceiling;task['task_goal']['execution_ceiling']=ceiling
            task['facts_revision']+=1
            self._invalidate_derived(db,task,'explicit_user_scope_changed')
            task.update(pending_proposal_id=None,understanding_pending=True,status='NEW',outcome=None)
            self._event(db,task_id,'user_execution_scope_changed',{'ceiling':ceiling,
                'revoked_constraint_ids':revoked_constraints,'source_message_id':source_message_id,'text':text,
                'requires_new_preview_and_confirmation':True})
            self._save(db,task)
            return task

    def rule(self, actor):
        self.authorize(actor)
        with self.transaction() as db:
            row = db.execute('SELECT * FROM loan_rules WHERE tenant=?',(actor.tenant_id,)).fetchone()
            if row is None:
                raise ServiceError('POLICY_NOT_CONFIGURED')
            return dict(row)

    def bind_rule_index(self, actor, snapshot):
        rule=self.rule(actor)
        matches=[d for d in snapshot.documents_by_id.values() if d.tenant_id==actor.tenant_id
                 and d.document_version.version_id==rule['version'] and d.document_version.status=='active']
        if len(matches)!=1: raise ServiceError('POLICY_SOURCE_AMBIGUOUS')
        doc=matches[0]
        if not any(c.doc_id==doc.doc_id and c.text==rule['content'] for c in snapshot.all_chunks_by_id.values()):
            raise ServiceError('FULL_POLICY_NOT_MATERIALIZED')
        with self.transaction() as db:
            binding=(actor.tenant_id,doc.doc_id,snapshot.version.manifest.run_id,
                     doc.source_path,snapshot.version.manifest_sha256)
            existing=db.execute('SELECT * FROM rule_sources WHERE tenant=?',(actor.tenant_id,)).fetchone()
            if existing:
                if tuple(existing)!=binding:raise ServiceError('INDEX_IDENTITY_CHANGED')
                return
            db.execute('INSERT INTO rule_sources VALUES(?,?,?,?,?)',binding)

    def source_binding(self, actor):
        self.authorize(actor)
        with self.transaction() as db:
            row=db.execute('SELECT * FROM rule_sources WHERE tenant=?',(actor.tenant_id,)).fetchone()
            return dict(row) if row else None

    def assets(self, actor, facts=None):
        self.authorize(actor)
        with self.transaction() as db:
            from app.service_desk.scheduling import inventory
            rows=inventory(db,actor,facts)
            repair = db.execute('SELECT active,version FROM repairs WHERE tenant=? AND owner=?',
                                (actor.tenant_id,actor.subject)).fetchone()
            return {'assets':rows, 'repair':dict(repair) if repair else None}

    def list_tickets(self, actor,kind='loan'):
        from app.service_desk.catalog import SERVICES
        if kind not in SERVICES:raise ServiceError('INVALID_ARGUMENTS')
        self.authorize(actor)
        with self.transaction() as db:
            return [json.loads(r['payload']) for r in db.execute(
                f'SELECT payload FROM {SERVICES[kind].ticket_table} WHERE tenant=? AND owner=? ORDER BY ticket_id',
                (actor.tenant_id,actor.subject))]

    def get_ticket(self, actor, ticket_id,kind='loan'):
        from app.service_desk.catalog import SERVICES
        if kind not in SERVICES:raise ServiceError('INVALID_ARGUMENTS')
        self.authorize(actor)
        with self.transaction() as db:
            row = db.execute(f'SELECT payload FROM {SERVICES[kind].ticket_table} WHERE tenant=? AND owner=? AND ticket_id=?',
                             (actor.tenant_id,actor.subject,ticket_id)).fetchone()
            if row is None:
                raise ServiceError('NOT_FOUND')
            return json.loads(row['payload'])

    @staticmethod
    def auth_digest(actor):
        return digest({'tenant':actor.tenant_id, 'owner':actor.subject, 'groups':sorted(actor.groups),
                       'roles':sorted(actor.roles), 'issuer':actor.issuer, 'audience':actor.audience})

    def remember_knowledge(self, actor, task_id, evidence):
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            self._live(task)
            if any(e.get('knowledge_peer') is not None and (
                e['knowledge_peer']!=task.get('knowledge_peer')
                or e.get('index_manifest')!=e['knowledge_peer'].get('index_fingerprint')) for e in evidence):
                raise ServiceError('INDEX_IDENTITY_CHANGED')
            previous=task.setdefault('knowledge',{})
            before=digest(previous)
            order=task.setdefault('evidence_order',list(previous))
            aliases=task.setdefault('evidence_aliases',{'E'+str(i+1):ref for i,ref in enumerate(order)})
            for e in evidence:
                for old in previous.values():
                    if old['document_id']==e['document_id'] and old['version_id']!=e['version_id']:
                        old['invalidated_by']=e['ref']
            previous.update({e['ref']:e for e in evidence})
            for e in evidence:
                if e['ref'] not in order:
                    order.append(e['ref'])
                    next_alias=max((int(a[1:]) for a in aliases),default=0)+1
                    aliases['E'+str(next_alias)]=e['ref']
            if digest(previous)!=before: self._invalidate_derived(db,task,'knowledge_changed')
            self._save(db,task)
            self._event(db,task_id,'knowledge_admitted',{'evidence':evidence})

    @staticmethod
    def _live(task):
        if task['status'] == 'CANCELLED':
            raise ServiceError('CANCELLED')
        owner=_RUN_OWNER.get()
        if owner and owner[0]==task['task_id'] and (owner[1]!=task.get('active_run_id') or owner[2]!=task.get('run_fence')):
            raise ServiceError('STALE_RUN')

    @contextmanager
    def run_scope(self, task):
        token=_RUN_OWNER.set((task['task_id'],task['active_run_id'],task['run_fence']))
        try:yield
        finally:_RUN_OWNER.reset(token)

    @staticmethod
    def owns_run(task):
        return _RUN_OWNER.get()==(task['task_id'],task.get('active_run_id'),task.get('run_fence'))

    def remember_search(self,actor,task_id,receipt):
        with self.transaction() as db:
            task=self._task(db,actor,task_id); self._live(task)
            receipts=task.setdefault('search_receipts',{})
            key='Q'+str(len(receipts)+1)
            receipts[key]={**receipt,'task_id':task_id,'auth_digest':self.auth_digest(actor)}
            self._invalidate_derived(db,task,'search_changed')
            self._save(db,task); self._event(db,task_id,'search_receipt',{'ref':key,**receipts[key]})
            return key

    def _validate_business(self, db, actor, task, asset_id, evidence_refs):
        facts = task['facts']
        missing = [k for k in ('loan_start','loan_end','purpose') if not facts.get(k)]
        if missing:
            raise ServiceError('NEED_USER_FACT',data={'missing_fields':missing})
        try:
            start,end = date.fromisoformat(facts['loan_start']),date.fromisoformat(facts['loan_end'])
        except (ValueError,TypeError):
            raise ServiceError('INVALID_ARGUMENTS') from None
        rule = db.execute('SELECT * FROM loan_rules WHERE tenant=?',(actor.tenant_id,)).fetchone()
        if rule is None:
            raise ServiceError('POLICY_NOT_CONFIGURED')
        if start < self.today() or not 1 <= (end-start).days+1 <= rule['max_days']:
            raise ServiceError('INVALID_ARGUMENTS')
        asset = db.execute('SELECT * FROM assets WHERE tenant=? AND asset_id=? AND available=1',
                           (actor.tenant_id,asset_id)).fetchone()
        if asset is None or asset['category'] != 'laptop':
            raise ServiceError('RESOURCE_CHANGED')
        from app.service_desk.scheduling import check_resource
        check_resource(db,actor,asset_id,facts)
        repair = db.execute('SELECT * FROM repairs WHERE tenant=? AND owner=?',
                            (actor.tenant_id,actor.subject)).fetchone()
        if repair is None or not repair['active']:
            raise ServiceError('NOT_ELIGIBLE')
        existing = db.execute("SELECT ticket_id,payload FROM tickets WHERE tenant=? AND owner=? AND status IN ('PENDING_APPROVAL','IN_PROGRESS','RESERVED','CHECKED_OUT')",
                              (actor.tenant_id,actor.subject)).fetchone()
        if existing:
            ticket=json.loads(existing['payload'])
            from app.service_desk.contracts import parameter_differences
            matching=(ticket['parameters'].get('loan_end','')>=self.today().isoformat()
                and not parameter_differences(ticket['parameters'],facts,task.get('parameter_normalizer','literal-v1')))
            raise ServiceError('EXISTING_TICKET',data={'ticket_id':existing['ticket_id'],'ticket':ticket,
                'matches_requested_facts':matching,'next_actions':['tickets.get'],
                'message':'Read this owned open ticket. Reuse only when all requested fields match; otherwise report the conflict. Do not repeat proposal creation.'})
        evidence = task.get('knowledge',{})
        bound = [evidence[r] for r in evidence_refs if r in evidence
                 and evidence[r]['version_id'] == rule['version']
                 and evidence[r]['text'] == rule['content']
                 and evidence[r]['need_refs'] == ['loan_policy']]
        if not bound:
            raise ServiceError('EVIDENCE_INSUFFICIENT')
        return dict(rule),dict(asset),dict(repair),bound

    def propose(self, actor, task_id, asset_id, evidence_refs, *, _record_tool_result=False):
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            self._live(task)
            if task.get('pending_user_update') and not self.owns_run(task):raise ServiceError('USER_UPDATE_PENDING')
            if self._proposal_declined(db,actor,task):raise ServiceError('USER_DECLINED')
            if task.get('understanding_pending'):
                raise ServiceError('NO_WRITE_GOAL')
            from app.service_desk.goals import execution_ceiling, execution_binding
            from app.service_desk.catalog import service_for
            service=service_for(task)
            ceiling=execution_ceiling(task)
            if ceiling=='READ_ONLY': raise ServiceError('EXECUTION_CEILING')
            if task.get('independent_goal_review') or task.get('semantic_review_contract')=='clauses-disposition-v2':
                from app.service_desk.goals import goal_mapping_complete
                if not goal_mapping_complete(task):
                    raise ServiceError('ORIGINAL_GOAL_NOT_VERIFIED')
            if db.execute(f'SELECT 1 FROM {service.ticket_table} WHERE task_id=?',(task_id,)).fetchone():
                raise ServiceError('ALREADY_SUBMITTED')
            if task['task_goal']['goal_subject'] != 'submit_'+service.key and task['goal_kind'] != 'track_approval':
                raise ServiceError('NO_WRITE_GOAL')
            from app.service_desk.contracts import proposal_requires_owned_query
            if proposal_requires_owned_query(task) and self._current_ticket_query(db,actor,task) is None:
                raise ServiceError('REQUESTED_QUERY_REQUIRED')
            from app.service_desk.contracts import evaluate_owned_condition
            for unit in task['task_goal'].get('request_units',[]):
                condition=unit.get('execution_condition')
                if unit['intent']!='execute' or not condition:continue
                value=evaluate_owned_condition(task,condition,self._current_ticket_query(db,actor,task))
                if value['value']=='UNKNOWN':
                    raise ServiceError('REQUESTED_QUERY_REQUIRED',data={'condition':value})
                if value['value']=='FALSE':
                    raise ServiceError('CONDITION_NOT_SATISFIED',data={'condition':value,
                        'next_actions':['tickets.get'],'message':'Read the matching owned record; do not create another application.'})
            rule,asset,repair,evidence = service.validate(self,db,actor,task,asset_id,evidence_refs)
            if task.get('pending_proposal_id'):
                try:
                    previous, previous_content = self._bound_proposal(db,actor,task,task['pending_proposal_id'])
                    self._check_preview_dependencies(db,actor,previous_content)
                    if previous_content['target']==asset_id and previous_content['evidence_refs']==[e['ref'] for e in evidence]:
                        return {'proposal_id':previous['proposal_id'],'content':previous_content,
                                'content_digest':previous['content_digest'],'expires_at':previous['expires_at']}
                except ServiceError:
                    pass
            proposal_id = uuid4().hex
            expires_at = self.clock()+600
            content = {'task_id':task_id, 'task_revision':task['facts_revision'], 'tenant':actor.tenant_id,
                       'owner':actor.subject, 'operation':service.operation, 'target':asset_id,
                       'parameters':task['facts'], **service.bindings(rule,asset,repair), 'rule_version':rule['version'],
                       'rule_digest':digest(rule), 'auth_digest':self.auth_digest(actor), 'expires_at':expires_at,
                       'evidence_refs':[e['ref'] for e in evidence], 'ticket_status':service.ticket_status,
                       'notice':service.next_step}
            content.update(execution_ceiling=ceiling, execution_binding=execution_binding(task))
            if ceiling=='PREVIEW_ONLY':
                content['notice']='Preview only. This proposal cannot be confirmed or submitted.'
            if task.get('parameter_normalizer','literal-v1')!='literal-v1':
                content['parameter_normalizer']=task['parameter_normalizer']
            proposal = {'proposal_id':proposal_id, 'content':content, 'content_digest':digest(content),
                        'expires_at':expires_at}
            db.execute('INSERT INTO action_proposals VALUES(?,?,?,?,?)',
                       (proposal_id,task_id,encoded(content),proposal['content_digest'],proposal['expires_at']))
            task.update(pending_proposal_id=proposal_id,
                status='PREVIEW_READY' if ceiling=='PREVIEW_ONLY' else 'WAITING_CONFIRMATION',
                active_run_id=task.get('active_run_id') if ceiling=='PREVIEW_ONLY' or
                    (task.get('pending_user_update') and self.owns_run(task)) else None)
            self._event(db,task_id,'proposal_created',proposal)
            if _record_tool_result:
                # Persist the fenced action result before its terminal transition leaves this transaction.
                self._observe_result(db,actor,task,'tickets.propose_create',
                    {'status':'ok','data':proposal,'retryable':False})
            else:
                self._save(db,task)
            return proposal

    def proposal(self, actor, task_id):
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            row = db.execute('SELECT * FROM action_proposals WHERE proposal_id=?',
                             (task['pending_proposal_id'],)).fetchone()
            if row is None:
                raise ServiceError('NOT_FOUND')
            return {**dict(row),'content':json.loads(row['content'])}

    def _bound_proposal(self, db, actor, task, proposal_id, *, enforce_current=True):
        row = db.execute('SELECT * FROM action_proposals WHERE proposal_id=? AND task_id=?',
                         (proposal_id,task['task_id'])).fetchone()
        if row is None:
            raise ServiceError('NOT_FOUND')
        content = json.loads(row['content'])
        if digest(content) != row['content_digest']:
            raise ServiceError('PROPOSAL_CHANGED')
        from app.service_desk.catalog import service_for
        if content['operation']!=service_for(task).operation:raise ServiceError('PROPOSAL_CHANGED')
        if enforce_current:
            from app.service_desk.goals import execution_binding
            if content.get('execution_binding') != execution_binding(task):
                raise ServiceError('PROPOSAL_CHANGED')
            if (task['pending_proposal_id'] != proposal_id or task['facts_revision'] != content['task_revision']
                    or task['facts'] != content['parameters']
                    or task.get('parameter_normalizer','literal-v1')!=content.get('parameter_normalizer','literal-v1')):
                raise ServiceError('PROPOSAL_CHANGED')
            if self.clock() >= row['expires_at']:
                raise ServiceError('CONFIRMATION_EXPIRED')
            if self.auth_digest(actor) != content['auth_digest']:
                raise ServiceError('AUTH_DENIED')
        return row,content

    def confirm(self, actor, task_id, proposal_id, content_digest, accepted):
        try:
            return self._confirm_bound(actor,task_id,proposal_id,content_digest,accepted)
        except ServiceError as exc:
            self._invalidate_preview(actor,task_id,proposal_id,exc.code)
            raise

    def _check_preview_dependencies(self, db, actor, content):
        from app.service_desk.catalog import by_operation
        return by_operation(content['operation']).check_preview(self,db,actor,content)

    def _check_loan_dependencies(self, db, actor, content):
        from app.service_desk.scheduling import check_resource
        check_resource(db,actor,content['target'],content['parameters'])
        rule=db.execute('SELECT * FROM loan_rules WHERE tenant=?',(actor.tenant_id,)).fetchone()
        if rule is None or digest(dict(rule))!=content['rule_digest']:
            raise ServiceError('POLICY_CHANGED')
        asset=db.execute('SELECT * FROM assets WHERE tenant=? AND asset_id=?',
            (actor.tenant_id,content['target'])).fetchone()
        repair=db.execute('SELECT * FROM repairs WHERE tenant=? AND owner=?',
            (actor.tenant_id,actor.subject)).fetchone()
        if (asset is None or not asset['available'] or asset['category']!='laptop'
            or asset['version']!=content['asset_version'] or repair is None
            or not repair['active'] or repair['version']!=content['repair_version']):
            raise ServiceError('RESOURCE_CHANGED')

    def _invalidate_preview(self, actor, task_id, proposal_id, code):
        if code not in {'RESOURCE_CHANGED','POLICY_CHANGED','CONFIRMATION_EXPIRED'}:return
        with self.transaction() as db:
            task=self._task(db,actor,task_id)
            if (not task['receipt'] and task['status']!='CANCELLED'
                and task['pending_proposal_id']==proposal_id):
                task.update(status='BLOCKED',active_run_id=None,pending_proposal_id=None,last_error=code)
                task['outcome']={'outcome_kind':'resource_changed','goal_satisfied':False,
                    'answer':'原预览依赖的资源、制度或有效期已变化；没有提交工单，旧确认已失效。',
                    'next_step':'重新查询当前资源并生成新预览，再由用户确认。','missing_user_facts':[]}
                self._save(db,task);self._event(db,task_id,'proposal_invalidated',{'proposal_id':proposal_id,'reason':code})

    def _confirm_bound(self, actor, task_id, proposal_id, content_digest, accepted):
        if type(accepted) is not bool:
            raise ServiceError('INVALID_ARGUMENTS')
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            self._live(task)
            if task.get('pending_user_update') and not self.owns_run(task):raise ServiceError('USER_UPDATE_PENDING')
            from app.service_desk.goals import execution_ceiling
            if execution_ceiling(task)!='SUBMIT_AFTER_CONFIRMATION':
                raise ServiceError('EXECUTION_CEILING')
            row,content = self._bound_proposal(db,actor,task,proposal_id)
            if content.get('execution_ceiling')!='SUBMIT_AFTER_CONFIRMATION':
                raise ServiceError('EXECUTION_CEILING')
            if content_digest != row['content_digest']:
                raise ServiceError('PROPOSAL_CHANGED')
            if accepted and not task['receipt']:
                self._check_preview_dependencies(db,actor,content)
            existing = db.execute('SELECT * FROM confirmations WHERE proposal_id=?',(proposal_id,)).fetchone()
            if existing:
                if bool(existing['accepted']) != accepted:
                    raise ServiceError('CONFIRMATION_CHANGED')
                return dict(existing)
            confirmation = {'confirmation_id':uuid4().hex,'proposal_id':proposal_id,
                'content_digest':content_digest,'auth_digest':self.auth_digest(actor),
                'accepted':int(accepted),'created_at':self.clock()}
            db.execute('INSERT INTO confirmations VALUES(?,?,?,?,?,?)',tuple(confirmation.values()))
            self._event(db,task_id,'user_confirmation',confirmation)
            if not accepted:
                task.update(status='BLOCKED',last_error='USER_DECLINED',outcome=None)
                self._save(db,task)
        if not accepted:
            self.finish_goal(actor,task_id)
        return confirmation

    def submit(self, actor, task_id, proposal_id, *, fault=None):
        try:
            return self._submit_bound(actor,task_id,proposal_id,fault=fault)
        except ServiceError as exc:
            self._invalidate_preview(actor,task_id,proposal_id,exc.code)
            raise

    def _submit_bound(self, actor, task_id, proposal_id, *, fault=None):
        if not self.writes_enabled:
            raise ServiceError('WRITES_DISABLED')
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            from app.service_desk.catalog import service_for
            service=service_for(task);command_id=self.command_id(task,proposal_id)
            self._live(task)
            row,content = self._bound_proposal(db,actor,task,proposal_id,enforce_current=False)
            from app.service_desk.goals import execution_ceiling
            if (execution_ceiling(task)!='SUBMIT_AFTER_CONFIRMATION'
                or content.get('execution_ceiling')!='SUBMIT_AFTER_CONFIRMATION'):
                raise ServiceError('EXECUTION_CEILING')
            committed = db.execute('SELECT * FROM command_ledger WHERE command_id=?',(command_id,)).fetchone()
            if committed:
                if committed['content_digest'] != row['content_digest']:
                    raise ServiceError('COMMAND_CONFLICT')
                return json.loads(committed['receipt'])
            if task.get('pending_user_update') and not self.owns_run(task):raise ServiceError('USER_UPDATE_PENDING')
            if db.execute(f'SELECT 1 FROM {service.ticket_table} WHERE task_id=?',(task_id,)).fetchone():
                raise ServiceError('ALREADY_SUBMITTED')
            self._bound_proposal(db,actor,task,proposal_id)
            confirmation = db.execute('SELECT * FROM confirmations WHERE proposal_id=?',(proposal_id,)).fetchone()
            if (confirmation is None or not confirmation['accepted']
                    or confirmation['content_digest'] != row['content_digest']
                    or confirmation['auth_digest'] != self.auth_digest(actor)):
                raise ServiceError('CONFIRMATION_REQUIRED')
            self._check_preview_dependencies(db,actor,content)
            rule,asset,repair,_ = service.validate(self,db,actor,task,content['target'],content['evidence_refs'])
            if any(content.get(k)!=v for k,v in service.bindings(rule,asset,repair).items()):
                raise ServiceError('RESOURCE_CHANGED')
            ticket = {'ticket_id':uuid4().hex,'tenant':actor.tenant_id,'owner':actor.subject,
                'task_id':task_id,'command_id':command_id,'status':service.ticket_status,'version':1,
                'asset_id':content['target'],'parameters':content['parameters'],
                'rule_version':content['rule_version'],
                'next_step':service.next_step}
            receipt = {'command_id':command_id,'proposal_id':proposal_id,'ticket_id':ticket['ticket_id'],
                       'content_digest':row['content_digest'],'ticket':ticket}
            db.execute(f'INSERT INTO {service.ticket_table} VALUES(?,?,?,?,?,?,?,?)',
                       (ticket['ticket_id'],actor.tenant_id,actor.subject,task_id,command_id,
                        ticket['status'],1,encoded(ticket)))
            db.execute('INSERT INTO command_ledger VALUES(?,?,?)',(command_id,row['content_digest'],encoded(receipt)))
            db.execute('INSERT INTO ticket_events VALUES(?,?,?,?)',
                       (uuid4().hex,ticket['ticket_id'],'submitted',encoded({'confirmation_id':confirmation['confirmation_id'],
                                                                               'command_id':command_id})))
            task.update(status='RECONCILING',active_run_id=None)
            self._save(db,task)
            self._event(db,task_id,'business_committed',receipt)
            if fault: fault('before_commit')
        if fault: fault('after_commit')
        return receipt

    def readback(self, actor, task_id, proposal_id):
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            self._bound_proposal(db,actor,task,proposal_id,enforce_current=False)
            row = db.execute('SELECT receipt FROM command_ledger WHERE command_id=?',(self.command_id(task,proposal_id),)).fetchone()
            if row is None:
                raise ServiceError('COMMAND_NOT_COMMITTED')
            receipt = json.loads(row['receipt'])
            ticket = db.execute(f'SELECT payload FROM {self.ticket_table(task)} WHERE ticket_id=? AND tenant=? AND owner=?',
                                (receipt['ticket_id'],actor.tenant_id,actor.subject)).fetchone()
            current=json.loads(ticket['payload']) if ticket else {}
            snapshot=receipt['ticket']
            if (not current or any(current.get(k)!=snapshot.get(k) for k in
                    ('ticket_id','tenant','owner','task_id','command_id','asset_id')) or current.get('version',0)<snapshot['version']):
                raise ServiceError('READBACK_MISMATCH')
            if task.get('receipt'):
                self._event(db,task_id,'receipt_reloaded',{'submission_receipt':receipt,'current_ticket':current})
                return receipt
            # Readback proves the command, not every original user obligation.
            task.update(receipt=receipt,status='BLOCKED',active_run_id=None,last_error='GOAL_NOT_COMPLETE',
                        outcome=None,outcome_binding=None)
            self._save(db,task)
            self._event(db,task_id,'receipt_read_back',receipt)
        self.finish_goal(actor,task_id)
        return receipt

    def get_task(self, actor, task_id):
        with self.transaction() as db:
            task=self._task(db, actor, task_id)
            entries=task.get('verified_need_answers',{})
            kept={n:e for n,e in entries.items() if e['binding']==self._need_binding(db,actor,task,e['answer'])}
            cache_changed=kept!=entries
            if cache_changed and task.get('agent_contract')=='obligation-v1':
                drafts=task.setdefault('invalidated_need_drafts',{})
                for nid,entry in entries.items():
                    if nid in kept:continue
                    key=digest({'answer':entry['answer'],'binding':entry['binding']})
                    if key not in drafts:
                        drafts[key]={'answer':entry['answer'],'prior_binding':entry['binding'],
                            'prior_review':entry.get('review'),'trust':'STALE_DRAFT_REQUIRES_FULL_REVALIDATION'}
                        self._event(db,task_id,'need_draft_invalidated',{'draft_key':key,'need_id':nid,
                            'trust':drafts[key]['trust'],'prior_binding':entry['binding']})
            if entries: task['verified_need_answers']=kept
            delivery=task.get('delivery')
            binding=delivery.get('binding') if delivery else task.get('outcome_binding')
            if binding and binding!=self._answer_binding(db,actor,task,delivery['answers'] if delivery else []):
                self._invalidate_derived(db,task,'dependencies_changed')
                if not task['active_run_id'] and not task['receipt'] and task['status']!='CANCELLED':
                    task.update(status='NEW',last_error='RESOURCE_CHANGED')
                self._save(db,task)
            if not task.get('delivery') and kept:
                task['delivery']=self._cached_delivery(db,actor,task)
                self._save(db,task)
            elif cache_changed:
                self._save(db,task)
            return task

    def get_public_task(self, actor, task_id):
        """Show a current partial publication alongside an unconfirmed preview."""
        task = self.get_task(actor, task_id)
        if (task['status'] != 'WAITING_CONFIRMATION' or task.get('outcome')
            or task.get('agent_contract') != 'obligation-v1'
            or task.get('routing_contract') != 'request-outcomes-visible-v11'
            or not task.get('delivery') or task.get('understanding_pending')
            or task.get('compact_facts_pending') or task.get('active_run_id')):
            return task
        from app.service_desk.goals import goal_mapping_complete
        if not goal_mapping_complete(task):
            return task
        expected = task['delivery']['binding']
        outcome = self.finish_goal(actor, task_id, _probe=True)
        with self.transaction() as db:
            current = self._task(db, actor, task_id)
            delivery = current.get('delivery')
            if (current['status'] != 'WAITING_CONFIRMATION' or current.get('active_run_id')
                or current.get('pending_proposal_id') != task['pending_proposal_id']
                or not delivery or delivery['binding'] != expected
                or self._answer_binding(db, actor, current, delivery['answers']) != expected):
                raise ServiceError('RESOURCE_CHANGED')
            _, content = self._bound_proposal(db, actor, current, current['pending_proposal_id'])
            self._check_preview_dependencies(db, actor, content)
            self._check_delivery_binding(actor, current, db=db)
            outcome.update(outcome_kind='awaiting_confirmation', goal_satisfied=False,
                lifecycle_state='WAITING_CONFIRMATION',
                next_step='Review this exact preview and explicitly confirm before submission. No ticket has been submitted.')
            # Same publisher, current binding, no stored outcome or state transition.
            current.update(outcome=outcome, outcome_binding=expected)
            return current

    def update_facts(self, actor, task_id, facts, *, expected_facts_revision=None):
        from app.service_desk.contracts import UserFacts,parameter_sources
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            from app.service_desk.contracts import RepairFacts
            fact_type=RepairFacts if task.get('guided_request',{}).get('kind')=='repair' else UserFacts
            raw_values = fact_type.model_validate(facts).model_dump(mode='json',exclude_unset=True)
            if expected_facts_revision is not None and expected_facts_revision!=task['facts_revision']:
                raise ServiceError('TASK_CHANGED',data={'current_revision':task['facts_revision'],
                    'current_facts':task['facts'],'conflicting_fields':list(raw_values)})
            self._live(task)
            if (task['active_run_id'] and not self.owns_run(task)) or task['receipt'] or db.execute(f'SELECT 1 FROM {self.ticket_table(task)} WHERE task_id=?',(task_id,)).fetchone():
                raise ServiceError('TASK_BUSY_OR_SUBMITTED')
            values,sources=parameter_sources(raw_values,
                {key:{'origin':'USER_FORM','value':value} for key,value in raw_values.items()},
                task.get('parameter_normalizer','literal-v1'))
            if all(task['facts'].get(key) == value for key, value in values.items()):
                # Re-saving the same form does not change the authorized operation.
                # Different facts still invalidate the proposal below.
                return task
            for key,value in values.items():
                if value is None:task['facts'].pop(key,None)
                else:task['facts'][key]=value
            field_event=None
            if task.get('interaction_mode')=='guided':
                field_event=uuid4().hex
                task.setdefault('guided_field_events',{}).update({k:field_event for k in values})
                task['guided_request']['facts']=dict(task['facts'])
                self._refresh_guided(task)
            task.setdefault('fact_sources',{}).update(sources)
            task['facts_revision'] += 1
            self._invalidate_derived(db,task,'facts_changed')
            task.update(status='NEW',pending_proposal_id=None,last_error=None)
            self._save(db,task)
            self._event(db,task_id,'user_facts',{'origin':'USER','fields':values,'raw_fields':raw_values,
                **({'form_event_id':field_event,'interpretation':'USER_CONFIRMED_STRUCTURED'} if field_event else {})})
            return task

    def configure_runtime(self,actor,task_id,config):
        with self.transaction() as db:
            task=self._task(db,actor,task_id); self._live(task)
            if task['active_run_id']: raise ServiceError('TASK_BUSY_OR_SUBMITTED')
            old_normalizer=task.get('parameter_normalizer','literal-v1')
            if task.get('interaction_mode')=='guided' and config.parameter_normalizer!='literal-v1':
                raise ServiceError('PARAMETER_CONTRACT_LOCKED')
            if old_normalizer!=config.parameter_normalizer:
                if task.get('pending_proposal_id') or task.get('receipt') or task.get('existing_ticket'):
                    raise ServiceError('PARAMETER_CONTRACT_LOCKED')
                from app.service_desk.contracts import parameter_sources
                raw={key:task.get('fact_sources',{}).get(key,{}).get('raw_value',value)
                     for key,value in task['facts'].items()}
                values,sources=parameter_sources(raw,task.get('fact_sources',{}),config.parameter_normalizer)
                if values!=task['facts']: task['facts_revision']+=1
                task.update(facts=values,fact_sources=sources)
            task['parameter_normalizer']=config.parameter_normalizer
            previous=task.get('runtime_index_manifest')
            if previous and previous!='UNBOUND' and previous!=config.index_manifest:
                raise ServiceError('INDEX_IDENTITY_CHANGED')
            if config.index_version!='UNBOUND' and any(e.get('index_run_id')!=config.index_version for e in task.get('knowledge',{}).values()):
                raise ServiceError('INDEX_IDENTITY_CHANGED')
            if task.get('runtime_fingerprint')!=config.fingerprint:
                self._invalidate_derived(db,task,'runtime_changed')
            stale={r:e for r,e in task.get('knowledge',{}).items()
                if e.get('knowledge_peer') is not None and e['knowledge_peer']!=config.knowledge_peer}
            if stale or (task.get('knowledge_peer')!=config.knowledge_peer and task.get('peer_answer_candidates')):
                retained=task.get('verified_need_answers',{})
                stale_answers={n:a for n,a in retained.items()
                    if any(c['evidence_ref'] in stale for c in a['answer']['citations'])}
                self._event(db,task_id,'peer_capability_retired',{'evidence':stale,
                    'candidates':task.get('peer_answer_candidates',{}),'answers':stale_answers,
                    'old_peer':task.get('knowledge_peer'),'new_peer':config.knowledge_peer,
                    'trust':'HISTORICAL_ONLY_REQUIRES_CURRENT_RETRIEVAL_AND_REVIEW'})
                task['knowledge']={r:e for r,e in task['knowledge'].items() if r not in stale}
                task['evidence_order']=[r for r in task.get('evidence_order',[]) if r not in stale]
                task['evidence_aliases']={a:r for a,r in task.get('evidence_aliases',{}).items() if r not in stale}
                task['verified_need_answers']={n:a for n,a in retained.items() if n not in stale_answers}
                task['peer_answer_candidates']={}
            task.update(runtime_protocol=config.protocol,execution_contract=config.execution_contract,runtime_fingerprint=config.fingerprint,
                runtime_index_manifest=config.index_manifest,runtime_index_version=config.index_version,
                task_attempt_limit=min(task.get('task_attempt_limit',16),config.task_attempt_limit),
                run_attempt_limit=config.run_attempt_limit,run_seconds=config.run_seconds,
                runtime_live_authorized=config.live_authorized,
                reframe_limit=config.reframe_limit)
            task['compact_understanding']=config.compact_understanding
            task['agent_contract']=config.agent_contract
            if config.agent_contract=='obligation-v1' and not task.get('goal_contract'):
                task['understanding_pending']=True
            task['route_with_review_model']=config.route_with_review_model
            task['routing_contract']=config.routing_contract
            task['request_semantics']=config.request_semantics
            task['knowledge_peer']=config.knowledge_peer
            task['semantic_review_contract']=config.semantic_review_contract
            task['blind_answer_interpretation']=config.blind_answer_interpretation
            task['scoped_source_interpretation']=config.scoped_source_interpretation
            task['knowledge_writer']=config.knowledge_writer
            task['shared_knowledge_candidate']=config.shared_knowledge_candidate
            task['typed_claim_review']=config.typed_claim_review
            task['local_review_batch']=config.local_review_batch
            task['independent_goal_review']=config.independent_goal_review
            task['separate_business_facts']=config.separate_business_facts
            if task.get('interaction_mode')=='guided':self._refresh_guided(task)
            self._save(db,task)
            self._event(db,task_id,'runtime_config',{'fingerprint':config.fingerprint,'config':config.model_dump(mode='json')})

    def _proposal_declined(self, db, actor, task):
        proposal_id=task.get('pending_proposal_id')
        if not proposal_id:return False
        confirmation=db.execute('SELECT * FROM confirmations WHERE proposal_id=?',(proposal_id,)).fetchone()
        if not confirmation or confirmation['accepted']:return False
        proposal,content=self._bound_proposal(db,actor,task,proposal_id,enforce_current=False)
        return (confirmation['content_digest']==proposal['content_digest']
            and confirmation['auth_digest']==self.auth_digest(actor)
            and content['task_revision']==task['facts_revision'] and content['parameters']==task['facts'])

    def begin_run(self, actor, task_id, *, followup=False):
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            self._live(task)
            if self._proposal_declined(db,actor,task):raise ServiceError('USER_DECLINED')
            blocked={'RECONCILING'} if followup else {'COMPLETED','WAITING_CONFIRMATION','RECONCILING','WAITING_EXTERNAL'}
            if task['active_run_id'] or task['status'] in blocked:
                raise ServiceError('TASK_BUSY_OR_FINISHED')
            if not task.get('product_runtime') and task['model_calls'] >= task.get('task_attempt_limit',16):
                raise ServiceError('BUDGET_EXCEEDED')
            task.update(active_run_id=uuid4().hex,status='RUNNING',last_error=None)
            if task.get('product_runtime'):
                task.update(run_fence=task.get('run_fence',0)+1,run_model_calls=0,run_tool_calls=0)
            if task.get('agent_contract')=='obligation-v1':
                task.update(run_fence=task.get('run_fence',0)+1,run_model_calls=0,
                    run_lease_until=min(self.clock()+task.get('run_seconds',60)+5,actor.expires_at.timestamp()))
            self._save(db,task)
            self._event(db,task_id,'run_started',{'run_id':task['active_run_id']})
            return task

    def reserve_model(self, actor, task_id, run_id, view):
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            self._live(task)
            if task['active_run_id'] != run_id:
                raise ServiceError('STALE_RUN')
            if not task.get('product_runtime') and task['model_calls'] >= task.get('task_attempt_limit',16):
                raise ServiceError('BUDGET_EXCEEDED')
            if task.get('product_runtime'):
                if task.get('run_model_calls',0)>=8:raise ServiceError('BUDGET_EXCEEDED')
                task['run_model_calls']=task.get('run_model_calls',0)+1
            step=None
            if task.get('agent_contract')=='obligation-v1':
                if task.get('run_model_calls',0)>=task.get('run_attempt_limit',8):raise ServiceError('BUDGET_EXCEEDED')
                task['run_model_calls']=task.get('run_model_calls',0)+1
                step={'step_id':run_id+':'+str(task['run_model_calls']),'run_id':run_id,'fence':task['run_fence'],
                    'purpose':view.get('purpose','understanding' if view.get('understanding_pending') else 'policy'),
                    'view_sha256':digest(view),'status':'RESERVED_BEFORE_CALL','reserved_at':self.clock()}
                task.setdefault('model_steps',[]).append(step)
            task['model_calls'] += 1
            self._save(db,task)
            self._event(db,task_id,'model_request',{'run_id':run_id,'view':view,'step':step})

    def recover_run(self,actor,task_id,expected_run_id,expected_fence,config_fingerprint,*,ledger_path=None):
        """Fence an expired owner; reconcile receipts, never replay an uncertain send or command."""
        with self.transaction() as db:
            task=self._task(db,actor,task_id);self._live(task)
            if task.get('agent_contract')!='obligation-v1':raise ServiceError('RECOVERY_NOT_SUPPORTED')
            if not expected_run_id or task['status']!='RUNNING':raise ServiceError('RUN_NOT_RECOVERABLE')
            if task.get('active_run_id')!=expected_run_id or task.get('run_fence')!=expected_fence:
                raise ServiceError('STALE_RUN')
            if task.get('runtime_fingerprint')!=config_fingerprint:raise ServiceError('CONFIG_NOT_AUTHORIZED')
            if task.get('run_lease_until',float('inf'))>self.clock():raise ServiceError('RUN_LEASE_ACTIVE')
            if task['status'] in {'RECONCILING','WAITING_CONFIRMATION'}:raise ServiceError('BUSINESS_RECONCILIATION_REQUIRED')
            actual=[]
            if task.get('runtime_live_authorized'):
                if ledger_path is None:raise ServiceError('RECOVERY_LEDGER_REQUIRED')
                with sqlite3.connect(Path(ledger_path).resolve().as_uri()+'?mode=ro',uri=True) as ledger:
                    actual=[dict(zip(('id','items','status'),r)) for r in ledger.execute(
                        "SELECT id,items,status FROM attempts WHERE operation='chat' AND task=? AND run=? ORDER BY id",
                        (task_id,expected_run_id))]
                if any(r['status']=='RESERVED_BEFORE_SEND' for r in actual):raise ServiceError('PENDING_SEND_REQUIRES_RECONCILIATION')
                if sum(r['items'] for r in actual)>task.get('run_model_calls',0):raise ServiceError('UNACCOUNTED_MODEL_SEND')
            task.update(active_run_id=None,run_fence=expected_fence+1,status='BLOCKED',last_error='RUN_RECOVERED_WITHOUT_REPLAY')
            self._save(db,task)
            self._event(db,task_id,'run_recovered',{'old_run_id':expected_run_id,'old_fence':expected_fence,
                'fence':task['run_fence'],'ledger_receipts':actual,'model_calls_preserved':task['model_calls'],
                'mode':'LIVE_LEDGER_RECONCILED' if task.get('runtime_live_authorized') else 'PROGRAM_ONLY',
                'replay':'NONE; uncertain reservations remain counted'})
            return task

    def reserve_tool(self, actor, task_id, name, arguments):
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            self._live(task)
            used = task.get('run_tool_calls',0) if task.get('product_runtime') else task['tool_calls']
            if used >= 24:
                raise ServiceError('BUDGET_EXCEEDED')
            if task.get('product_runtime'):task['run_tool_calls']=task.get('run_tool_calls',0)+1
            task['tool_calls'] += 1
            self._save(db,task)
            self._event(db,task_id,'tool_request',{'tool':name,'arguments':arguments})

    def record(self, actor, task_id, kind, data):
        with self.transaction() as db:
            task=self._task(db,actor,task_id)
            steps=task.get('model_steps',[])
            if steps and kind in {'model_response','model_exchange'}:
                latest=steps[-1]
                owner=_RUN_OWNER.get()
                if latest['run_id']==task.get('active_run_id') and (not owner or owner[1]==latest['run_id']):
                    response=data.get('raw_response') if kind=='model_exchange' else data.get('raw')
                    if response is not None:
                        latest.update(status='RESPONSE_RECORDED',response_sha256=digest(response))
                        self._save(db,task)
            self._event(db,task_id,kind,data)

    def observe(self, actor, task_id, name, result):
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            self._live(task)
            self._observe_result(db,actor,task,name,result)

    def _observe_result(self, db, actor, task, name, result):
        """Caller has validated the current owner in this same transaction."""
        task_id=task['task_id']
        if name=='tickets.list_mine':
            task['ticket_query_receipt']=None
            if result.get('status')=='ok':
                rows=db.execute(f'SELECT payload FROM {self.ticket_table(task)} WHERE tenant=? AND owner=? ORDER BY ticket_id',
                    (actor.tenant_id,actor.subject)).fetchall()
                current=[json.loads(r['payload']) for r in rows]
                if result.get('data',{}).get('tickets')==current:
                    task['ticket_query_receipt']={'status':'success','count':len(current),'as_of':self.clock(),
                        'expires_at':self.clock()+300,'scope':{'tenant':actor.tenant_id,'owner':actor.subject},
                        'auth_digest':self.auth_digest(actor),'filters':{},'data_sha256':digest(current),
                        'consistency':'transactional local SQLite snapshot; rechecked at publication'}
        if name=='tickets.get' and result.get('status')=='ok':
            data=result.get('data') or {}
            row=db.execute(f'SELECT payload FROM {self.ticket_table(task)} WHERE ticket_id=? AND tenant=? AND owner=?',
                (data.get('ticket_id'),actor.tenant_id,actor.subject)).fetchone()
            if row and data==json.loads(row['payload']):
                task.setdefault('resolved_ticket_results',{})[data['ticket_id']]=data
        observation={'tool':name,'result':result}
        if task.get('product_runtime'):
            fields=('loan_start','loan_end','min_memory_gb','pickup_location','date_flex_days') if task.get('guided_request',{}).get('kind')=='loan' and name=='assets.search' else ()
            observation['dependency_context']={'observed_at':self.clock(),'facts_revision':task['facts_revision'],
                'facts_projection':{field:task['facts'].get(field) for field in fields}}
        if name=='tickets.propose_create':
            observation['request_binding']={'facts_revision':task['facts_revision'],
                'facts_sha256':digest(task['facts']),'auth_digest':self.auth_digest(actor),
                'parameter_normalizer':task.get('parameter_normalizer','literal-v1'),
                'expires_at':self.clock()+300}
        task['observations'].append(observation)
        plan=task.get('source_plan') if name=='invalid_action' else None
        self._invalidate_derived(db,task,'observation_changed')
        if plan:
            from app.service_desk.delivery import source_plan_key
            if plan.get('binding')==source_plan_key(task):task['source_plan']=plan
        self._save(db,task)
        self._event(db,task_id,'tool_result',{'tool':name,'result':result})

    def business_conditions(self,actor,task_id):
        from app.service_desk.contracts import evaluate_owned_condition
        with self.transaction() as db:
            task=self._task(db,actor,task_id)
            receipt=self._current_ticket_query(db,actor,task)
            return [{'intent':u['intent'],'source':u['execution_condition']['source'],
                **evaluate_owned_condition(task,u['execution_condition'],receipt)}
                for u in task['task_goal'].get('request_units',[]) if u.get('execution_condition')]

    def fresh_business_reads(self,actor,task_id):
        """Suppress only results identical to the current owned database snapshot."""
        with self.transaction() as db:
            task=self._task(db,actor,task_id)
            if task.get('agent_contract')!='obligation-v1':return {}
            cached={}
            query=task.get('ticket_query_receipt') or {}
            rows=db.execute('SELECT payload FROM tickets WHERE tenant=? AND owner=? ORDER BY ticket_id',
                (actor.tenant_id,actor.subject)).fetchall()
            current=[json.loads(r['payload']) for r in rows]
            if (query.get('status')=='success' and query.get('expires_at',0)>self.clock()
                and query.get('auth_digest')==self.auth_digest(actor)
                and query.get('scope')=={'tenant':actor.tenant_id,'owner':actor.subject}
                and query.get('data_sha256')==digest(current)):
                cached['tickets.list_mine']={'data_sha256':query['data_sha256'],'count':len(current)}
            inventory=next((o['result'].get('data',{}) for o in reversed(task['observations'])
                if o['tool']=='assets.search' and o['result'].get('status')=='ok'),{})
            assets=[dict(r) for r in db.execute(
                'SELECT asset_id,category,available,version FROM assets WHERE tenant=? AND available=1',(actor.tenant_id,))]
            repair=db.execute('SELECT active,version FROM repairs WHERE tenant=? AND owner=?',
                (actor.tenant_id,actor.subject)).fetchone()
            actual={'assets':sorted(assets,key=encoded),'repair':dict(repair) if repair else None}
            if isinstance(inventory,dict) and 'assets' in inventory and (
                {'assets':sorted(inventory['assets'],key=encoded),'repair':inventory.get('repair')}==actual):
                cached['assets.search']={'data_sha256':digest(actual)}
            observed={}
            for item in task['observations']:
                if item['tool']=='tickets.get' and item['result'].get('status')=='ok':
                    data=item['result'].get('data')
                    if isinstance(data,dict) and data.get('ticket_id'):observed[data['ticket_id']]=data
            known={t['ticket_id']:t for t in current}
            # An unchanged existing-application result leaves readback, not another proposal.
            for item in reversed(task['observations']):
                if item['tool']!='tickets.propose_create':continue
                result=item['result'];data=result.get('data') or {};binding=item.get('request_binding') or {}
                ticket=data.get('ticket')
                if (isinstance(ticket,dict) and known.get(ticket.get('ticket_id'))==ticket
                    and ticket.get('status') in {'PENDING_APPROVAL','IN_PROGRESS'}
                    and ticket.get('parameters',{}).get('loan_end','')>=self.today().isoformat()
                    and (result.get('error_code')=='EXISTING_TICKET' or data.get('outcome_kind')=='existing_application')
                    and binding.get('facts_revision')==task['facts_revision']
                    and binding.get('facts_sha256')==digest(task['facts'])
                    and binding.get('auth_digest')==self.auth_digest(actor)
                    and binding.get('parameter_normalizer')==task.get('parameter_normalizer','literal-v1')
                    and binding.get('expires_at',0)>self.clock()):
                    cached['tickets.propose_create']={'ticket_id':ticket['ticket_id'],'version':ticket['version']}
                break
            fresh=sorted(ref for ref,data in observed.items() if known.get(ref)==data)
            if fresh:cached['tickets.get']=fresh
            return cached

    def stop_run(self, actor, task_id, status, *, error=None, missing=None):
        if status in {'BLOCKED','WAITING_USER'}:
            task=self.get_task(actor,task_id)
            from app.service_desk.delivery import bounded_peer_stop_ready
            rejected_peer=(status=='BLOCKED' and error=='PEER_REPAIR_EXHAUSTED'
                and bounded_peer_stop_ready(task))
            observed_partial=False
            if (status=='BLOCKED' and error in {'NO_PROGRESS','BUDGET_EXCEEDED',
                'MODEL_INPUT_BUDGET_EXCEEDED','MODEL_OUTPUT_TRUNCATED','MODEL_RESPONSE_INCOMPLETE',
                'MODEL_RESPONSE_INVALID','MODEL_RESPONSE_EMPTY','MODEL_REPEATED_TRUNCATION'}
                and task.get('agent_contract')=='obligation-v1' and task['status']!='CANCELLED'
                and not task.get('understanding_pending') and not task.get('compact_facts_pending')
                and not task.get('delivery')):
                from app.service_desk.goals import goal_mapping_complete
                if goal_mapping_complete(task):
                    current=self.finish_goal(actor,task_id,_probe=True)
                    observed_partial=bool(set(current['completed_outputs']) & {'asset_status','ticket_status'})
            if (task.get('agent_contract')=='obligation-v1' and task['status']!='CANCELLED'
                and (task.get('delivery') or observed_partial or rejected_peer) and not task.get('understanding_pending')):
                published=self.finish_goal(actor,task_id)
                if published['outcome']['goal_satisfied']:return published
        with self.transaction() as db:
            task = self._task(db,actor,task_id)
            owner=_RUN_OWNER.get()
            if owner and task['status']!='CANCELLED' and (task.get('active_run_id') not in {None,owner[1]}
                or task.get('run_fence')!=owner[2]):
                raise ServiceError('STALE_RUN')
            if task['status'] != 'CANCELLED':
                task.update(status=status,last_error=error,active_run_id=None)
                if missing is not None:
                    task['missing_fields'] = missing
                    from app.service_desk.goals import QUESTIONS
                    from app.service_desk.catalog import SERVICES
                    service=SERVICES.get(task.get('guided_request',{}).get('kind'))
                    task['question']=(service.questions(missing) if service else
                                      ' '.join(QUESTIONS[k] for k in missing))
                    if missing==['goal_subject'] and task['task_goal'].get('clarification'):
                        task['question']=task['task_goal']['clarification']
                    if status=='WAITING_USER' and task.get('outcome'):
                        task['outcome'].update(outcome_kind='needs_clarification',goal_satisfied=False,
                            missing_user_facts=missing,next_step=task['question'],lifecycle_state='WAITING_USER')
                self._save(db,task)
            self._event(db,task_id,'run_stopped',{'status':task['status'],'error':error})
            return task

    def completion_ready(self, actor, task_id):
        task=self.get_task(actor,task_id)
        if (task['status'] in {'CANCELLED','WAITING_CONFIRMATION','RECONCILING'} or task.get('understanding_pending')
            or task.get('compact_facts_pending')):
            return False
        result=self.finish_goal(actor,task_id,_probe=True)
        blocked_business=(result['outcome_kind'] in {'no_stock','not_eligible'}
            and set(task['task_goal']['required_outputs'])-set(result['completed_outputs'])=={'open_application'}
            and not result['withheld_need_ids'] and not result['coverage_issues'])
        if blocked_business and task.get('agent_contract')=='obligation-v1':
            from app.service_desk.goals import goal_mapping_complete
            blocked_business=goal_mapping_complete(task)
        return result['goal_satisfied'] or blocked_business or result['outcome_kind']=='waiting_external'

    def clarification_ready(self, actor, task_id):
        task=self.get_task(actor,task_id)
        if (task['status'] in {'CANCELLED','WAITING_CONFIRMATION','RECONCILING'}
            or task.get('understanding_pending') or task.get('compact_facts_pending')): return False
        result=self.finish_goal(actor,task_id,_probe=True)
        if not (result['outcome_kind']=='needs_clarification' and result['missing_user_facts'] and not result['goal_satisfied']):
            return False
        needed=task['task_goal']['required_outputs']
        if needed==['open_application']: return True
        if result['coverage_issues']: return False
        if task.get('agent_contract')=='obligation-v1':
            from app.service_desk.goals import goal_mapping_complete
            if not goal_mapping_complete(task): return False
        # finish_goal derives this question only from a current owned-ticket conflict.
        # Pending knowledge stays withheld; asking the user is not task completion.
        if (set(result['missing_user_facts']).issubset({'loan_start','loan_end','purpose'})
            and set(needed).intersection({'ticket_status','open_application'})):
            if (task.get('agent_contract')=='obligation-v1'
                and task.get('routing_contract')=='request-outcomes-visible-v11'
                and result['withheld_need_ids']):
                return False
            return True
        if ('ticket_status' not in needed or not set(needed).issubset(result['completed_outputs'])
            or result['withheld_need_ids'] or result['missing_obligation_ids']): return False
        return True

    def _current_ticket_query(self, db, actor, task):
        """Bind a fresh owned-list result to its actual tool event and current rows."""
        query=task.get('ticket_query_receipt') or {}
        now=self.clock()
        if (query.get('status')!='success' or type(query.get('count')) is not int or query['count']<0
            or query.get('auth_digest')!=self.auth_digest(actor)
            or query.get('scope')!={'tenant':actor.tenant_id,'owner':actor.subject}
            or query.get('filters')!={}
            or type(query.get('as_of')) not in (int,float)
            or type(query.get('expires_at')) not in (int,float)
            or not query['as_of']<=now<query['expires_at']):
            return None
        rows=db.execute(f'SELECT payload FROM {self.ticket_table(task)} WHERE tenant=? AND owner=? ORDER BY ticket_id',
            (actor.tenant_id,actor.subject)).fetchall()
        current=[json.loads(r['payload']) for r in rows]
        if query['count']!=len(current) or query.get('data_sha256')!=digest(current):
            return None
        events=db.execute("SELECT seq,payload,created_at FROM task_events WHERE task_id=? AND kind='tool_result' ORDER BY seq DESC",
            (task['task_id'],)).fetchall()
        for event in events:
            observation=json.loads(event['payload'])
            if observation.get('tool')!='tickets.list_mine':continue
            result=observation.get('result') or {}
            if (result.get('status')!='ok' or result.get('data',{}).get('tickets')!=current
                or not query['as_of']<=event['created_at']<=now):
                return None
            return {**query,'tickets':current,'snapshot_relation':'CURRENT_OWNED_LIST',
                'query_event_seq':event['seq']}
        return None

    def _prior_ticket_query(self, db, actor, task):
        """Prove the read was valid at this commit, never claim current emptiness."""
        query=task.get('ticket_query_receipt') or {}
        receipt=task.get('receipt') or {}
        if (query.get('status')!='success' or type(query.get('count')) is not int or query['count']<0
            or query.get('auth_digest')!=self.auth_digest(actor)
            or query.get('scope')!={'tenant':actor.tenant_id,'owner':actor.subject}
            or query.get('filters')!={} or not receipt.get('ticket_id')):
            return None
        rows=db.execute('SELECT payload FROM tickets WHERE tenant=? AND owner=? ORDER BY ticket_id',
            (actor.tenant_id,actor.subject)).fetchall()
        current=[json.loads(r['payload']) for r in rows]
        ticket=next((t for t in current if t.get('ticket_id')==receipt['ticket_id']),None)
        if (ticket!=receipt.get('ticket') or not ticket or ticket.get('task_id')!=task['task_id']
            or ticket.get('command_id')!=receipt.get('command_id')):
            return None
        command=db.execute('SELECT receipt FROM command_ledger WHERE command_id=?',
            (receipt['command_id'],)).fetchone()
        if not command or json.loads(command['receipt'])!=receipt:
            return None
        before=[t for t in current if t['ticket_id']!=receipt['ticket_id']]
        if query.get('count')!=len(before) or query.get('data_sha256')!=digest(before):
            return None
        commits=db.execute("SELECT seq,payload,created_at FROM task_events WHERE task_id=? AND kind='business_committed' ORDER BY seq DESC",
            (task['task_id'],)).fetchall()
        commit=next((e for e in commits if json.loads(e['payload'])==receipt),None)
        if (not commit or not query.get('as_of',float('inf'))<=commit['created_at']<query.get('expires_at',0)):
            return None
        events=db.execute("SELECT seq,payload,created_at FROM task_events WHERE task_id=? AND kind='tool_result' ORDER BY seq DESC",
            (task['task_id'],)).fetchall()
        for event in events:
            observation=json.loads(event['payload'])
            if observation.get('tool')!='tickets.list_mine':continue
            result=observation.get('result') or {}
            if (event['seq']>=commit['seq'] or result.get('status')!='ok'
                or result.get('data',{}).get('tickets')!=before
                or not query['as_of']<=event['created_at']<=commit['created_at']):
                return None
            return {**query,'snapshot_relation':'BEFORE_THIS_TASK_SUBMISSION',
                'consistency':'owned query event and exact same-task commit/readback; other owned rows unchanged',
                'query_event_seq':event['seq'],'commit_event_seq':commit['seq'],
                'submitted_ticket_id':receipt['ticket_id'],'tickets':before}
        return None

    def _committed_ticket(self, db, actor, task):
        receipt=task.get('receipt') or {}
        if not receipt.get('ticket_id') or not receipt.get('command_id'):return None
        row=db.execute(f'SELECT payload FROM {self.ticket_table(task)} WHERE ticket_id=? AND tenant=? AND owner=?',
            (receipt['ticket_id'],actor.tenant_id,actor.subject)).fetchone()
        ticket=json.loads(row['payload']) if row else None
        if (not ticket or ticket!=receipt.get('ticket') or ticket.get('task_id')!=task['task_id']
            or ticket.get('command_id')!=receipt['command_id']):return None
        command=db.execute('SELECT receipt FROM command_ledger WHERE command_id=?',
            (receipt['command_id'],)).fetchone()
        if not command or json.loads(command['receipt'])!=receipt:return None
        events=db.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='business_committed'",
            (task['task_id'],)).fetchall()
        return ticket if any(json.loads(event['payload'])==receipt for event in events) else None

    def finish_goal(self, actor, task_id, *, _probe=False):
        from app.service_desk.goals import TaskOutcome
        task = self.get_task(actor,task_id)
        if task.get('guided_request',{}).get('kind')=='repair':
            from app.service_desk.catalog import finish_repair
            return finish_repair(self,actor,task_id)
        self._check_delivery_binding(actor,task)
        with self.transaction() as db:
            publication_binding=self._answer_binding(db,actor,task,(task.get('delivery') or {}).get('answers',[]))
            prior_query=self._prior_ticket_query(db,actor,task)
            current_query=self._current_ticket_query(db,actor,task)
            declined=self._proposal_declined(db,actor,task)
            committed_ticket=self._committed_ticket(db,actor,task)
        if task.get('delivery') and task['delivery'].get('binding')!=publication_binding:
            raise ServiceError('RESOURCE_CHANGED')
        contract=task['task_goal']; completed=[]; answers=[]; refs=[]; ticket=None; missing=[]
        needed=contract['required_outputs']
        from app.service_desk.goals import execution_ceiling
        preview_complete=False
        if execution_ceiling(task)=='PREVIEW_ONLY' and task.get('pending_proposal_id'):
            with self.transaction() as db:
                _,preview=self._bound_proposal(db,actor,task,task['pending_proposal_id'])
                self._check_preview_dependencies(db,actor,preview)
            completed.append('open_application');preview_complete=True
            answers.append('Preview only; no application was submitted. '+encoded(preview['parameters']))
        original_obligations=(task.get('goal_contract') or {}).get('obligations',[])
        read_only_result=(task.get('agent_contract')=='obligation-v1'
            and task.get('routing_contract')=='request-outcomes-visible-v11'
            and bool(original_obligations)
            and set(needed).issubset({'policy_answer','ticket_status','asset_status'})
            and {o['output'] for o in original_obligations}.issubset({'policy_answer','ticket_status','asset_status'})
            and not any(u['intent']=='execute' for u in contract.get('request_units',[])))
        delivery=task.get('delivery'); withheld=[]; knowledge_questions=[]; limited_needs=[]; review_uncertain=False
        missing_needs=[n['id'] for n in contract.get('needs',[]) if n['id'] not in
                       {a['need_id'] for a in (delivery or {}).get('answers',[])}]
        if 'policy_answer' in needed and not delivery:
            withheld=missing_needs
        if 'policy_answer' in needed and delivery and delivery.get('host_validated'):
            assessment=delivery['assessment']
            per_need=assessment.get('need_assessments',[])
            host_rejected=[r['need_id'] for r in delivery.get('host_rejections',[])]
            withheld=list(dict.fromkeys(assessment['unsupported_need_ids']+host_rejected+missing_needs))
            if per_need:
                withheld=list(dict.fromkeys(withheld+[r['need_id'] for r in per_need if r['verdict']!='supported']))
                review_uncertain=any(r['verdict']=='review_uncertain' for r in per_need)
            elif not withheld and not (assessment['faithful_to_source'] and assessment['preserves_numbers_entities_negation_conditions']):
                withheld=[a['need_id'] for a in delivery['answers']]
                review_uncertain=True
            if not assessment['covers_user_needs'] and not assessment['unsupported_need_ids']:
                review_uncertain=True
            limited_needs=[a for a in delivery['answers'] if a['status']=='insufficient' and a['need_id'] in withheld]
            published=[a for a in delivery['answers'] if a['need_id'] not in withheld]
            answers.extend(a['answer'] for a in published)
            refs=list(dict.fromkeys(c['evidence_ref'] for a in published for c in a['citations']))
            knowledge_questions=[a['answer'] for a in published if a['status']=='need_user_fact']
            if (all(assessment[k] for k in ('faithful_to_source','covers_user_needs','preserves_numbers_entities_negation_conditions'))
                and not withheld and not review_uncertain and all(a['status']!='need_user_fact' for a in delivery['answers'])):
                completed.append('policy_answer')
            if host_rejected:
                answers.extend('该子问题的来源或回答尚未通过主机校验，未发布未验证文本。' for _ in host_rejected)
        if limited_needs:
            questions={n['id']:n['question'] for n in contract.get('needs',[])}
            for item in limited_needs:
                question=questions.get(item['need_id'],item['need_id'])
                answers.append('关于“'+question+'”：本次未能形成可核验的确定答案。这不表示相关规定或金额一定不存在；需要进一步核实。')
            refs=list(dict.fromkeys(refs+[c['evidence_ref'] for a in limited_needs for c in a['citations']]))
        from app.service_desk.delivery import bounded_peer_reports
        bounded_reports={nid:row for nid,row in bounded_peer_reports(task).items() if nid in withheld}
        answers.extend(row['answer'] for row in bounded_reports.values())
        reads = [o['result']['data'] for o in task['observations'] if o['tool']=='tickets.get'
                 and o['result']['status']=='ok']
        if task['receipt']: reads.append(task['receipt']['ticket'])
        conflicting_ticket=None; comparison_fields=None
        for observed in reversed(reads):
            current=self.get_ticket(actor,observed['ticket_id'])
            if current!=observed: continue
            if contract['ticket_ref'] and current['ticket_id']!=contract['ticket_ref']: continue
            if ('ticket_status' in needed and not contract['ticket_ref'] and len(self.list_tickets(actor))!=1
                and not (prior_query and current['ticket_id']==prior_query['submitted_ticket_id'])):
                missing=['ticket_ref']; continue
            from app.service_desk.contracts import parameter_differences
            # An exact committed command proves submission after its loan window too;
            # another task's application must still be active before it is reused.
            matching=((current==committed_ticket or (current['status'] in {'PENDING_APPROVAL','IN_PROGRESS'}
                and current['parameters'].get('loan_end','')>=self.today().isoformat()))
                and all(task['facts'].get(k) for k in ('loan_start','loan_end','purpose'))
                and not parameter_differences(current['parameters'],task['facts'],task.get('parameter_normalizer','literal-v1')))
            if 'open_application' in needed and not matching:
                if current['status'] in {'PENDING_APPROVAL','IN_PROGRESS'}:
                    conflicting_ticket=current
                continue
            ticket=current
            completed.extend(x for x in ('ticket_status','open_application') if x in needed)
            from app.service_desk.goals import ticket_next_step
            answers.append('Ticket '+current['ticket_id']+': '+current['status']+'. '+ticket_next_step(current['status']))
            requested={k:v for k,v in task['facts'].items()
                if k in {'loan_start','loan_end','purpose'} and v is not None
                and not (k=='purpose' and task.get('fact_sources',{}).get(k,{}).get('origin')=='LEGACY_TEXT')}
            actual={k:current.get('parameters',{}).get(k) for k in requested}
            differences=parameter_differences(actual,requested,task.get('parameter_normalizer','literal-v1'))
            if requested and differences:
                from app.service_desk.goals import response_language
                if response_language(task['goal'])=='zh':
                    answers.append('工单现有参数：'+encoded(current.get('parameters',{}))+'；本次请求参数：'+
                        encoded(requested)+'；相异字段：'+', '.join(differences)+'。未自动修改该工单或新建替代申请。')
                else:
                    answers.append('Actual ticket parameters: '+encoded(current.get('parameters',{}))+
                        '; requested parameters: '+encoded(requested)+'; differing fields: '+', '.join(differences)+
                        '. No automatic ticket change or replacement application was made.')
                if ('ticket_status' in needed and 'open_application' not in needed
                    and not read_only_result
                    and current['status'] in {'PENDING_APPROVAL','IN_PROGRESS'}
                    and current['parameters'].get('loan_end','')>=self.today().isoformat()):
                    conflicting_ticket=current; comparison_fields=differences
            break
        queried=bool(current_query and not contract['ticket_ref'] and 'ticket_status' in needed)
        absent=bool(queried and current_query['count']==0)
        if absent and 'ticket_status' in needed:
            completed.append('ticket_status')
            answers.append('截至本次查询，在当前本人可见范围内未查到匹配工单。未创建任何新申请。')
        elif queried:
            listed='；'.join(t['ticket_id']+'：'+t['status'] for t in current_query['tickets'])
            answers.append('截至本次查询，在当前本人可见范围内查到'+str(current_query['count'])+
                '个工单：'+listed+'。这是当前查询结果，不表示提交前的已有申请情况。')
            if 'ticket_status' not in completed:completed.append('ticket_status')
        if prior_query and not contract['ticket_ref'] and 'ticket_status' in needed:
            if prior_query['count']:
                previous='；'.join(t['ticket_id']+'：'+t['status'] for t in prior_query['tickets'])
                answers.append('提交前查询时，在当时本人可见范围内查到'+str(prior_query['count'])+
                    '个已有工单：'+previous+'。这是提交前的查询结果，本次新工单状态另见提交回执。')
            else:
                answers.append('提交前查询时，在当时本人可见范围内未查到已有工单；这不是提交后的当前空查询。本次新工单状态见提交回执。')
            if 'ticket_status' not in completed:completed.append('ticket_status')
        elif (not queried and task.get('receipt') and 'ticket_status' in needed and not contract['ticket_ref']
            and task.get('agent_contract')=='obligation-v1'
            and task.get('routing_contract')=='request-outcomes-visible-v11'
            and any(u.get('intent')=='lookup' for u in contract.get('request_units',[]))):
            completed=[output for output in completed if output!='ticket_status']
            answers.append('本次新工单回执已核验，但提交前的原查询结果未能重新核验；不能据新回执宣称原查询已完成。')
        if 'asset_status' in needed:
            current_assets=self.assets(actor)
            observed_assets=[o['result'].get('data',{}) for o in task['observations']
                if o['tool']=='assets.search' and o['result'].get('status')=='ok']
            if any({k:data.get(k) for k in ('assets','repair')}==current_assets for data in observed_assets):
                completed.append('asset_status')
                eligible=bool((current_assets['repair'] or {}).get('active'))
                stock=[r for r in current_assets['assets'] if r['category']=='laptop' and r['available']==1]
                answers.append('Current repair eligibility: '+('eligible' if eligible else 'not eligible')+
                    '; available laptops: '+str(len(stock))+'. This snapshot does not reserve or allocate a device.')
        satisfied=bool(needed) and set(needed).issubset(completed)
        status='COMPLETED' if satisfied else 'BLOCKED'
        next_step='No device approval or allocation is performed by this Agent.'
        if ticket: next_step=ticket_next_step(ticket['status'])
        outcome_kind='answer' if satisfied else 'evidence_limited' if limited_needs or bounded_reports else 'incomplete'
        if preview_complete and satisfied:
            outcome_kind='preview_ready';next_step='This preview cannot be confirmed or submitted. No ticket has been created.'
        if absent and satisfied: outcome_kind='no_matching_ticket'
        if contract['goal_subject']=='track_approval' and ticket and ticket['status']=='PENDING_APPROVAL':
            status='WAITING_EXTERNAL'; satisfied=False; outcome_kind='waiting_external'
            next_step='Contact the service desk for approval. Automatic background tracking is not enabled.'
        if not satisfied and not ticket:
            assets=[o['result']['data'] for o in task['observations'] if o['tool']=='assets.search' and o['result']['status']=='ok']
            if assets and 'open_application' in needed:
                current=self.assets(actor)
                if not current['repair'] or not current['repair']['active']:
                    outcome_kind='not_eligible'; answers.append('An active repair is required. No request was submitted.')
                    next_step='Ask the service desk to verify the repair record.'
                elif not any(a['category']=='laptop' and a['available']==1 for a in current['assets']):
                    outcome_kind='no_stock'; answers.append('No temporary laptop is currently available. No request was submitted.')
                    next_step='Contact the service desk about availability or retry later.'
        if contract['goal_subject']=='unknown': missing=['goal_subject']
        if contract['goal_subject']=='unsupported_action':
            completed.append('capability_boundary')
            resolved=bool(needed) and set(needed).issubset(completed)
            status='COMPLETED' if resolved else 'BLOCKED'
            outcome_kind='unsupported_action'; satisfied=False
            answers.append('当前服务台没有执行该操作的已注册能力，未创建替代申请，也未执行该操作。')
            next_step='可解释授权资料、查询本人借用工单，或在确认后提交临时电脑借用申请；审批、分配、采购和业务取消需联系服务台。'
        if missing: status='WAITING_USER'; next_step='Please clarify '+', '.join(missing)+'.'
        if conflicting_ticket and 'open_application' not in completed:
            status='WAITING_USER'; satisfied=False; outcome_kind='needs_clarification'
            from app.service_desk.contracts import parameter_differences
            missing=(comparison_fields if comparison_fields is not None else
                parameter_differences(conflicting_ticket['parameters'],task['facts'],task.get('parameter_normalizer','literal-v1')))
            if comparison_fields is None:
                answers.append('已有本人有效申请 '+conflicting_ticket['ticket_id']+'，内容为 '+encoded(conflicting_ticket['parameters'])+'；与本次请求存在差异，未自动复用或创建重复工单。')
            from app.service_desk.goals import response_language
            if response_language(task['goal'])=='zh':
                labels={'loan_start':'开始日期','loan_end':'结束日期','purpose':'用途'}
                next_step='您希望沿用已有申请的'+ '、'.join(labels[k] for k in missing)+'，还是保留本次请求值？若需更改已有申请，请联系服务台；本次未修改或新建申请。'
            else:
                next_step="Should I use the existing application's "+', '.join(missing)+", or keep the requested values? Contact the service desk to change an existing application; no change or new application was made."
            answers.append(next_step)
        if knowledge_questions:
            status='WAITING_USER'; outcome_kind='needs_clarification'; next_step=' '.join(knowledge_questions)
        obligation_missing=[]; coverage_issues=[]
        published_ids={a['need_id'] for a in (delivery or {}).get('answers',[]) if a['need_id'] not in withheld}
        if task.get('agent_contract')=='obligation-v1':
            from app.service_desk.goals import obligation_progress,goal_mapping_complete
            obligation_missing=obligation_progress(task,published_ids,completed)
            coverage=task.get('goal_coverage') or {}
            coverage_issues=[*coverage.get('issues',[]),
                *[{'kind':'UNMAPPED_EXECUTION_NEED','need_id':nid,'authority':'HOST_MAPPING_CHECK'}
                    for nid in coverage.get('unmapped_need_ids',[])]]
            goal_covered=goal_mapping_complete(task)
            if (needed==['policy_answer'] and not obligation_missing and goal_covered and published_ids and not knowledge_questions):
                if 'policy_answer' not in completed:completed.append('policy_answer')
                satisfied=True;status='COMPLETED';outcome_kind='answer'
            if (not task.get('goal_contract') or obligation_missing
                or (('policy_answer' in needed or task.get('independent_goal_review')
                    or task.get('semantic_review_contract')=='clauses-disposition-v2') and not goal_covered)):
                satisfied=False
                if status=='COMPLETED': status='BLOCKED'; outcome_kind='incomplete'
            blocker_only=(outcome_kind in {'no_stock','not_eligible'} and goal_covered
                and not missing and not coverage_issues and bool(obligation_missing)
                and all(o['output']=='open_application' and not o.get('need_id')
                    for o in task['goal_contract']['obligations'] if o['id'] in obligation_missing))
            clarification=(outcome_kind=='needs_clarification' and status=='WAITING_USER'
                and missing and goal_covered and not coverage_issues)
            if (obligation_missing or coverage_issues) and not blocker_only and not clarification:
                next_step='Resolve missing original obligations; verified partial answers are retained. No unconfirmed business action was performed.'
        canonical_pending=[]
        from app.service_desk.delivery import peer_answer_key, peer_need_unresolved
        for nid,row in task.get('peer_answer_candidates',{}).items():
            receipt=row.get('receipt',{})
            if (nid in published_ids and row.get('binding')==peer_answer_key(task)
                and receipt.get('knowledge_decision')
                and peer_need_unresolved(row,nid)):
                canonical_pending.append(nid)
                answers.extend(receipt['answer'].get('warnings',[]))
        if canonical_pending:
            completed=[o for o in completed if o!='policy_answer']
            satisfied=False
            if status=='COMPLETED':status='BLOCKED'
            outcome_kind='evidence_limited'
            next_step='Published source-bound facts are retained; unresolved knowledge coverage is not task completion.'
        if declined:
            satisfied=False;status='BLOCKED';outcome_kind='declined'
            answers.append('You declined this application. No ticket was submitted.')
            next_step='Verified answers are retained. Edit the application and review a new proposal when ready.'
        outcome=TaskOutcome(outcome_kind=outcome_kind,answer='\n'.join(dict.fromkeys(answers)) or 'The requested result has not been verified.',
            evidence_refs=refs,ticket_ref=ticket['ticket_id'] if ticket else None,business_status=ticket['status'] if ticket else None,
            next_step=next_step,missing_user_facts=missing,goal_satisfied=satisfied,completed_outputs=completed,
            need_results=([a for a in delivery['answers'] if a['need_id'] in published_ids]
                if task.get('agent_contract')=='obligation-v1' and delivery else delivery['answers'] if delivery else []),
            semantic_review='MODEL_PROVISIONAL_HUMAN_UNREVIEWED' if delivery else 'NOT_APPLICABLE',withheld_need_ids=withheld,
            review_uncertain=review_uncertain,missing_obligation_ids=obligation_missing,coverage_issues=coverage_issues,
            knowledge_state={**{a['need_id']:a.get('answer_disposition') or a['status'] for a in (delivery or {}).get('answers',[])
                if a['need_id'] in published_ids},**{nid:row['status'] for nid,row in bounded_reports.items()}},
            capability_state='UNAVAILABLE' if contract['goal_subject']=='unsupported_action' else 'REGISTERED',
            lifecycle_state='COMPLETE' if satisfied else 'WAITING_USER' if status=='WAITING_USER' else 'PARTIAL' if published_ids or bounded_reports else 'INCOMPLETE').model_dump()
        outcome['need_reviews']=(delivery or {}).get('assessment',{}).get('need_reviews',[])
        outcome['semantic_acceptance']='PENDING_INDEPENDENT_REVIEW' if delivery else 'NOT_APPLICABLE'
        outcome['canonical_unresolved_need_ids']=canonical_pending
        if queried: outcome['query_receipt']=current_query
        if prior_query and not contract['ticket_ref'] and 'ticket_status' in needed:
            outcome['prior_query_receipt']=prior_query
        if _probe: return outcome
        with self.transaction() as db:
            latest=self._task(db,actor,task_id); self._live(latest)
            if (self._answer_binding(db,actor,latest,(latest.get('delivery') or {}).get('answers',[]))!=publication_binding
                    or latest.get('delivery')!=delivery or self._prior_ticket_query(db,actor,latest)!=prior_query
                    or self._current_ticket_query(db,actor,latest)!=current_query
                    or self._committed_ticket(db,actor,latest)!=committed_ticket):
                raise ServiceError('RESOURCE_CHANGED')
            if delivery: self._check_delivery_binding(actor,latest,db=db)
            latest['outcome']=outcome
            latest['outcome_binding']=publication_binding
            if ticket: latest['existing_ticket']=ticket
            error=('USER_DECLINED' if declined else None if satisfied or status=='WAITING_EXTERNAL'
                or (outcome_kind=='unsupported_action' and status=='COMPLETED') else 'GOAL_NOT_COMPLETE')
            latest.update(status=status,last_error=error,active_run_id=None,missing_fields=missing)
            from app.service_desk.goals import QUESTIONS
            latest['question']=next_step if conflicting_ticket else ' '.join(QUESTIONS[k] for k in missing)
            if missing==['goal_subject'] and latest['task_goal'].get('clarification'):
                latest['question']=latest['task_goal']['clarification']
            # Outcome and terminal state commit together; no cancellation/revision gap between writes.
            self._save(db,latest); self._event(db,task_id,'outcome_verified',outcome)
            self._event(db,task_id,'run_stopped',{'status':status,'error':error})
        return latest

    def add_message(self, actor, task_id, text, message_id):
        from app.service_desk.contracts import facts_from_goal
        from app.service_desk.goals import task_goal
        if not text.strip() or len(text)>2000 or not message_id or len(message_id)>128:
            raise ServiceError('INVALID_ARGUMENTS')
        task=self.get_task(actor,task_id)
        if task.get('interaction_mode')=='guided':raise ServiceError('GUIDED_FIELDS_REQUIRED')
        if any(m['id']==message_id for m in task['messages']):
            if any(m['id']==message_id and m['text']==text for m in task['messages']): return task
            raise ServiceError('MESSAGE_CONFLICT')
        if task['goal_kind']=='auto':
            with self.transaction() as db:
                latest=self._task(db,actor,task_id); self._live(latest)
                if latest['active_run_id'] or latest['receipt'] or db.execute('SELECT 1 FROM tickets WHERE task_id=?',(task_id,)).fetchone():
                    raise ServiceError('TASK_BUSY_OR_SUBMITTED')
                latest['messages'].append({'id':message_id,'text':text})
                self._invalidate_derived(db,latest,'user_message')
                latest['facts_revision']+=1
                latest.update(status='NEW',understanding_pending=True,pending_proposal_id=None,
                              missing_fields=[],outcome=None,delivery=None)
                self._save(db,latest)
                self._event(db,task_id,'user_message',{'source_message_id':message_id,'text':text,'interpretation':'PENDING'})
            return self.get_task(actor,task_id)
        values=facts_from_goal(text,{},date.fromisoformat(task['time_context']['reference_date']))
        if task['facts'].get('purpose'): values.pop('purpose',None)
        self.update_facts(actor,task_id,values)
        known={t['ticket_id'] for t in self.list_tickets(actor)} if 'ticket_ref' in task.get('missing_fields',[]) else set()
        with self.transaction() as db:
            latest=self._task(db,actor,task_id); self._live(latest)
            if task['task_goal']['goal_subject']=='unknown':
                latest['task_goal']=task_goal(text,'auto')
                latest['task_goal']['source_message_id']=message_id
            if 'ticket_ref' in task.get('missing_fields',[]):
                # Exact user-supplied identifier; never take an ID from model text.
                matches=[ref for ref in known if ref in text]
                if len(matches)==1: latest['task_goal']['ticket_ref']=matches[0]
            latest['messages'].append({'id':message_id,'text':text})
            self._invalidate_derived(db,latest,'user_message')
            latest['facts_revision']+=1
            latest['pending_proposal_id']=None
            latest['fact_sources'].update({k:{'source_message_id':message_id,'text':text,'start':0,'end':len(text),'origin':'USER_TEXT'} for k in values})
            latest.update(status='NEW',missing_fields=[],outcome=None)
            self._save(db,latest); self._event(db,task_id,'user_message',{'source_message_id':message_id,'text':text,'facts':values})
        return self.get_task(actor,task_id)

    def apply_understanding(self, actor, task_id, raw, *, phase='normal'):
        from app.service_desk.understanding import validate_understanding
        with self.transaction() as db:
            task=self._task(db,actor,task_id); self._live(task)
            if task.get('interaction_mode')=='guided':raise ServiceError('GUIDED_TASK_IMMUTABLE')
            if not task.get('understanding_pending') and not (phase=='facts' and task.get('compact_facts_pending')):
                raise ServiceError('UNDERSTANDING_NOT_REQUESTED')
            if phase!='normal' and not task.get('compact_understanding'): raise ServiceError('INVALID_ARGUMENTS')
            if phase=='route' and task.get('separate_business_facts') and raw.get('facts'):
                raise ValueError('ROUTE_PHASE_CANNOT_APPLY_BUSINESS_FACTS')
            if task.get('agent_contract')=='obligation-v1' and isinstance(raw,dict):
                raw={**raw,'needs':[{**n,'id':n.get('id','host_proposal_'+str(i))}
                    for i,n in enumerate(raw.get('needs',[]))]}
            contract,values,sources,revisions=validate_understanding(task,raw)
            fact_intake_reused=(phase=='route' and task.get('agent_contract')=='obligation-v1'
                and task.get('routing_contract')=='request-outcomes-visible-v11'
                and task.get('separate_business_facts') and task.get('compact_facts_pending') is False
                and task.get('understanding_pending') and task.get('reframe_count')==1
                and task.get('reframe_reason') in {'goal_observation_mismatch','unsupported_capability'}
                and task.get('understanding_messages_digest')==digest(task['messages'])
                and values==task['facts'] and sources==task['fact_sources']
                and [u for u in contract.get('request_units',[]) if u['intent'] not in
                    {'explain','lookup','observe_assets'}]==[u for u in task['task_goal'].get('request_units',[])
                    if u['intent'] not in {'explain','lookup','observe_assets'}])
            if phase=='facts':
                from copy import deepcopy
                prior=task['task_goal']
                if (contract['goal_subject']!=prior['goal_subject']
                    or contract.get('request_frame')!=prior.get('request_frame')
                    or contract['forbidden_operations']!=prior['forbidden_operations']
                    or raw.get('goal_proposal') or raw.get('goal_delta')):
                    raise ValueError('FACT_PHASE_CANNOT_CHANGE_GOAL')
                # Fact extraction cannot re-derive or replace pinned result obligations.
                contract={**deepcopy(prior),'ticket_ref':contract.get('ticket_ref')}
            if task.get('agent_contract')=='obligation-v1':
                from app.service_desk.goals import (bind_goal_contract,goal_messages_digest,reconcile_goal_delta,
                    bind_execution_need_ids,remap_goal_execution)
                previous_goal=task.get('goal_contract')
                if (previous_goal and goal_messages_digest(previous_goal)==digest(task['messages'])
                    and any(o['output']=='open_application' and not o['need_id']
                        for o in previous_goal['obligations'])
                    and 'open_application' not in contract['required_outputs']):
                    raise ValueError('WRITE_OBLIGATION_NOT_IN_PLAN: retain the original requested application '
                        'in the plan; an observed blocker is not a user goal replacement or write permission')
                previous_ids={digest({k:v for k,v in n.items() if k!='id'}):n['id'] for n in task['task_goal']['needs']}
                mapping={n['id']:(previous_ids.get(digest({k:v for k,v in n.items() if k!='id'}))
                    if previous_goal and goal_messages_digest(previous_goal)==digest(task['messages']) else None)
                    or 'n'+digest({k:v for k,v in n.items() if k!='id'})[:24] for n in contract['needs']}
                if task.get('semantic_review_contract')=='clauses-disposition-v2':
                    mapping=bind_execution_need_ids(task,contract['needs'])
                contract['needs']=[{**n,'id':mapping[n['id']]} for n in contract['needs']]
                pending=(contract['goal_subject']=='unknown' and not contract['required_outputs']
                    and not contract['needs'] and raw.get('goal_proposal')=={'obligations':[],'relations':[]})
                if pending:
                    if previous_goal:
                        from copy import deepcopy
                        contract['needs']=deepcopy(task['task_goal']['needs'])
                        contract['required_outputs']=list(task['task_goal']['required_outputs'])
                    self._event(db,task_id,'goal_interpretation_pending',{
                        'previous_contract_sha256':(previous_goal or {}).get('sha256'),
                        'reason':'User clarification required; no invented obligation or completion approval.'})
                elif not previous_goal or goal_messages_digest(previous_goal)!=digest(task['messages']):
                    if not raw.get('goal_proposal'):raise ValueError('GOAL_PROPOSAL_REQUIRED')
                    # Host identities are not model-selected labels. Keep model IDs only in this proposal mapping.
                    obligations=[]
                    for item in raw['goal_proposal']['obligations']:
                        position=item.get('need_index')
                        if position is not None:
                            if type(position) is not int or not 0<=position<len(contract['needs']):
                                raise ValueError('OBLIGATION_NEED_BINDING')
                            selected=contract['needs'][position]['id']
                            if item.get('need_id') is not None and mapping.get(item['need_id'])!=selected:
                                raise ValueError('OBLIGATION_NEED_BINDING')
                        elif item.get('need_id') is not None:
                            selected=mapping.get(item['need_id'])
                        elif item.get('output')=='policy_answer':
                            exact=[n['id'] for n in contract['needs'] if all(item.get(k)==n.get(k)
                                for k in ('question','source_message_id','quote'))]
                            selected=exact[0] if len(exact)==1 else None
                        else:
                            selected=None
                        obligations.append({**item,'need_id':selected})
                    proposed={**raw['goal_proposal'],'obligations':obligations}
                    goal=bind_goal_contract({**task,'task_goal':contract},proposed)
                    if previous_goal and task.get('semantic_review_contract')=='clauses-disposition-v2':
                        goal=reconcile_goal_delta(task,contract,goal,revisions,raw.get('goal_delta'))
                    task.setdefault('goal_contract_history',[]).append({'previous':previous_goal,'current':goal})
                    task['goal_contract']=goal
                if previous_goal and not pending and task.get('semantic_review_contract')=='clauses-disposition-v2':
                    from app.service_desk.goals import provisional_goal_inventory_feedback
                    inventory_recovery=(task.get('understanding_pending') and task.get('reframe_count')==1
                        and provisional_goal_inventory_feedback(task) and raw.get('goal_proposal'))
                    read_role_changed=(task.get('routing_contract')=='request-outcomes-visible-v11'
                        and raw.get('goal_proposal') and any(o['output'] in {'asset_status','ticket_status'}
                        and (o['output'] not in contract['required_outputs'] or any(
                            u['intent']=='explain' and u['source']==o['source'] and not any(
                                prior['intent']=='explain' and prior['source']==u['source']
                                for prior in task['task_goal'].get('request_units',[]))
                            for u in contract.get('request_units',[])))
                        for o in task['goal_contract']['obligations']))
                    try:
                        if inventory_recovery:
                            from app.service_desk.goals import recover_provisional_goal_inventory
                            proposed={**raw['goal_proposal'],'obligations':[{**item,
                                **({'need_id':mapping.get(item['need_id'],item['need_id'])} if item.get('need_id') else {})}
                                for item in raw['goal_proposal']['obligations']]}
                            goal=recover_provisional_goal_inventory(task,contract,
                                bind_goal_contract({**task,'task_goal':contract},proposed))
                            self._event(db,task_id,'provisional_inventory_recovered',goal['provisional_reinterpretation'])
                        elif read_role_changed:
                            from app.service_desk.goals import reinterpret_provisional_reads
                            proposed={**raw['goal_proposal'],'obligations':[{**item,
                                **({'need_id':mapping.get(item['need_id'],item['need_id'])} if item.get('need_id') else {})}
                                for item in raw['goal_proposal']['obligations']]}
                            goal=reinterpret_provisional_reads(task,contract,
                                bind_goal_contract({**task,'task_goal':contract},proposed))
                            self._event(db,task_id,'provisional_role_reinterpreted',goal['provisional_reinterpretation'])
                        else:goal=remap_goal_execution(task['goal_contract'],contract['needs'])
                    except ValueError as exc:
                        if not str(exc).startswith('ORIGINAL_OBLIGATION_NOT_MAPPED') or not raw.get('goal_proposal'):
                            raise
                        if not set(task['task_goal']['required_outputs']).intersection({'open_application','asset_status','ticket_status'}):
                            raise
                        from app.service_desk.goals import reinterpret_provisional_knowledge
                        proposed={**raw['goal_proposal'],'obligations':[{**item,
                            **({'need_id':mapping.get(item['need_id'],item['need_id'])} if item.get('need_id') else {})}
                            for item in raw['goal_proposal']['obligations']]}
                        goal=reinterpret_provisional_knowledge(task,contract,
                            bind_goal_contract({**task,'task_goal':contract},proposed))
                        self._event(db,task_id,'provisional_role_reinterpreted',goal['provisional_reinterpretation'])
                    if goal!=task['goal_contract']:
                        task.setdefault('goal_contract_history',[]).append({'previous':task['goal_contract'],'current':goal})
                        task['goal_contract']=goal
            previous=task['task_goal'].get('needs',[])
            if (task.get('understanding_messages_digest')==digest(task['messages']) and previous
                and phase!='facts' and task.get('semantic_review_contract')!='clauses-disposition-v2'):
                requested={(n['source_message_id'],n['quote']) for n in contract['needs']}
                if not all((n['source_message_id'],n['quote']) in requested for n in previous):
                    raise ValueError('ORIGINAL_NEED_SOURCE_DROPPED: tools cannot remove pinned user questions')
            changed=values!=task['facts'] or contract!=task['task_goal']
            self._invalidate_derived(db,task,'understanding_changed')
            task.update(task_goal=contract,facts=values,fact_sources=sources,understanding_pending=False,
                        missing_fields=[],delivery=None,pending_proposal_id=None)
            parameter_intake=(task.get('agent_contract')=='obligation-v1' and task.get('separate_business_facts')
                and set(contract['required_outputs']).intersection({'asset_status','ticket_status'})
                and any(u['intent']=='fact_update' for u in contract.get('request_units',[])))
            if (task.get('agent_contract')=='obligation-v1' and task.get('separate_business_facts')
                and task.get('routing_contract')=='request-outcomes-visible-v11'
                and 'ticket_status' in contract['required_outputs']):
                from app.service_desk.understanding import date_source_candidates
                background=[{'id':u['source']['source_message_id'],'text':u['source']['quote']}
                    for u in contract.get('request_units',[]) if u['intent']=='background']
                # Calendar syntax schedules interpretation, never supplies loan facts or consent.
                parameter_intake=parameter_intake or bool(date_source_candidates(background,task['time_context']))
            task['compact_facts_pending']=(phase=='route' and not fact_intake_reused
                and (contract['goal_subject']=='submit_loan' or bool(parameter_intake)))
            if fact_intake_reused:
                self._event(db,task_id,'fact_intake_reused',{'reason':'unchanged_user_inputs_during_internal_role_correction',
                    'messages_sha256':digest(task['messages']),'facts_sha256':digest(values),
                    'fact_sources_sha256':digest(sources),'approval':'NONE; goal/source/confirmation checks still required'})
            task['understanding_messages_digest']=digest(task['messages'])
            if changed: task['facts_revision']+=1
            self._save(db,task)
            self._event(db,task_id,'understanding_applied',{'interpretation':raw,'contract':contract,'revisions':revisions})
        return self.get_task(actor,task_id)

    def request_reframe(self,actor,task_id,reason):
        if self.get_task(actor,task_id).get('interaction_mode')=='guided':raise ServiceError('GUIDED_TASK_IMMUTABLE')
        if reason not in {'goal_observation_mismatch','unsupported_capability','user_clarification'}:
            raise ServiceError('INVALID_REFRAME_REASON')
        with self.transaction() as db:
            task=self._task(db,actor,task_id); self._live(task)
            if (reason=='user_clarification' and task.get('agent_contract')=='obligation-v1'
                and task.get('routing_contract')=='request-outcomes-visible-v11'
                and not any(m['id']!='initial' for m in task['messages'])):
                raise ServiceError('USER_CLARIFICATION_NOT_OBSERVED')
            if task.get('reframe_count',0)>=task.get('reframe_limit',1): raise ServiceError('REFRAME_LIMIT')
            if task['receipt'] or task['status'] in {'WAITING_CONFIRMATION','COMPLETED','WAITING_EXTERNAL','RECONCILING'}:
                raise ServiceError('TASK_BUSY_OR_SUBMITTED')
            from app.service_desk.goals import provisional_goal_inventory_feedback
            feedback=provisional_goal_inventory_feedback(task)
            if feedback:self._observe_result(db,actor,task,'host.goal_plan_feedback',feedback)
            task['reframe_count']=task.get('reframe_count',0)+1
            task['facts_revision']+=1
            self._invalidate_derived(db,task,'reframe')
            task.update(understanding_pending=True,reframe_reason=reason,delivery=None,outcome=None,pending_proposal_id=None,missing_fields=[])
            self._save(db,task)
            self._event(db,task_id,'reframe_requested',{'reason':reason,'count':task['reframe_count'],
                'preserved_prohibitions':task['task_goal']['forbidden_operations'],'facts_preserved':task['fact_sources']})
        return self.get_task(actor,task_id)

    def reserve_answer_shortening(self, actor, task_id, need_id):
        from app.service_desk.delivery import peer_answer_key
        with self.transaction() as db:
            task=self._task(db,actor,task_id);self._live(task)
            self._check_delivery_binding(actor,task)
            if need_id not in {n['id'] for n in task['task_goal']['needs']}:
                raise ServiceError('INVALID_ARGUMENTS')
            key=digest({'need_id':need_id,'dependencies':peer_answer_key(task),
                'goal_contract':task.get('goal_contract'),
                'sources':{r:{k:e.get(k) for k in ('text','document_id','chunk_id',
                    'version_id','index_run_id','source_path','invalidated_by')}
                    for r,e in task.get('knowledge',{}).items()}})
            reservations=task.setdefault('answer_shortening_attempts',{})
            if key in reservations:return False
            reservations[key]={'need_id':need_id,'authority':'REWRITE_ONLY_NOT_APPROVAL'}
            self._save(db,task)
            self._event(db,task_id,'answer_shortening_reserved',{'binding':key,'need_id':need_id})
        return True

    def prepare_delivery(self, actor, task_id, answers, *, reassess_cached=True):
        from app.service_desk.delivery import validate_delivery
        task=self.get_task(actor,task_id)
        self._check_delivery_binding(actor,task)
        for source in task.get('knowledge',{}).values():
            if source.get('auth_digest') and source['auth_digest']!=self.auth_digest(actor):
                raise ServiceError('AUTH_DENIED')
        rejections=[]
        if any('span_refs' in answer for answer in answers):
            needs={n['id']:n for n in task['task_goal']['needs']}
            ids=[a.get('need_id') for a in answers]
            if not ids or len(ids)!=len(set(ids)) or not set(ids).issubset(needs):
                raise ValueError('Deliver a nonempty unique subset of original needs')
            validated=[]
            for answer in answers:
                subset={**task,'task_goal':{**task['task_goal'],'needs':[needs[answer['need_id']]]}}
                try: validated.extend(validate_delivery(subset,[answer]))
                except ValueError as exc:
                    rejections.append({'need_id':answer['need_id'],'field_path':'answers.'+answer['need_id'],
                        'reason':str(exc),'available_spans':[ref+'.S1' for ref in task.get('evidence_aliases',{})],
                        'evidence_scope':task['task_id'][:12]})
        else:
            if not answers: raise ValueError('Deliver a nonempty subset of original needs')
            validated=validate_delivery(task,answers)
        with self.transaction() as db:
            latest=self._task(db,actor,task_id)
            if latest!=task: raise ServiceError('RESOURCE_CHANGED')
            submitted={a['need_id'] for a in validated}
            for nid,entry in task.get('verified_need_answers',{}).items():
                if reassess_cached and nid not in submitted and entry.get('review_context')!=self._review_context(task,entry['answer']):
                    subset={**task,'task_goal':{**task['task_goal'],'needs':[n for n in task['task_goal']['needs'] if n['id']==nid]}}
                    validated.extend(validate_delivery(subset,[entry['answer']]))
            binding=self._answer_binding(db,actor,task,validated)
        return {'answers':validated,'task_revision':task['facts_revision'],'host_rejections':rejections,'binding':binding}

    def offer_retained_draft(self,actor,task_id):
        from app.service_desk.delivery import validate_delivery
        from app.service_desk.evidence import resolve_span
        from app.service_desk.goals import goal_review_fresh,separate_goal_review
        task=self.get_task(actor,task_id)
        self._live(task)
        if (task.get('agent_contract')!='obligation-v1'
            or task.get('routing_contract')!='request-outcomes-visible-v11'
            or task.get('knowledge_writer')!='grounded_answer'
            or task.get('understanding_pending') or task.get('compact_facts_pending')):
            return None
        coverage=task.get('goal_coverage') or {}
        if separate_goal_review(task) and (not coverage.get('complete') or not goal_review_fresh(task,coverage)):
            return None
        self._check_delivery_binding(actor,task)
        with self.transaction() as db:
            current=self._task(db,actor,task_id)
            self._live(current)
            if current!=task:raise ServiceError('RESOURCE_CHANGED')
            self._check_delivery_binding(actor,task,db=db)
            answers=[];offered=[]
            for need in task['task_goal']['needs']:
                nid=need['id']
                retained=task.get('verified_need_answers',{}).get(nid)
                drafts=list(reversed(list(task.get('invalidated_need_drafts',{}).items())))
                if retained:
                    if retained.get('review_context')==self._review_context(task,retained['answer']):continue
                    drafts=[('retained:'+nid,{'answer':retained['answer'],
                        'prior_binding':retained['binding'],'trust':'STALE_DRAFT_REQUIRES_FULL_REVALIDATION',
                        'revalidation_attempts':retained.setdefault('revalidation_attempts',[])})]
                for key,entry in drafts:
                    answer=entry['answer'];prior=entry['prior_binding']
                    if (answer['need_id']!=nid or entry['trust']!='STALE_DRAFT_REQUIRES_FULL_REVALIDATION'
                        or prior.get('task_id')!=task_id or prior.get('auth_digest')!=self.auth_digest(actor)):
                        continue
                    try:
                        refs=[citation['evidence_ref']+'.S1' for citation in answer['citations']]
                        if [resolve_span(task,ref) for ref in refs]!=answer['citations']:continue
                        candidate={'need_id':nid,'answer':answer['answer'],
                            'answer_disposition':answer['answer_disposition'],'target':answer['target'],
                            'span_refs':refs,'evidence_scope':task_id[:12],
                            'search_receipts':answer.get('search_receipts',[])}
                        subset={**task,'task_goal':{**task['task_goal'],'needs':[need]}}
                        validated=validate_delivery(subset,[candidate])
                    except (ValueError,KeyError):
                        continue
                    if validated!=[answer]:continue
                    binding=digest({'need_binding':self._need_binding(db,actor,task,answer),
                        'review_context':self._review_context(task,answer)})
                    attempts=entry.get('revalidation_attempts',[])
                    if binding in attempts or len(attempts)>=task.get('task_attempt_limit',16):break
                    entry.setdefault('revalidation_attempts',[]).append(binding)
                    answers.append(candidate);offered.append({'draft_key':key,'current_binding':binding,'need_id':nid})
                    break
            if not answers:return None
            # Retain only bytes. The existing runner must prepare and review them anew.
            self._save(db,task)
            self._event(db,task_id,'retained_draft_offered',{'drafts':offered,
                'approval':'NONE_REQUIRES_CURRENT_PREPARATION_AND_REVIEW','model_send':False})
            return {'kind':'deliver','answers':answers}

    def get_source_plan(self,actor,task_id):
        from app.service_desk.delivery import source_plan_key,validate_source_plan
        task=self.get_task(actor,task_id);self._live(task);self._check_delivery_binding(actor,task)
        plan=task.get('source_plan')
        if plan and plan.get('binding')==source_plan_key(task) and plan.get('status')!='REJECTED_BY_HOST':
            validate_source_plan(task,plan['interpretation'])
            return plan
        return None

    def begin_source_plan_attempt(self,actor,task_id,expected):
        from app.service_desk.delivery import source_plan_key
        with self.transaction() as db:
            task=self._task(db,actor,task_id);self._live(task);self._check_delivery_binding(actor,task,db=db)
            if expected!=source_plan_key(task):raise ServiceError('RESOURCE_CHANGED')
            attempts=task.get('source_plan_attempts') or {}
            if attempts.get('binding')!=expected:attempts={'binding':expected,'count':0}
            if attempts['count']>=2:raise ServiceError('SOURCE_PLAN_REPAIR_EXHAUSTED')
            attempts['count']+=1
            task['source_plan_attempts']=attempts
            self._save(db,task);self._event(db,task_id,'source_plan_attempt',attempts)

    def reject_source_plan(self,actor,task_id,expected,candidate,error,rejected=None):
        from app.service_desk.delivery import source_plan_key
        with self.transaction() as db:
            task=self._task(db,actor,task_id);self._live(task);self._check_delivery_binding(actor,task,db=db)
            if expected!=source_plan_key(task):raise ServiceError('RESOURCE_CHANGED')
            attempts=task.get('source_plan_attempts') or {'binding':expected,'count':0}
            if attempts.get('binding')!=expected:raise ServiceError('RESOURCE_CHANGED')
            feedback={'owner':'source_plan','validation_error':str(error),
                'affected_need_ids':[a['need_id'] for a in candidate],'candidate':candidate,
                'rejected_interpretation':rejected,
                'instruction':'Repair the rejected source interpretation against the original needs and authentic spans. The candidate is not an approved fact.'}
            attempts['feedback']=feedback
            plan=task.get('source_plan')
            self._invalidate_derived(db,task,'source_plan_rejected')
            if plan and plan.get('binding')==expected:
                plan['status']='REJECTED_BY_HOST';task['source_plan']=plan
            task['source_plan_attempts']=attempts
            self._save(db,task);self._event(db,task_id,'source_plan_rejected',feedback)

    def bind_source_plan(self,actor,task_id,expected,interpretation):
        from app.service_desk.delivery import source_plan_key,validate_source_plan
        with self.transaction() as db:
            task=self._task(db,actor,task_id);self._live(task);self._check_delivery_binding(actor,task,db=db)
            if expected!=source_plan_key(task): raise ServiceError('RESOURCE_CHANGED')
            value=validate_source_plan(task,interpretation)
            revision=task.get('source_plan_revision',0)+1
            self._invalidate_derived(db,task,'source_plan_changed')
            task['source_plan_revision']=revision
            task['source_plan']={'binding':expected,'interpretation':value,'revision':revision,
                'status':'MODEL_PROVISIONAL_NOT_HUMAN_APPROVAL'}
            task['coverage_review']=None
            self._save(db,task);self._event(db,task_id,'source_plan_bound',task['source_plan'])
        return self.get_task(actor,task_id)

    def _check_delivery_binding(self,actor,task,db=None):
        manifest=task.get('runtime_index_manifest')
        if manifest and manifest!='UNBOUND':
            binding=db.execute('SELECT * FROM rule_sources WHERE tenant=?',(actor.tenant_id,)).fetchone() if db is not None else self.source_binding(actor)
            if not binding or binding['manifest_sha256']!=manifest: raise ServiceError('INDEX_IDENTITY_CHANGED')
        for evidence in task.get('knowledge',{}).values():
            if evidence.get('auth_digest') and evidence['auth_digest']!=self.auth_digest(actor): raise ServiceError('AUTH_DENIED')
            version=task.get('runtime_index_version')
            peer=evidence.get('knowledge_peer')
            if peer is not None:
                if not task.get('knowledge_peer') or peer!=task['knowledge_peer']:
                    raise ServiceError('INDEX_IDENTITY_CHANGED')
                if evidence.get('index_manifest')!=peer['index_fingerprint']:
                    raise ServiceError('INDEX_IDENTITY_CHANGED')
                continue
            if version and version!='UNBOUND' and evidence.get('index_run_id')!=version: raise ServiceError('INDEX_IDENTITY_CHANGED')

    def assess_delivery(self, actor, task_id, prepared, assessment):
        from app.service_desk.delivery import Assessment,validate_delivery,source_plan_key,coverage_review_key,validate_original_units
        assessment=Assessment.model_validate(assessment).model_dump()
        with self.transaction() as db:
            task=self._task(db,actor,task_id); self._live(task)
            if prepared['task_revision']!=task['facts_revision'] or task.get('understanding_pending'):
                raise ServiceError('RESOURCE_CHANGED')
            self._check_delivery_binding(actor,task,db=db)
            if prepared.get('binding')!=self._answer_binding(db,actor,task,prepared['answers']):
                raise ServiceError('RESOURCE_CHANGED')
            if task.get('semantic_review_contract')=='source-plan-v2':
                if assessment['source_plan_binding']!=source_plan_key(task):raise ServiceError('RESOURCE_CHANGED')
                covered=validate_original_units(task,assessment['original_units'])
                if covered!=assessment['covers_user_needs']:raise ValueError('COVERAGE_PROOF_MISMATCH')
                task['coverage_review']={'binding':coverage_review_key(task),'complete':covered,
                    'original_units':assessment['original_units'],'status':'MODEL_PROVISIONAL_NOT_HUMAN_APPROVAL'}
            from app.service_desk.goals import user_structured_goal
            if task.get('agent_contract')=='obligation-v1' and task.get('goal_contract') and not user_structured_goal(task):
                from app.service_desk.goals import validate_goal_coverage
                covered=validate_goal_coverage(task,assessment['goal_coverage'])
                if covered['complete']!=assessment['covers_user_needs']:raise ValueError('GOAL_COVERAGE_MISMATCH')
                task['goal_coverage']=covered
            rejected=prepared.get('host_rejections',[])
            subset={**task,'task_goal':{**task['task_goal'],'needs':[n for n in task['task_goal']['needs']
                if n['id'] in {a['need_id'] for a in prepared['answers']}]}}
            answers=validate_delivery(subset,prepared['answers']) if prepared['answers'] else []
            if task.get('semantic_review_contract')=='clauses-disposition-v2' and answers:
                from app.service_desk.delivery import normalize_reviewed_dispositions
                checked={r['need_id']:r for r in assessment['need_reviews']}
                ids=[r['need_id'] for r in assessment['need_assessments']]
                if len(ids)!=len(answers) or set(ids)!={a['need_id'] for a in answers}:
                    raise ValueError('DISPOSITION_PROOF: every actual need requires an assessment')
                approved={r['need_id'] for r in assessment['need_assessments'] if r['verdict']=='supported'}
                if any(not checked.get(nid,{}).get('reviewed_disposition') for nid in approved):
                    raise ValueError('DISPOSITION_PROOF: approved need requires independently classified full body')
                answers,corrections=normalize_reviewed_dispositions(task,answers,assessment['need_reviews'])
                answers=validate_delivery(subset,answers)
                for correction in corrections:
                    self._event(db,task_id,'answer_disposition_normalized',correction)
            need_ids={a['need_id'] for a in answers}
            per_need=assessment.get('need_assessments',[])
            if not set(assessment['unsupported_need_ids']).issubset(need_ids):
                raise ValueError('Review must identify actual need IDs')
            if per_need and (len(per_need)!=len(need_ids) or {r['need_id'] for r in per_need}!=need_ids):
                raise ValueError('Review every need exactly once')
            if task.get('semantic_review_contract')=='clauses-disposition-v2':
                mapped=({n['id'] for n in task['task_goal']['needs']} if user_structured_goal(task) else
                    {nid for row in task['goal_coverage']['obligations'] if row['verdict']=='represented'
                        for nid in row['represented_need_ids']})
                for row in per_need:
                    if row['verdict']=='supported' and row['need_id'] not in mapped:
                        row.update(verdict='review_uncertain',reason='Original obligation mapping is not verified; source/body support alone cannot publish this execution need.')
            task['delivery']={'answers':answers,'assessment':assessment,'host_validated':True,
                              'semantic_review':'MODEL_PROVISIONAL_HUMAN_UNREVIEWED','host_rejections':rejected,
                              'binding':self._answer_binding(db,actor,task,answers)}
            entries=task.setdefault('verified_need_answers',{})
            if task.get('agent_contract')=='obligation-v1':
                registry=task.setdefault('semantic_rejections',{})
                effective={r['need_id']:r for r in per_need}
                for item in answers:
                    coverage=task.get('goal_coverage') or {}
                    original_refs=[o['id'] for o in (task.get('goal_contract') or {}).get('obligations',[])
                        if o['need_id']==item['need_id'] or any(r['obligation_id']==o['id'] and item['need_id'] in r.get('represented_need_ids',[])
                            for r in coverage.get('obligations',[]))]
                    key=digest({'body':item['answer'],'original_obligations':sorted(original_refs) or [item['need_id']],
                        'original_goal':task.get('goal_contract') or task['task_goal'],
                        'facts':task['facts'],'fact_sources':task.get('fact_sources'),
                        'auth':self.auth_digest(actor),'judge':task.get('runtime_fingerprint'),
                        'citations':item['citations'],
                        'sources':{r:{k:e.get(k) for k in ('text','document_id','version_id','index_run_id','source_path','invalidated_by')}
                            for r,e in task.get('knowledge',{}).items()},
                        'checked_queries':sorted({encoded({k:q.get(k) for k in ('query','mode','index_binding','hit_count','scope')})
                            for q in task.get('search_receipts',{}).values()})})
                    nid=item['need_id']; verdict=effective.get(nid,{}).get('verdict')
                    if verdict in {'unsupported','review_uncertain'} or nid in assessment['unsupported_need_ids']:
                        registry.setdefault(key,{'need_id':nid,'candidate_sha256':digest(item),
                            'verdict':verdict or 'unsupported','reason':effective.get(nid,{}).get('reason',assessment['reason'])})
                    if key in registry:
                        effective[nid]={'need_id':nid,'verdict':registry[key]['verdict'],'reason':registry[key]['reason']}
                        if registry[key]['verdict']=='unsupported' and nid not in assessment['unsupported_need_ids']:
                            assessment['unsupported_need_ids'].append(nid)
                        if nid in entries and entries[nid]['answer']==item: entries.pop(nid)
                        if verdict=='supported':self._event(db,task_id,'semantic_rejection_reaffirmed',{'key':key,'need_id':nid})
                per_need=list(effective.values());assessment['need_assessments']=per_need
            reviews={r['need_id']:r for r in per_need}
            raw_reviews={r['need_id']:r for r in assessment.get('need_reviews',[])}
            import hashlib
            for answer in answers:
                reviewed=raw_reviews.get(answer['need_id'],{}).get('reviewed_answer_sha256')
                if reviewed and reviewed!=hashlib.sha256(answer['answer'].encode('utf-8')).hexdigest():
                    raise ServiceError('RESOURCE_CHANGED')
            for answer in answers:
                nid=answer['need_id']
                supported=reviews.get(nid,{}).get('verdict','supported')=='supported'
                dimensions_ok=bool(per_need) or (assessment['faithful_to_source']
                    and assessment['preserves_numbers_entities_negation_conditions'])
                if (supported and dimensions_ok and (assessment['covers_user_needs'] or task.get('semantic_review_contract')=='source-plan-v2'
                    or task.get('agent_contract')=='obligation-v1')
                    and nid not in assessment['unsupported_need_ids']):
                    entries[nid]={'answer':answer,'binding':self._need_binding(db,actor,task,answer),
                        'reason':reviews.get(nid,{}).get('reason',assessment['reason']),'review':raw_reviews.get(nid),
                        'review_context':self._review_context(task,answer)}
            cached=self._cached_delivery(db,actor,task)
            if cached:
                merged={a['need_id']:a for a in answers}; merged.update({a['need_id']:a for a in cached['answers']})
                task['delivery']['answers']=[merged[n['id']] for n in task['task_goal']['needs'] if n['id'] in merged]
                effective={r['need_id']:r for r in per_need}
                effective.update({r['need_id']:r for r in cached['assessment']['need_assessments']})
                assessment['need_assessments']=list(effective.values())
                # The cached body overrides a new draft; its exact fresh proof must follow it.
                proof_by_need={r['need_id']:r for r in assessment.get('need_reviews',[])}
                proof_by_need.update({r['need_id']:r for r in cached['assessment'].get('need_reviews',[])})
                assessment['need_reviews']=[proof_by_need[n['id']] for n in task['task_goal']['needs']
                    if n['id'] in proof_by_need]
                assessment['unsupported_need_ids']=[n for n in assessment['unsupported_need_ids'] if n not in entries]
                task['delivery']['host_rejections']=[r for r in rejected if r['need_id'] not in entries]
                task['delivery']['binding']=self._answer_binding(db,actor,task,task['delivery']['answers'])
            self._save(db,task)
            self._event(db,task_id,'delivery_assessed',task['delivery'])
        return self.get_task(actor,task_id)

    def bind_goal_coverage(self,actor,task_id,expected,raw,*,expected_context=None):
        from app.service_desk.goals import goal_coverage_key,goal_review_context_key,validate_goal_coverage
        with self.transaction() as db:
            task=self._task(db,actor,task_id);self._live(task)
            if expected!=goal_coverage_key(task):raise ServiceError('RESOURCE_CHANGED')
            if expected_context is not None and expected_context!=goal_review_context_key(task):
                raise ServiceError('RESOURCE_CHANGED')
            task['goal_coverage']=validate_goal_coverage(task,raw)
            self._save(db,task)
            self._event(db,task_id,'original_goal_reviewed',task['goal_coverage'])
        return self.get_task(actor,task_id)

    def feedback_unfinished(self,actor,task_id,expected):
        """Repair feedback is not a published outcome or a permission to act."""
        progress=self.finish_goal(actor,task_id,_probe=True)
        with self.transaction() as db:
            task=self._task(db,actor,task_id);self._live(task)
            delivery=task.get('delivery') or {}
            if expected!=delivery.get('binding'):raise ServiceError('RESOURCE_CHANGED')
            from app.service_desk.delivery import unapproved_draft_views
            drafts=unapproved_draft_views(task,[a for a in delivery.get('answers',[])
                if a['need_id'] in progress['withheld_need_ids']])
            task['observations'].append({'tool':'host.assessment','result':{
                'status':'error','error_code':'GOAL_NOT_COMPLETE','retryable':False,
                'missing_outputs':sorted(set(task['task_goal']['required_outputs'])-set(progress['completed_outputs'])),
                'missing_need_ids':progress['withheld_need_ids'],
                'review_feedback':delivery.get('assessment'),
                'unapproved_draft_answers':drafts,
                'instruction':('Retain verified knowledge answers. Continue the missing business outputs using actual tools; '
                    'knowledge review is not approval of business actions. Exact user confirmation is still required. No result has been published.'
                    if not progress['withheld_need_ids'] and not progress['coverage_issues'] else
                    'Repair only unresolved original needs using actual evidence; approved body is retained. No result has been published.')}})
            self._save(db,task)
            self._event(db,task_id,'repair_requested',{'binding':expected,'publication':'NONE'})

    def continue_unfinished(self, actor, task_id, run_id):
        with self.transaction() as db:
            task=self._task(db,actor,task_id)
            if task['status']!='BLOCKED' or task['last_error']!='GOAL_NOT_COMPLETE':
                raise ServiceError('NOT_CONTINUABLE')
            self._live({**task,'active_run_id':run_id})
            missing=set(task['task_goal']['required_outputs'])-set(task['outcome']['completed_outputs'])
            task['observations'].append({'tool':'host.finish','result':{'status':'error','error_code':'GOAL_NOT_COMPLETE',
                'missing_outputs':sorted(missing),'needs':task['task_goal'].get('needs',[]),
                'missing_need_ids':task['outcome'].get('withheld_need_ids',[]),
                'review_feedback':(task.get('delivery') or {}).get('assessment'),
                'instruction':'Resolve the specific missing output. Repeating empty finish cannot create an answer.'}})
            task.update(status='RUNNING',active_run_id=run_id)
            self._save(db,task)
        return task

    def cancel_task(self, actor, task_id):
        with self.transaction() as db:
            task = self._task(db, actor, task_id)
            committed = db.execute(f'SELECT ticket_id FROM {self.ticket_table(task)} WHERE task_id=?', (task_id,)).fetchone()
            if committed:
                raise ServiceError('ALREADY_SUBMITTED', data={'ticket_id':committed['ticket_id']})
            task.update(status='CANCELLED', active_run_id=None)
            self._save(db, task)
            self._event(db, task_id, 'cancelled', {})
            return task

    def diagnostic_records(self, actor, task_id, *, event_limit=256):
        """Read an authorized consistent snapshot; never invalidate or execute a task."""
        if type(event_limit) is not int or not 1 <= event_limit <= 256:
            raise ServiceError('INVALID_ARGUMENTS')
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2,isolation_level=None)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            task=self._task(db,actor,task_id)
            if task.get('owner')!=actor.subject or task.get('tenant')!=actor.tenant_id:
                raise ServiceError('AUTH_DENIED')
            rows=db.execute('SELECT seq,task_id,kind,payload,created_at FROM task_events WHERE task_id=? ORDER BY seq LIMIT ?',
                            (task_id,event_limit+1)).fetchall()
            events=[{**dict(r),'payload':json.loads(r['payload'])} for r in rows[:event_limit]]
            tickets=[dict(r) for r in db.execute(
                'SELECT ticket_id,command_id,status,version FROM tickets WHERE task_id=? AND tenant=? AND owner=? LIMIT 2',
                (task_id,actor.tenant_id,actor.subject))]
            commands=[]
            for ticket in tickets:
                commands.extend(dict(r) for r in db.execute(
                    'SELECT command_id,content_digest FROM command_ledger WHERE command_id=?',(ticket['command_id'],)))
            confirmations=[dict(r) for r in db.execute(
                'SELECT c.proposal_id,c.content_digest,c.accepted,c.created_at FROM confirmations c '
                'JOIN action_proposals p ON p.proposal_id=c.proposal_id WHERE p.task_id=? LIMIT 64',(task_id,))]
            return {'task':task,'events':events,'events_truncated':len(rows)>event_limit,
                    'tickets':tickets,'commands':commands,'confirmations':confirmations}
        finally:db.close()

    def events(self, actor, task_id):
        with self.transaction() as db:
            self._task(db, actor, task_id)
            return [{**dict(r),'payload':json.loads(r['payload'])} for r in db.execute(
                'SELECT * FROM task_events WHERE task_id=? ORDER BY seq', (task_id,))]

    def dump(self):
        """Test/operator projection; deliberately not exposed as an HTTP endpoint."""
        with self.transaction() as db:
            return {table:[dict(r) for r in db.execute('SELECT * FROM '+table)]
                    for table in ('agent_tasks','task_events','tickets','assets','repairs','loan_rules',
                                  'action_proposals','confirmations','command_ledger','ticket_events')}
