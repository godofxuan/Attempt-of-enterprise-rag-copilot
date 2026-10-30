import {$,api,showError} from './api.js';
import {textElement} from './dom.js';

const terminal=new Set(['succeeded','finished','failed','cancelled','interrupted']);
const watchers=new Map();
export async function watchRun(run,onComplete){
 if(watchers.has(run.id))return watchers.get(run.id);
 const panel=$(run.kind==='conversation'?'conversationProgress':run.kind==='knowledge'?'knowledgeProgress':'taskProgress');
 const stop=textElement('button','停止本次执行'),state=textElement('p','正在执行…');
 panel.replaceChildren(stop,state);localStorage.setItem('esa-active-run',run.id);
 stop.onclick=async()=>{stop.disabled=true;try{await api('/api/runs/'+run.id+'/cancel',{},'POST');}catch(e){showError(e);stop.disabled=false;}};
 const promise=new Promise((resolve,reject)=>{
  let source,done=false,failures=0,cursor=Number(localStorage.getItem('esa-run-cursor-'+run.id)||0);
  async function finish(snapshot){
   if(done)return;done=true;source?.close();stop.disabled=true;
   localStorage.removeItem('esa-active-run');state.textContent='执行：'+snapshot.status;
   try{await onComplete(snapshot);resolve(snapshot);}catch(e){showError(e);reject(e);}finally{watchers.delete(run.id);}
  }
  async function connect(){
   const snapshot=await api('/api/runs/'+run.id);
   if(terminal.has(snapshot.status)){await finish(snapshot);return;}
   source=new EventSource('/api/runs/'+run.id+'/events?after_seq='+cursor);
   source.addEventListener('progress',async event=>{
    const row=JSON.parse(event.data);cursor=row.seq;localStorage.setItem('esa-run-cursor-'+run.id,String(cursor));
    const titles={queued:'排队',running:'执行中',needs_input:'需要补充信息',field_changes:'参数已更新',sources:'来源已就绪',preview_ready:'当前预览已就绪'};
    const title=row.kind==='tool_result'?row.data.tool+' · '+row.data.result.status:row.kind==='model_decision'?
      '模型选择：'+(row.data.tool_calls||[]).map(c=>c.function.name).join(', '):titles[row.kind]||row.kind;
    state.textContent=title;
    const detail=document.createElement('details');detail.append(textElement('summary',title),textElement('pre',JSON.stringify(row.data,null,2)));panel.append(detail);
    if(terminal.has(row.kind))await finish(await api('/api/runs/'+run.id));
   });
   source.onerror=async()=>{
    if(done)return;
    try{const snapshot=await api('/api/runs/'+run.id);if(terminal.has(snapshot.status)){await finish(snapshot);return;}}catch(e){state.textContent='连接中断，保留已接收的进度';}
    if(++failures>=5){source.close();const retry=textElement('button','重连已保存进度');retry.onclick=()=>{retry.remove();failures=0;connect().catch(showError);};panel.append(retry);}
    else state.textContent='进度连接重连中；不会重新执行任务';
   };
  }
  connect().catch(e=>{watchers.delete(run.id);showError(e);reject(e);});
 });
 watchers.set(run.id,promise);return promise;
}
