"""Actual tool capabilities, constructed for one current task and user turn."""
import json
from dataclasses import dataclass

from pydantic import ValidationError
from app.service_desk.catalog import SERVICES,service_for
from app.service_desk.store import ServiceError


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict
    required: tuple=()

    def schema(self):return {'type':'function','function':{'name':self.name,'description':self.description,
        'parameters':{'type':'object','properties':self.properties,'required':list(self.required),'additionalProperties':False}}}


class ToolCatalog:
    OBSERVATIONS={'loan_policy':'knowledge.read','repair_policy':'knowledge.read','assets_search':'assets.search',
                  'tickets_list_mine':'tickets.list_mine','tickets_get':'tickets.get'}

    def __init__(self,service,task,turn=None):
        self.service=service;self.task=task;self.turn=turn;self.knowledge_cache={}
        kind=task['guided_request']['kind'];domain=SERVICES.get(kind)
        tools=[Tool('finish','Finish the current turn after all requested parts are addressed.',{}),
               Tool('ask_user','Ask once for missing or ambiguous input.',{'question':{'type':'string'}})]
        if kind=='knowledge' or task.get('kb_id'):
            properties={} if kind=='knowledge' and not turn else {'question':{'type':'string'}}
            tools.append(Tool('knowledge_answer','Use the shared knowledge service; preserve its body, sources and limitations.',properties,
                              ('question',) if properties else ()))
        if domain:
            tools.extend([Tool(domain.rule_need,'Read the current executable synthetic business rule; documents do not replace it.',{}),
                Tool('assets_search','Read current owned IT assets.' if kind=='repair' else 'Read actual date availability, specifications, preferences and repair eligibility.',{}),
                Tool('tickets_list_mine','Read current authenticated owned tickets, including an empty list.',{}),
                Tool('tickets_get','Read a current owned ticket returned by the list.',{'ticket_id':{'type':'string'}},('ticket_id',))])
            if not task.get('receipt'):
                if turn:
                    schema=domain.facts_type.model_json_schema()
                    tools.extend([Tool('update_parameters','Apply only user-requested fact changes; normalize relative dates using reference_date. Null clears. Never changes permissions.',
                        {'changes':schema},('changes',)),Tool('select_asset','Select an actual user-requested resource; not reservation or submission.',
                        {'asset_id':{'type':'string'}},('asset_id',))])
                if task['user_execution_ceiling']!='READ_ONLY':
                    tools.append(Tool('prepare_preview','Prepare the current full preview. Complete other requested knowledge/explanation first. Does not submit.',
                        {'asset_id':{'type':'string'}},('asset_id',)))
        self.tools={tool.name:tool for tool in tools}

    def schemas(self,current=None):
        current=current or self.task
        allowed=set(self.tools)
        if self.turn and current['guided_request']['kind'] in SERVICES:
            missing=[f for f in self.service.required_fields(current) if not current['facts'].get(f)]
            actual=current.get('observations',[])[len(self.task.get('observations',[])):]
            addressed=any(o['tool'] in {'update_parameters','knowledge_answer'} and o['result'].get('status')=='ok' for o in actual)
            if missing and not addressed:allowed.discard('finish')
        if not self.turn and current['guided_request']['kind'] in SERVICES:
            from app.workbench_service import local_actor
            if not self.service.store.completion_ready(local_actor(),current['task_id']):allowed.discard('finish')
            missing=self.service.required_fields(current)
            last_error=bool(current.get('observations') and current['observations'][-1]['result'].get('status')=='error')
            if not any(not current['facts'].get(f) for f in missing) and not last_error:allowed.discard('ask_user')
        self.allowed_names=allowed
        return [tool.schema() for name,tool in self.tools.items() if name in allowed]

    @staticmethod
    def model_view(result):
        data=result.get('data')
        if result.get('status')=='ok' and isinstance(data,dict) and 'result' in data and 'id' in data:
            answer=data['result']
            # Full published receipt/trace is retained in the tool observation.
            # The model needs one body and its limitations, not duplicate trace/span JSON.
            return {**result,'data':{'id':data['id'],'question':data.get('question'),'mode':answer['mode'],
                'answer':answer['answer'],'sources':[{k:s.get(k) for k in ('doc_id','chunk_id','source_path','title','version_id','index_run_id')}
                    for s in answer.get('sources',[])],'warnings':answer.get('warnings',[]),
                'source_notices':data.get('source_notices',[])}}
        return result

    def validate(self,name,arguments):
        if name not in getattr(self,'allowed_names',self.tools) or not isinstance(arguments,dict):raise ServiceError('INVALID_TOOL_ARGUMENTS')
        tool=self.tools[name]
        if set(arguments)-set(tool.properties) or set(tool.required)-set(arguments):raise ServiceError('INVALID_TOOL_ARGUMENTS')

    async def call(self,name,args,current,run_id):
        self.validate(name,args)
        service=self.service;task_id=current['task_id'];store=service.store
        from app.workbench_service import local_actor
        actor=local_actor()
        if name in {'loan_policy','repair_policy'}:return service.policy(task_id)
        if name=='assets_search':return service.assets(task_id)
        if name=='tickets_list_mine':return {'tickets':service.tickets(task_id)}
        if name=='tickets_get':return service.ticket(task_id,args['ticket_id'])
        if name=='update_parameters':
            domain=service_for(current)
            try:changes=domain.facts_type.model_validate(args['changes']).model_dump(mode='json',exclude_unset=True)
            except ValidationError as exc:raise ServiceError('INVALID_PARAMETER',data={'details':exc.errors(include_context=False)}) from exc
            view=service.facts(task_id,changes,current['facts_revision'])
            with store.transaction() as db:
                updated=store._task(db,actor,task_id)
                for field in changes:
                    updated.setdefault('fact_sources',{})[field]={'origin':'USER_MESSAGE','source_message_id':self.turn['id'],
                        'raw_text':self.turn['text'],'normalized_by':'MAIN_MODEL_WITH_FIELD_VALIDATION'}
                store._save(db,updated)
            service.workspace.runs.event(run_id,'field_changes',{'changes':changes,'facts_revision':view['facts_revision']})
            return {'facts':view['facts'],'facts_revision':view['facts_revision'],'changed':changes}
        if name=='select_asset':return service.choose_asset(task_id,args['asset_id'],current['facts_revision'])
        if name=='prepare_preview':
            if current.get('preferred_asset_id') and args['asset_id']!=current['preferred_asset_id']:raise ServiceError('USER_ASSET_SELECTION_MISMATCH')
            domain=service_for(current)
            refs=[e['ref'] for e in current.get('knowledge',{}).values() if e['need_refs']==[domain.rule_need]]
            return store.propose(actor,task_id,args['asset_id'],refs,_record_tool_result=True)
        if name=='knowledge_answer':
            if not current.get('kb_id'):raise ServiceError('KNOWLEDGE_BASE_REQUIRED')
            question=args.get('question') or (self.turn['text'] if self.turn else current['guided_request']['question'])
            detailed=bool(self.turn and self.turn.get('detailed'))
            key=(current['kb_id'],question.strip(),detailed)
            if key in self.knowledge_cache:return self.knowledge_cache[key]
            linked=current.get('linked_answer_id');library=service.workspace.library
            cached=library.valid_answer(linked,current['kb_id']) if linked and hasattr(library,'valid_answer') else None
            if cached and not detailed and question.strip()==cached['question'].strip():
                self.knowledge_cache[key]={**cached,'reused':True};return self.knowledge_cache[key]
            previous=current.get('knowledge_result') or {}
            answer=await library.answer(current['kb_id'],question,
                conversation_id=current.get('conversation_id') or previous.get('conversation_id'),detailed=detailed)
            self.knowledge_cache[key]=answer;return answer
        raise ServiceError('INVALID_TOOL_ARGUMENTS')
