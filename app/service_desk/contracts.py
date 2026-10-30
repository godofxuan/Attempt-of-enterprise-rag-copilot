from datetime import date, timedelta
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class UserFacts(Strict):
    loan_start: date | None = None
    loan_end: date | None = None
    purpose: str | None = Field(default=None,min_length=1,max_length=1000)
    min_memory_gb: int | None = Field(default=None,ge=1,le=256,strict=True)
    pickup_location: str | None = Field(default=None,min_length=1,max_length=100)
    date_flex_days: int | None = Field(default=None,ge=0,le=7,strict=True)


class RepairFacts(Strict):
    asset_id: str | None = Field(default=None,min_length=1,max_length=128)
    description: str | None = Field(default=None,min_length=1,max_length=1000)
    impact: Literal['low','medium','high'] | None = None


class GuidedTaskRequest(Strict):
    kind: Literal['loan','repair','knowledge']
    execution_ceiling: Literal['READ_ONLY','PREVIEW_ONLY','SUBMIT_AFTER_CONFIRMATION']='READ_ONLY'
    facts: UserFacts | RepairFacts=Field(default_factory=UserFacts)
    question: str | None=Field(default=None,min_length=1,max_length=600)
    confirmed: bool=Field(strict=True)

    @model_validator(mode='after')
    def explicit_range(self):
        if self.confirmed is not True:raise ValueError('USER_TASK_CONFIRMATION_REQUIRED')
        if self.kind=='knowledge':
            if not self.question or not self.question.strip() or self.execution_ceiling!='READ_ONLY' or self.facts.model_dump(exclude_none=True):
                raise ValueError('KNOWLEDGE_REQUEST_REQUIRES_ONLY_EXPLICIT_QUESTION')
        elif self.question is not None:raise ValueError('SERVICE_TASK_DOES_NOT_ADD_KNOWLEDGE_NEEDS')
        schema=RepairFacts if self.kind=='repair' else UserFacts
        self.facts=schema.model_validate(self.facts.model_dump(exclude_none=True))
        return self


def canonical_parameters(values, version='literal-v1'):
    """A comparison view, never a mutation of a historical payload or confirmation."""
    result=dict(values)
    if version=='literal-v1': return result
    if version!='purpose-connector-v1': raise ValueError('UNKNOWN_PARAMETER_NORMALIZER')
    purpose=result.get('purpose')
    if isinstance(purpose,str):
        text=purpose.strip()
        # Only an initial grammatical connector; preserve qualifiers and negation.
        connector=r'^(?:\u7528\u4e8e|\u7528\u6765|(?i:for)\s+)(.+)$'
        match=re.match(connector,text)
        remainder=match.group(1).strip() if match else text
        # Repeated connectors are ambiguous; do not erase another layer on comparison.
        result['purpose']=(remainder if match and not re.match(connector,remainder) else text) or purpose
    return result


def parameter_sources(values, sources, version):
    canonical=canonical_parameters(values,version)
    return canonical,{key:{**sources.get(key,{}),'raw_value':raw,
        'canonical_value':canonical[key],'normalizer_version':version}
        for key,raw in values.items()}


def parameter_differences(stored, requested, version='literal-v1'):
    left,right=canonical_parameters(stored,version),canonical_parameters(requested,version)
    return [key for key in ('loan_start','loan_end','purpose') if left.get(key)!=right.get(key)]


class Empty(Strict):
    pass


class Search(Strict):
    query: str = Field(min_length=1,max_length=1000)


class KnowledgeAnswer(Strict):
    need_id: str = Field(min_length=1,max_length=40)


class Read(Strict):
    evidence_ref: str = Field(min_length=1,max_length=128)


class Find(Read):
    pattern: str = Field(min_length=1,max_length=500)


class Open(Strict):
    navigation_ref: str = Field(min_length=1,max_length=128)


class Get(Strict):
    ticket_ref: str = Field(min_length=1,max_length=128)


class Propose(Strict):
    asset_id: str = Field(min_length=1,max_length=128)
    evidence_refs: list[str] = Field(min_length=1,max_length=8)


TOOL_SCHEMAS = {'knowledge.search':Search, 'knowledge.read':Read, 'assets.search':Empty,
                'knowledge.answer':KnowledgeAnswer,
                'knowledge.find':Find,'knowledge.open':Open,
                'tickets.list_mine':Empty, 'tickets.get':Get, 'tickets.propose_create':Propose}


class NextAction(Strict):
    kind: Literal['tool','ask_user','finish','deliver','reframe']
    tool: str | None = None
    arguments: dict = Field(default_factory=dict)
    missing_fields: list[Literal['loan_start','loan_end','purpose','ticket_ref','goal_subject','execution_scope']] = Field(default_factory=list,max_length=5)
    answers: list[dict] = Field(default_factory=list,max_length=8)
    reason: Literal['goal_observation_mismatch','unsupported_capability','user_clarification'] | None = None

    @model_validator(mode='after')
    def validate_action_contract(self):
        """Reject incomplete/mixed actions at the same boundary used by calibration.

        This validates shape and tool arguments, not whether an action is a good
        decision for a particular task. Authorization remains in the host gateway.
        """
        if self.kind!='reframe' and self.reason is not None: raise ValueError('reason is only for reframe')
        if self.kind=='reframe':
            if self.reason is None or self.tool or self.arguments or self.answers or self.missing_fields:
                raise ValueError('reframe requires only a reason')
            return self
        if self.kind!='deliver' and self.answers:
            raise ValueError('Answers belong only to deliver')
        if self.kind == 'deliver':
            from app.service_desk.delivery import NeedAnswer,SpanAnswer
            if self.tool is not None or self.arguments or self.missing_fields or not self.answers:
                raise ValueError('deliver requires per-need answers only')
            self.answers=[(SpanAnswer if 'span_refs' in a else NeedAnswer).model_validate(a).model_dump(exclude_unset=True) for a in self.answers]
        elif self.kind == 'tool':
            if self.tool not in TOOL_SCHEMAS or self.missing_fields:
                raise ValueError('Tool actions require a registered tool and no missing_fields')
            self.arguments = TOOL_SCHEMAS[self.tool].model_validate(
                self.arguments, strict=True
            ).model_dump()
        elif self.kind == 'ask_user':
            if self.tool is not None or self.arguments or not self.missing_fields:
                raise ValueError('ask_user requires missing_fields and no tool arguments')
            if len(set(self.missing_fields)) != len(self.missing_fields):
                raise ValueError('missing_fields must be unique')
        elif self.tool is not None or self.arguments or self.missing_fields:
            raise ValueError('finish cannot contain a tool, arguments, or missing_fields')
        return self

    @classmethod
    def model_json_schema(cls, **kwargs):
        schema = super().model_json_schema(**kwargs)
        branches=[]
        for tool,args in TOOL_SCHEMAS.items():
            branches.append({'type':'object','properties':{'kind':{'const':'tool'},'tool':{'const':tool},
                'arguments':args.model_json_schema(),'missing_fields':{'type':'array','maxItems':0}},
                'required':['kind','tool','arguments'],'additionalProperties':False})
        branches.extend([
            {'type':'object','properties':{'kind':{'const':'ask_user'},'missing_fields':{
                'type':'array','items':{'enum':['loan_start','loan_end','purpose','ticket_ref','goal_subject','execution_scope']},
                'minItems':1,'maxItems':5,'uniqueItems':True}},'required':['kind','missing_fields'],'additionalProperties':False},
            {'type':'object','properties':{'kind':{'const':'finish'}},'required':['kind'],'additionalProperties':False}])
        schema['oneOf']=branches
        return schema


def empty_finish_is_invalid(view):
    terminal = view.get('status') in {'CANCELLED','WAITING_CONFIRMATION','COMPLETED','WAITING_EXTERNAL'}
    knowledge='policy_answer' in view.get('task_goal',{}).get('required_outputs',[])
    pending_boundary=(view.get('goal_kind')=='unsupported_action' and bool(view.get('missing_need_ids')))
    return not terminal and knowledge and (pending_boundary or view.get('goal_kind') not in {'unknown','unsupported_action'})


def business_finish_is_available(view):
    if view.get('status') in {'CANCELLED','WAITING_CONFIRMATION','COMPLETED','WAITING_EXTERNAL'}:
        return True
    outputs=set(view.get('task_goal',{}).get('required_outputs',[]))
    if not outputs.intersection({'open_application','ticket_status','asset_status'}):
        return True
    fresh=view.get('fresh_business_reads',{})
    if view.get('agent_contract')=='obligation-v1' and 'fresh_business_reads' in view:
        current_ticket=bool(fresh.get('tickets.get'))
        if 'asset_status' in outputs and 'assets.search' not in fresh:return False
        if 'ticket_status' in outputs and not current_ticket and 'tickets.list_mine' not in fresh:return False
        if 'open_application' in outputs and view.get('goal_kind')=='submit_loan' and not current_ticket:
            if 'assets.search' not in fresh:return False
            inventory=next((o['result'].get('data',{}) for o in reversed(view.get('observations',[]))
                if o.get('tool')=='assets.search' and o.get('result',{}).get('status')=='ok'),{})
            available=any(a.get('category')=='laptop' and a.get('available')==1
                for a in inventory.get('assets',[]))
            if available and (inventory.get('repair') or {}).get('active'):return False
    if (view.get('agent_contract')=='obligation-v1' and 'assets.search' in fresh
        and {'open_application','ticket_status'}.issubset(outputs)):
        inventory=next((o['result'].get('data',{}) for o in reversed(view.get('observations',[]))
            if o.get('tool')=='assets.search' and o.get('result',{}).get('status')=='ok'),{})
        if not inventory.get('assets') or not (inventory.get('repair') or {}).get('active'):
            # A blocked write does not resolve the user's independent owned-record request.
            empty_query=fresh.get('tickets.list_mine',{}).get('count')==0
            if not empty_query and not fresh.get('tickets.get'):
                return False
    for observation in view.get('observations',[]):
        result=observation.get('result',{})
        if result.get('status')!='ok': continue
        if observation['tool']=='tickets.get': return True
        if observation['tool']=='assets.search' and 'asset_status' in outputs: return True
        if observation['tool']=='assets.search' and 'open_application' in outputs:
            data=result['data']
            if not data.get('assets') or not (data.get('repair') or {}).get('active'): return True
        if observation['tool']=='tickets.list_mine' and 'ticket_status' in outputs and not result['data'].get('tickets'):
            return True
    return False


def peer_pending_need_ids(view):
    if not view.get('knowledge_peer'):return set()
    delivery=view.get('delivery') or {}
    retained=set(delivery.get('retained_need_ids',[]))
    stale={r['need_id'] for r in delivery.get('need_assessments',[])
        if r['verdict']=='review_uncertain' and r['need_id'] in retained}
    # Invalidated peer bytes may enter the same preparation/review path. This
    # makes no stale approval current and does not satisfy any missing need.
    stale.update(row['answer']['need_id'] for row in view.get('retained_drafts',[])
        if row.get('trust')=='STALE_DRAFT_REQUIRES_FULL_REVALIDATION')
    # A source-context change needs current review of retained bytes, not new generation.
    candidates=view.get('peer_answer_candidates',{})
    ready={nid for nid,row in candidates.items() if row.get('retry_ready')}
    return (set(view.get('missing_need_ids',[]))-set(candidates)-stale)|ready


def delivery_need_ids(view):
    all_ids=[n['id'] for n in view.get('task_goal',{}).get('needs',[])]
    missing=view.get('missing_need_ids')
    selected=missing if (view.get('semantic_review_contract')=='source-plan-v2' or view.get('agent_contract')=='obligation-v1') and missing is not None else all_ids
    pending=peer_pending_need_ids(view)
    return [nid for nid in selected if nid not in pending]


def proposal_requires_owned_query(value):
    goal=value.get('task_goal',{})
    from app.service_desk.goals import user_structured_goal
    if user_structured_goal(value):return 'ticket_status' in goal.get('required_outputs',[])
    return (value.get('agent_contract')=='obligation-v1'
        and 'ticket_status' in goal.get('required_outputs',[])
        and not goal.get('ticket_ref')
        and any(unit.get('intent')=='lookup' for unit in goal.get('request_units',[])))


def evaluate_owned_condition(task, condition, current_receipt):
    """Evaluate only registered predicates over a host-validated current receipt."""
    predicate=condition.get('predicate')
    if predicate not in {'owned_matching_present','owned_matching_absent'}:
        raise ValueError('UNREGISTERED_CONDITION')
    facts=task.get('facts',{})
    if (not current_receipt or current_receipt.get('status')!='success'
        or any(not facts.get(f) for f in ('loan_start','loan_end','purpose'))):
        return {'value':'UNKNOWN','predicate':predicate,'matching_ticket_ids':[]}
    tickets=current_receipt.get('tickets')
    if not isinstance(tickets,list):
        return {'value':'UNKNOWN','predicate':predicate,'matching_ticket_ids':[]}
    matches=[t['ticket_id'] for t in tickets
        if t.get('status') in {'PENDING_APPROVAL','IN_PROGRESS','RESERVED','CHECKED_OUT'}
        and not parameter_differences(t.get('parameters',{}),facts,
            task.get('parameter_normalizer','literal-v1'))]
    truth=bool(matches) if predicate=='owned_matching_present' else not matches
    return {'value':'TRUE' if truth else 'FALSE','predicate':predicate,
        'matching_ticket_ids':matches,'query_event_seq':current_receipt.get('query_event_seq')}


def parse_action(raw, view):
    value=NextAction.model_validate(raw)
    wire=action_schema(view)
    branches=wire.get('oneOf',[wire])
    branch=next((b for b in branches if b['properties']['kind']['const']==value.kind
                 and (value.kind!='tool' or b['properties']['tool']['const']==value.tool)),None)
    if branch is None:
        raise ValueError('This action is not available in the current wire contract')
    if not set(branch['required']).issubset(raw) or not set(raw).issubset(branch['properties']):
        raise ValueError('Use only the declared fields of the selected action branch')
    if value.kind=='tool':
        excluded=branch['properties']['arguments'].get('not',{}).get('enum',[])
        if value.arguments in excluded:
            raise ValueError('The host observed no new information from these unchanged arguments; choose a useful action')
        for name,schema in branch['properties']['arguments'].get('properties',{}).items():
            supplied=value.arguments.get(name)
            if 'enum' in schema and supplied not in schema['enum']:
                raise ValueError('Use an observed or literal user-supplied identifier from the wire contract')
            if 'enum' in schema.get('items',{}) and any(item not in schema['items']['enum'] for item in supplied or []):
                raise ValueError('Use admitted authoritative source references from the wire contract')
    if value.kind=='finish' and empty_finish_is_invalid(view):
        raise ValueError('An empty finish cannot answer knowledge needs. Search if needed, then use deliver with per-need answers and citations.')
    if value.kind=='ask_user' and not set(value.missing_fields).issubset(set(view['missing_fields'])):
        raise ValueError('Ask only currently missing user facts')
    if value.kind=='tool' and value.tool=='tickets.propose_create' and view['goal_kind']!='submit_loan':
        raise ValueError('Current goal does not authorize an application proposal')
    from app.service_desk.goals import execution_ceiling
    if value.kind=='tool' and value.tool=='tickets.propose_create' and execution_ceiling(view)=='READ_ONLY':
        raise ValueError('Current execution ceiling prohibits preparing an application')
    if value.kind=='deliver' and not view.get('task_goal',{}).get('needs'):
        raise ValueError('No parsed knowledge needs to deliver')
    if value.kind=='deliver' and view.get('compact_understanding'):
        ids=[a['need_id'] for a in value.answers]
        if len(ids)!=len(set(ids)) or len(ids)>len(delivery_need_ids(view)):
            raise ValueError('Deliver a nonempty unique subset of currently available needs')
        needs={n['id']:n for n in view['task_goal']['needs']}
        if (view.get('semantic_review_contract')=='source-plan-v2' or view.get('agent_contract')=='obligation-v1') and any(
            a.get('need_id') not in delivery_need_ids(view) for a in value.answers):
            raise ValueError('Deliver only currently missing needs')
        for answer in value.answers:
            if answer['need_id'] in needs and not answer.get('target'):
                from app.service_desk.goals import need_target
                answer['target']=need_target(view,needs[answer['need_id']])
    if value.kind=='deliver' and view.get('protocol')=='service-v3':
        for answer in value.answers:
            if 'span_refs' not in answer: raise ValueError('Use host span handles, not model-authored quotes')
            if view.get('agent_contract')!='obligation-v1' and answer.get('answer_disposition')=='explicitly_unspecified':
                raise ValueError('DISPOSITION_NOT_AVAILABLE')
        # Source/scope checks are per-need in prepare_delivery; rejected needs cannot publish.
    if value.tool=='knowledge.read' and 'knowledge' in view:
        if value.arguments['evidence_ref'] not in {e['ref'] for e in view['knowledge']+view.get('evidence_catalog',[])}:
            raise ValueError('Use an admitted evidence ref, not a chunk/document ID')
    if view.get('status') in {'CANCELLED','WAITING_CONFIRMATION','PREVIEW_READY','COMPLETED','WAITING_EXTERNAL'}:
        if value.kind!='finish': raise ValueError('No model tool action in this state')
    return value


def action_schema(view):
    """The wire grammar uses the same branch/state permissions as parse_action."""
    branches=[]
    admitted=view.get('knowledge',[])+view.get('evidence_catalog',[])
    refs=list(dict.fromkeys(e['ref'] for e in admitted))
    visible_complete={e['ref'] for e in view.get('knowledge',[]) if any(
        s.get('span_ref')==e['ref']+'.S1' and s.get('text') for s in e.get('spans',[]))}
    readable=[ref for ref in refs if view.get('agent_contract')!='obligation-v1' or ref not in visible_complete]
    policy_refs=list(dict.fromkeys(e['ref'] for e in admitted if e.get('need_refs')==['loan_policy']))
    peer_pending=peer_pending_need_ids(view)
    business_policy_pending=('open_application' in view.get('task_goal',{}).get('required_outputs',[])
                             and not set(policy_refs).intersection(visible_complete))
    delivery=view.get('delivery') or {}
    need_ids={n['id'] for n in view.get('task_goal',{}).get('needs',[])}
    approved={r['need_id'] for r in delivery.get('need_assessments',[]) if r['verdict']=='supported'}
    # Pure business goals need the registered policy, not another knowledge answer.
    business_outputs=set(view.get('task_goal',{}).get('required_outputs',[]))
    application_policy_ready=(not need_ids
        and 'open_application' in business_outputs
        and business_outputs.issubset({'open_application','asset_status','ticket_status'})
        and bool(set(policy_refs).intersection(visible_complete)))
    from app.service_desk.goals import goal_mapping_complete,user_structured_goal
    knowledge_answers_done=(view.get('agent_contract')=='obligation-v1' and (bool(need_ids) or application_policy_ready)
        and view.get('missing_need_ids')==[] and need_ids.issubset(set(delivery.get('retained_need_ids',[])))
        and need_ids.issubset(approved) and goal_mapping_complete(view))
    knowledge_done=(knowledge_answers_done
        and ('open_application' not in view.get('task_goal',{}).get('required_outputs',[]) or bool(policy_refs)))
    ticket_ids=[]
    if view.get('task_goal',{}).get('ticket_ref'): ticket_ids.append(view['task_goal']['ticket_ref'])
    for observed in view.get('observations',[]):
        data=observed.get('result',{}).get('data',{})
        if isinstance(data,dict):
            ticket_ids.extend(t['ticket_id'] for t in data.get('tickets',[]))
            if data.get('ticket_id'): ticket_ids.append(data['ticket_id'])
    ticket_ids=list(dict.fromkeys(ticket_ids))
    fresh=view.get('fresh_business_reads',{}) if view.get('agent_contract')=='obligation-v1' else {}
    ticket_ids=[ref for ref in ticket_ids if ref not in fresh.get('tickets.get',[])]
    terminal=view.get('status') in {'CANCELLED','WAITING_CONFIRMATION','PREVIEW_READY','COMPLETED','WAITING_EXTERNAL'}
    from app.service_desk.goals import execution_ceiling
    for branch in NextAction.model_json_schema()['oneOf']:
        props=branch['properties']; kind=props['kind']['const']
        if user_structured_goal(view) and kind=='tool':
            name=props['tool']['const']
            if name.startswith('knowledge.') and not business_outputs.intersection({'policy_answer','open_application'}):continue
            if not name.startswith('knowledge.') and business_outputs=={'policy_answer'}:continue
        if kind=='tool' and props['tool']['const']=='knowledge.answer':
            if not peer_pending:continue
            props['arguments']['properties']['need_id']['enum']=[
                nid for nid in view['missing_need_ids'] if nid in peer_pending]
        if (peer_pending and kind=='tool' and props['tool']['const'] in
            {'knowledge.search','knowledge.read','knowledge.find','knowledge.open'}
            and not business_policy_pending):continue
        if kind=='tool' and knowledge_done and props['tool']['const'].startswith('knowledge.'):continue
        if (kind=='tool' and knowledge_answers_done and not knowledge_done
            and props['tool']['const'].startswith('knowledge.')
            and props['tool']['const']!='knowledge.search'):continue
        if kind=='tool' and props['tool']['const'] in {'knowledge.find','knowledge.open'} and view.get('agent_contract')!='obligation-v1':continue
        if kind=='tool' and props['tool']['const'] in {'assets.search','tickets.list_mine','tickets.propose_create'} and props['tool']['const'] in fresh:continue
        if terminal and kind!='finish': continue
        if view.get('protocol')=='service-v3' and kind=='tool':
            goal=view.get('goal_kind')
            mixed_knowledge=('policy_answer' in view.get('task_goal',{}).get('required_outputs',[])
                and bool(view.get('task_goal',{}).get('needs')))
            if goal=='unknown': continue
            if goal=='unsupported_action' and (not mixed_knowledge or not props['tool']['const'].startswith('knowledge.')): continue
        if kind=='finish' and empty_finish_is_invalid(view): continue
        if kind=='finish' and not business_finish_is_available(view): continue
        if kind=='ask_user':
            if not view.get('missing_fields'): continue
            props['missing_fields']['items']['enum']=list(view['missing_fields'])
        if kind=='tool' and props['tool']['const']=='tickets.propose_create' and (view.get('goal_kind')!='submit_loan' or execution_ceiling(view)=='READ_ONLY'): continue
        if (kind=='tool' and props['tool']['const']=='tickets.propose_create'
            and view.get('agent_contract')=='obligation-v1' and 'fresh_business_reads' in view
            and 'assets.search' not in fresh):continue
        if (kind=='tool' and props['tool']['const']=='tickets.propose_create'
            and proposal_requires_owned_query(view) and 'tickets.list_mine' not in fresh):continue
        if kind=='tool' and 'knowledge' in view:
            name=props['tool']['const']
            arguments=props['arguments']['properties']
            # Peer attempts are fenced by current receipt binding above; old
            # progress observations must not prevent a newly invalidated need.
            if name.startswith('knowledge.') and name!='knowledge.answer' and view.get('agent_contract')=='obligation-v1':
                exhausted=[]
                for observation in view.get('observations',[]):
                    if observation.get('tool')!='host.progress':continue
                    data=observation.get('result',{}).get('data',{})
                    action=data.get('unchanged_action',{})
                    if action.get('tool')==name and data.get('known_result',{}).get('status')=='ok':
                        exhausted.append(action['arguments'])
                if exhausted:
                    props['arguments']['not']={'enum':exhausted}
            if name in {'knowledge.read','knowledge.find'}:
                available=readable if name=='knowledge.read' else refs
                if not available: continue
                arguments['evidence_ref']['enum']=available
            if name=='knowledge.open':
                targets=list(view.get('navigation_targets',{}))
                if not targets:continue
                arguments['navigation_ref']['enum']=targets
            if name=='tickets.propose_create':
                eligible=policy_refs
                if not eligible: continue
                arguments['evidence_refs']['items']={'type':'string','enum':eligible}
                if view.get('agent_contract')=='obligation-v1':
                    assets=list(dict.fromkeys(a['asset_id'] for a in view.get('observed_asset_options',[])))
                    if not assets:continue
                    arguments['asset_id']['enum']=assets
            if name=='tickets.get':
                if not ticket_ids: continue
                arguments['ticket_ref']['enum']=ticket_ids
        branches.append(branch)
    reframe_basis=True
    if view.get('routing_contract')=='request-outcomes-visible-v11' and view.get('agent_contract')=='obligation-v1':
        coverage=view.get('goal_coverage') or {}
        need_ids={n['id'] for n in view.get('task_goal',{}).get('needs',[])}
        delivery=view.get('delivery') or {}
        supported={r['need_id'] for r in delivery.get('need_assessments',[]) if r['verdict']=='supported'}
        knowledge_retained=(bool(need_ids) and view.get('missing_need_ids')==[]
            and coverage.get('complete') is True
            and need_ids.issubset(set(delivery.get('retained_need_ids',[])))
            and need_ids.issubset(supported))
        unassessed_knowledge=(bool(need_ids) and not delivery.get('need_assessments')
            and not delivery.get('host_rejections') and not view.get('semantic_rejections'))
        outputs=set(view.get('task_goal',{}).get('required_outputs',[]))
        obligations=view.get('goal_contract',{}).get('obligations',[])
        represented={row['obligation_id'] for row in coverage.get('obligations',[])
            if row.get('verdict')=='represented' and 'obligation_id' in row}
        # A successful read changes business state, not an already-preserved intake.
        business_goal_preserved=(not need_ids and bool(outputs) and bool(obligations)
            and outputs.issubset({'open_application','ticket_status','asset_status'})
            and {o['output'] for o in obligations}==outputs
            and {o['id'] for o in obligations}.issubset(represented)
            and coverage.get('complete') is True)
        reframe_basis=bool(coverage.get('issues') or coverage.get('unmapped_need_ids') or any(
            row.get('verdict') in {'missing','scope_unresolved'} for row in coverage.get('obligations',[]))) or (
            not knowledge_retained and not business_goal_preserved and not unassessed_knowledge and any(
            o.get('tool') in {'assets.search','tickets.list_mine','tickets.get'}
            and o.get('tool') in fresh and o.get('result',{}).get('status')=='ok'
            for o in view.get('observations',[])))
    if (not user_structured_goal(view) and not terminal and view.get('protocol')=='service-v3' and not view.get('understanding_pending')
        and view.get('reframe_count',0)<view.get('reframe_limit',1) and reframe_basis):
        reasons=['goal_observation_mismatch','unsupported_capability','user_clarification']
        if (view.get('routing_contract')=='request-outcomes-visible-v11'
            and view.get('agent_contract')=='obligation-v1'
            and not any(m['id']!='initial' for m in view.get('messages',[]))):
            reasons.remove('user_clarification')
        branches.append({'type':'object','properties':{'kind':{'const':'reframe'},'reason':{'enum':reasons}},
            'required':['kind','reason'],'additionalProperties':False})
    if not terminal and delivery_need_ids(view) and (view.get('knowledge') or view.get('search_receipts')):
        from app.service_desk.delivery import NeedAnswer,SpanAnswer
        from app.service_desk.understanding import inline_schema
        modern=view.get('protocol')=='service-v3'
        answer_schema=inline_schema(SpanAnswer if modern else NeedAnswer)
        if modern and view.get('agent_contract')!='obligation-v1':
            answer_schema['properties']['answer_disposition']['enum'].remove('explicitly_unspecified')
        elif modern:
            answer_schema['properties']['answer_disposition']['enum'].remove('unsupported_action')
        from app.service_desk.goals import response_language
        answer_schema['properties']['answer']['description'] = (
            'User-facing answer in Chinese. Keep literal commands, identifiers and citations unchanged.'
            if response_language(view.get('goal',''))=='zh' else
            'User-facing answer in the language of the original user request. Preserve literal commands and identifiers.')
        answer_schema['properties']['need_id']['enum']=delivery_need_ids(view)
        if modern:
            spans=[s['span_ref'] for e in view['knowledge'] for s in e['spans']]
            receipts=list(view.get('search_receipts',{}))
            for field,handles in (('span_refs',spans),('search_receipts',receipts)):
                prop=answer_schema['properties'][field]
                prop['items']={'type':'string',**({'enum':handles} if handles else {})}
                if not handles:prop['maxItems']=0
            answer_schema['properties']['evidence_scope']={'const':view['evidence_scope']}
            from copy import deepcopy
            variants=[]
            for need in view['task_goal']['needs']:
                variant=deepcopy(answer_schema)
                variant['properties']['need_id']={'const':need['id']}
                from app.service_desk.goals import need_target
                variant['properties']['target']={'const':need_target(view,need)}
                variant['required']=list(dict.fromkeys(variant['required']+['target']))
                variants.append(variant)
            if view.get('compact_understanding'):
                answer_schema['properties'].pop('target',None)
                answer_schema['required']=[k for k in answer_schema['required'] if k!='target']
            else: answer_schema={'oneOf':variants}
        else:
            answer_schema['properties']['citations']['items']['properties']['evidence_ref']['enum']=refs
        branches.append({'type':'object','properties':{'kind':{'const':'deliver'},
            'answers':{'type':'array','minItems':1,'maxItems':min(8,len(delivery_need_ids(view))),'items':answer_schema}},
            'required':['kind','answers'],'additionalProperties':False})
    if not branches: raise ValueError('NO_AVAILABLE_ACTION: goal requires clarification before tools')
    return {'oneOf':branches} if len(branches)>1 else branches[0]


def facts_from_goal(goal, explicit, today):
    """Extract only unambiguous literal date ranges; the original user text is retained."""
    values = dict(explicit)
    iso = re.findall(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)',goal)
    pair = iso if len(iso) == 2 else []
    if not pair:
        match = re.search(r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日?\s*(?:至|到|[-~])\s*(?:(\d{1,2})月)?(\d{1,2})日',goal)
        if match:
            year,month,start,end_month,end = match.groups()
            try:
                pair = [date(int(year or today.year),int(month),int(start)).isoformat(),
                        date(int(year or today.year),int(end_month or month),int(end)).isoformat()]
            except ValueError:
                pair = []
    if pair:
        try:
            for value in pair: date.fromisoformat(value)
            values.setdefault('loan_start',pair[0])
            values.setdefault('loan_end',pair[1])
        except ValueError:
            pass
    relative = re.search(r'下周([一二三四五六日天])(?:到|至)(?:下周|周)?([一二三四五六日天])',goal)
    if relative:
        days={'一':0,'二':1,'三':2,'四':3,'五':4,'六':5,'日':6,'天':6}
        a,b=(days[x] for x in relative.groups())
        if b>=a:
            monday=today+timedelta(days=7-today.weekday())
            values.setdefault('loan_start',(monday+timedelta(days=a)).isoformat())
            values.setdefault('loan_end',(monday+timedelta(days=b)).isoformat())
    if len(goal) <= 1000:
        values.setdefault('purpose',goal)
    return values
