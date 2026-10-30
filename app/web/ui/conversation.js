import {$,api,showError,view,bridge,uiState} from './api.js';
import {textElement,businessCard} from './dom.js';
import {renderAnswer} from './renderers.js';
import {watchRun} from './events.js';

let version=0,conversations=[],historyExpanded=false;
const historyViewport=window.matchMedia('(max-width:680px)');
$('conversationHistory').open=!historyViewport.matches;
historyViewport.addEventListener('change',event=>{$('conversationHistory').open=!event.matches;});
function renderConversationList(){
 const query=$('conversationSearch').value.trim().toLocaleLowerCase();
 let matches=conversations.filter(c=>(c.title||'知识会话').toLocaleLowerCase().includes(query));
 const active=matches.find(c=>c.id===uiState.conversationId);
 if(!query&&!historyExpanded&&active&&!matches.slice(0,6).includes(active))matches=[active,...matches.filter(c=>c!==active)];
 const visible=historyExpanded?matches:matches.slice(0,6);
 $('conversationList').replaceChildren(...visible.map(c=>{
  const title=c.title||'知识会话',button=textElement('button','');button.type='button';button.className='conversation-entry';
  button.title=title;
  if(c.id===uiState.conversationId)button.setAttribute('aria-current','page');
  const date=new Date(c.updated_at),time=c.updated_at&&!Number.isNaN(date.getTime())
   ?date.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'较早记录';
  const heading=textElement('span',title);heading.className='conversation-entry-title';
  button.append(heading,textElement('small',(c.task_id?'服务事项':'知识会话')+' · '+time));
  button.onclick=()=>openConversation(c.id).catch(showError);return button;
 }));
 if(!visible.length)$('conversationList').append(textElement('p',query?'没有匹配的会话':'还没有会话，从右侧开始提问。'));
 $('conversationCount').textContent=query?'找到 '+matches.length+' 个会话':'共 '+conversations.length+' 个会话';
 $('conversationMore').hidden=matches.length<=6;
 $('conversationMore').textContent=historyExpanded?'收起历史':'查看其余 '+(matches.length-visible.length)+' 个会话';
}
$('conversationSearch').oninput=()=>{historyExpanded=false;renderConversationList();};
$('conversationMore').onclick=()=>{historyExpanded=!historyExpanded;renderConversationList();};
export function restoreTaskLayout(){
 $('taskPane').append($('taskDetail'));$('taskProgressSlot').append($('taskProgress'));
}
export async function refreshConversations(){
 const list=await api('/api/conversations');
 conversations=[...list].sort((a,b)=>(Date.parse(b.updated_at)||0)-(Date.parse(a.updated_at)||0));
 renderConversationList();
 return list;
}
function renderTimeline(turns){
 const box=$('conversationTimeline');box.replaceChildren();
 for(const turn of turns){
  const card=document.createElement('article');card.className='turn '+turn.role;
  card.append(textElement('small',(turn.role==='user'?'你':turn.role==='tool'?'工具查询':'助手')+' · '+turn.status),textElement('pre',turn.text));
  const payload=turn.payload;
  if(payload?.knowledge)card.append(renderAnswer(payload.knowledge));
  else if(payload?.result?.sources)card.append(renderAnswer(payload));
  if(payload?.receipt)card.append(businessCard('提交时回执',payload.receipt.ticket));
  box.append(card);
 }
 if(!turns.length)box.append(textElement('p','可以提问资料，或明确服务与范围后开始办理。'));
}
export async function openConversation(cid){
 const own=++version;uiState.conversationId=cid;localStorage.setItem('esa-conversation',cid);view('conversations');
 const conversation=await api('/api/conversations/'+cid);if(own!==version)return;
 $('conversationTitle').textContent=conversation.title||'知识会话';$('conversationBase').value=conversation.kb_id||'';
 renderTimeline(conversation.turns);
 if(conversation.task_id){
  await bridge.selectTask(conversation.task_id);if(own!==version)return;
  $('conversationSide').append($('taskDetail'));$('conversationTaskProgressSlot').append($('taskProgress'));
 }else{restoreTaskLayout();$('conversationSide').replaceChildren(textElement('p','开始服务后，在这里查看参数、资源与当前预览。'));}
 await refreshConversations();
}
$('newConversation').onclick=async()=>{try{
 const created=await api('/api/conversations',{title:$('conversationName').value||'新会话',kb_id:$('conversationBase').value||null},'POST');
 await openConversation(created.id);
}catch(e){showError(e);}};
$('conversationForm').onsubmit=async event=>{
 event.preventDefault();const send=event.target.querySelector('button');send.disabled=true;
 try{
  let cid=uiState.conversationId;
  if(!cid){const c=await api('/api/conversations',{title:$('conversationText').value.slice(0,60),kb_id:$('conversationBase').value||null},'POST');cid=c.id;uiState.conversationId=cid;}
  const text=$('conversationText').value;
  const run=await api('/api/conversations/'+cid+'/turns',{message_id:crypto.randomUUID(),text,detailed:$('conversationDeep').checked},'POST');
  $('conversationText').value='';
  await openConversation(cid);
  await watchRun(run,async result=>{if(result.error)showError(Error(result.error));if(uiState.conversationId===cid)await openConversation(cid);});
 }catch(e){showError(e);}finally{send.disabled=false;}
};
$('conversationTaskForm').onsubmit=async event=>{
 event.preventDefault();try{
  if(!uiState.conversationId){const c=await api('/api/conversations',{title:$('conversationName').value||'服务事项',kb_id:$('conversationBase').value||null},'POST');uiState.conversationId=c.id;}
  const task=await api('/api/tasks',{request:{kind:$('conversationService').value,execution_ceiling:$('conversationScope').value,
      confirmed:$('conversationScopeConfirmed').checked},kb_id:$('conversationBase').value||null,conversation_id:uiState.conversationId},'POST');
  $('conversationScopeConfirmed').checked=false;await openConversation(uiState.conversationId);
 }catch(e){showError(e);}
};
api('/api/services').then(list=>{$('conversationService').replaceChildren(...list.map(service=>{const o=textElement('option',service.title);o.value=service.key;return o;}));}).catch(showError);

for(const id of ['conversationService','conversationScope'])$(id).onchange=()=>{$('conversationScopeConfirmed').checked=false;};
