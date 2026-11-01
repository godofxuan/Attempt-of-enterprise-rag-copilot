import {$,api,showError,bridge} from './api.js';
import {textElement,businessCard} from './dom.js';

export async function refreshDesk(){
 const data=await api('/api/service-desk'),box=$('deskTickets');box.replaceChildren();
 if(!data.tickets.length)box.append(textElement('p','当前没有工单。请先通过会话中的当前预览确认申请。'));
 for(const item of data.tickets){
  const ticket=item.ticket,card=businessCard(item.kind==='loan'?'电脑借用':'IT 报修',ticket);card.dataset.ticketId=ticket.ticket_id;
  card.append(textElement('p',item.notice));
  const note=document.createElement('textarea');note.placeholder='处理说明（必填，真实保存到本地工单事件）';note.maxLength=1000;
  const end=document.createElement('input');end.type='date';end.value=ticket.parameters.loan_end||'';
  if(item.actions.some(a=>a.name==='extend')){const label=textElement('label','续借结束日期');label.append(end);card.append(label);}
  if(item.actions.length)card.append(note);
  const previewBox=document.createElement('div');
  for(const action of item.actions){const button=textElement('button',action.label);button.dataset.action=action.name;
   button.onclick=async()=>{try{
    const p=await api('/api/service-desk/proposals',{kind:item.kind,ticket_id:ticket.ticket_id,action:action.name,
       expected_version:ticket.version,note:note.value,...(action.name==='extend'?{loan_end:end.value}:{})},'POST');
    previewBox.replaceChildren(textElement('h3','当前处理预览'),textElement('pre',JSON.stringify(p.content,null,2)));
    const check=document.createElement('input');check.type='checkbox';const label=document.createElement('label');
    label.append(check,document.createTextNode('我已核对当前工单版本、动作和参数，明确确认本次 TEST 操作。'));
    const commit=textElement('button','确认当前处理');commit.disabled=true;check.onchange=()=>commit.disabled=!check.checked;
    const clear=()=>{check.checked=false;commit.disabled=true;};note.oninput=clear;end.oninput=clear;
    commit.onclick=async()=>{commit.disabled=true;try{await api('/api/service-desk/commit',{proposal_id:p.proposal_id,
      content_digest:p.content_digest,accepted:check.checked},'POST');await refreshDesk();await bridge.tasks();}catch(error){showError(error);}};
    previewBox.append(label,commit);
   }catch(error){showError(error);}};card.append(button);}
  card.append(previewBox);box.append(card);
 }
 $('deskSchedule').textContent=JSON.stringify(data.reservations,null,2);
}
$('refreshDesk').onclick=()=>refreshDesk().catch(showError);
