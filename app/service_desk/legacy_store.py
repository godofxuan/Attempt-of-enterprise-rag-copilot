"""Explicit historical semantic-task operations, loaded only when invoked.

The current guided product uses the shared KnowledgeService and domain methods.
These methods are moved verbatim, not a second copy of business rules.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
import hashlib,json,sqlite3,time
from pathlib import Path
from uuid import uuid4
from .store import ServiceError,encoded,digest,_RUN_OWNER

class LegacyTaskOperations:
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

