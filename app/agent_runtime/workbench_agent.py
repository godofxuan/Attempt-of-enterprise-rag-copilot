"""One observation/tool loop; business commands and final facts stay in the store."""
import json

from app.service_desk.store import ServiceError, digest
from app.workbench_service import local_actor
from app.service_desk.catalog import SERVICES,service_for


DEFINITIONS = {
    'loan_policy':('Read the current authoritative synthetic loan business rule.',{}),
    'repair_policy':('Read the current authoritative synthetic IT repair rule; not loan eligibility.',{}),
    'assets_search':('Read current stock and the authenticated employee repair eligibility.',{}),
    'tickets_list_mine':('Read the authenticated employee applications, including an empty list.',{}),
    'tickets_get':('Read an actual ticket from tickets_list_mine.',{'ticket_id':{'type':'string'}}),
    'prepare_preview':('Prepare a complete preview using current facts, rule and an actual available asset; does not submit.',{'asset_id':{'type':'string'}}),
    'knowledge_answer':('Answer the user-bound original question using the same knowledge service as independent RAG.',{}),
    'ask_user':('Pause for genuinely missing user information.',{}),
    'finish':('Deliver current authoritative results. Host checks the actual requested outcome.',{})}


class ServiceAgent:
    def __init__(self,service):self.service=service;self.store=service.store;self.workspace=service.workspace

    async def run(self,task_id,run_id):
        actor=local_actor();started=self.store.begin_run(actor,task_id)
        self.workspace.runs.lifecycle.own_task(run_id,started)
        kind=started['guided_request']['kind'];service=SERVICES.get(kind)
        allowed={'knowledge_answer','finish','ask_user'} if kind=='knowledge' else set(DEFINITIONS)-{'knowledge_answer','loan_policy','repair_policy'}|{service.rule_need}
        if started['user_execution_ceiling']=='READ_ONLY':allowed.discard('prepare_preview')
        tools=[{'type':'function','function':{'name':name,'description':description,
                'parameters':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}}
               for name,(description,properties) in DEFINITIONS.items() if name in allowed]
        if kind=='repair':
            for tool in tools:
                if tool['function']['name']=='assets_search':tool['function']['description']='Read current authenticated owned IT assets; not loan stock.'
                if tool['function']['name']=='prepare_preview':tool['function']['description']='Prepare an IT repair preview for the user-selected owned asset, current description and impact; does not submit.'
        seen=set();messages=[];observed_this_run=set()
        try:
            for step in range(8):
                current=self.store.get_task(actor,task_id)
                if current['active_run_id']!=started['active_run_id']:raise ServiceError('STALE_RUN')
                scope=current['user_execution_ceiling']
                context={'task_kind':current['guided_request']['kind'],'execution_ceiling':scope,
                    'forbidden_operations':current['task_goal']['forbidden_operations'],
                    'facts':current['facts'],'reference_date':current['time_context']['reference_date'],
                    'preferred_asset_id':current.get('preferred_asset_id'),
                    'question':current['guided_request'].get('question'),
                    'required_outputs':current['task_goal']['required_outputs'],
                    'valid_observations':{k:v for k,v in self.service.valid_observations(current).items() if k not in observed_this_run},
                    'missing_fields':[k for k in self.service.required_fields(current) if not current['facts'].get(k)]}
                system=('You are the ESA local service assistant. Choose tools from actual observations. '
                    'valid_observations are already completed reads, rechecked by the host against the current '
                    'database and dependency rules. Use their data directly; do not repeat those read tools '
                    'unless the observation is missing or a genuinely new question requires it. '
                    'Never invent tool results, approval or stock. User scope cannot be expanded. '
                    'For loan, read loan policy, repair eligibility, stock and owned applications. '
                    'For repair, read repair policy, owned IT assets and owned repair tickets; '
                    'use the user-bound asset_id, description and impact. Do not substitute loan actions. '
                    'An existing open application must be read; do not make another. Missing facts require ask_user. '
                    'READ_ONLY forbids preparation and submission; PREVIEW_ONLY forbids submission. '
                    'No submit tool exists: the user confirms an exact current preview in the UI. '
                    'For a knowledge task use knowledge_answer once, not loan tools. Finish when actual results suffice. '
                    'Current user-bound task JSON: '+json.dumps(context,ensure_ascii=False))
                self.store.reserve_model(actor,task_id,started['active_run_id'],{'purpose':'tool_selection','context':context,'observations':messages})
                response=await self.workspace.models.chat([{'role':'system','content':system},*messages],tools=tools,max_tokens=600)
                self.store.record(actor,task_id,'model_response',{'raw':response,'run_id':run_id})
                self.workspace.runs.event(run_id,'model_decision',response)
                calls=response.get('tool_calls',[])
                if not calls:calls=[{'function':{'name':'finish','arguments':{}}}]
                messages.append({'role':'assistant','content':response.get('content',''),'tool_calls':response.get('tool_calls',[])})
                for call in calls:
                    function=call['function'];name=function['name'];arguments=function.get('arguments',{})
                    if isinstance(arguments,str):arguments=json.loads(arguments)
                    expected=DEFINITIONS.get(name)
                    if name not in allowed or not expected or set(arguments)!=set(expected[1]):raise ServiceError('INVALID_TOOL_ARGUMENTS')
                    if name in {'finish','ask_user'}:
                        if name=='ask_user':
                            self.store.stop_run(actor,task_id,'WAITING_USER',missing=context['missing_fields'])
                        else:self.store.finish_goal(actor,task_id)
                        return self.service.view(task_id)
                    with self.store.run_scope(started):
                        self.store.reserve_tool(actor,task_id,name,arguments)
                        try:
                            if name in {'loan_policy','repair_policy'}:data=self.service.policy(task_id)
                            elif name=='assets_search':data=self.service.assets(task_id)
                            elif name=='tickets_list_mine':data={'tickets':self.service.tickets(task_id)}
                            elif name=='tickets_get':data=self.service.ticket(task_id,arguments['ticket_id'])
                            elif name=='prepare_preview':
                                task=self.store.get_task(actor,task_id)
                                if task.get('preferred_asset_id') and arguments['asset_id']!=task['preferred_asset_id']:
                                    raise ServiceError('USER_ASSET_SELECTION_MISMATCH')
                                refs=[e['ref'] for e in task.get('knowledge',{}).values() if e['need_refs']==[service.rule_need]]
                                data=self.store.propose(actor,task_id,arguments['asset_id'],refs,_record_tool_result=True)
                            elif name=='knowledge_answer':
                                if current['guided_request']['kind']!='knowledge':raise ServiceError('QUESTION_NOT_BOUND')
                                if not current.get('kb_id'):raise ServiceError('KNOWLEDGE_BASE_REQUIRED')
                                data=await self.workspace.library.answer(current['kb_id'],current['guided_request']['question'])
                            result={'status':'ok','data':data,'retryable':False}
                        except ServiceError as exc:result={'status':'error','code':exc.code,'data':exc.data,'retryable':False}
                        if name!='prepare_preview':
                            self.store.observe(actor,task_id,{'loan_policy':'knowledge.read','repair_policy':'knowledge.read','assets_search':'assets.search',
                                'tickets_list_mine':'tickets.list_mine','tickets_get':'tickets.get'}.get(name,name),result)
                        elif result['status']=='error':self.store.observe(actor,task_id,'tickets.propose_create',result)
                    self.workspace.runs.event(run_id,'tool_result',{'tool':name,'result':result})
                    observed_this_run.add(name)
                    messages.append({'role':'tool','tool_name':name,'content':json.dumps(result,ensure_ascii=False)})
                    signature=digest({'name':name,'arguments':arguments,'result':result})
                    if signature in seen:raise ServiceError('NO_PROGRESS')
                    seen.add(signature)
                    if name=='knowledge_answer' and result['status']=='ok':
                        with self.store.transaction() as db:
                            task=self.store._task(db,actor,task_id);self.store._live(task)
                            task.update(knowledge_result=data,status='COMPLETED' if data['result']['mode']=='answered' else 'BLOCKED',active_run_id=None)
                            self.store._save(db,task)
                        return self.service.view(task_id)
                    if name=='prepare_preview' and result['status']=='ok':
                        if scope=='PREVIEW_ONLY':self.store.finish_goal(actor,task_id)
                        return self.service.view(task_id)
            raise ServiceError('RUN_STEP_LIMIT')
        except Exception as exc:
            try:self.store.stop_run(actor,task_id,'BLOCKED',error=getattr(exc,'code',type(exc).__name__))
            except ServiceError:pass
            raise


def build_service_agent(service):return ServiceAgent(service)
