import {$,api,showError,uiState} from './api.js';
import {renderAnswer} from './renderers.js';
import {watchRun} from './events.js';
export function newTopic(){uiState.knowledgeConversation=null;$('followupState').textContent='新话题，不带入旧会话';}
$('newTopic').onclick=newTopic;$('askBase').onchange=newTopic;
$('askForm').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;$('knowledgeState').textContent='正在检索与生成…';try{const question=$('question').value;const run=await api('/api/knowledge/runs',{kb_id:$('askBase').value,question,detailed:$('detailed').checked,conversation_id:uiState.knowledgeConversation},'POST');await watchRun(run,done=>{button.disabled=false;if(done.result){done.result.question=question;$('answerHistory').prepend(renderAnswer(done.result));$('knowledgeState').textContent='回答已保存';}else{$('knowledgeState').textContent=done.error||done.status;}});}catch(error){showError(error);button.disabled=false;}};
