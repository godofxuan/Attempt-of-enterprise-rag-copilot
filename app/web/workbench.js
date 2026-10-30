import {$,api,showError,view,bridge} from './ui/api.js';
import {status,installSettings} from './ui/settings.js';
import {library} from './ui/library.js';
import {renderAnswer} from './ui/renderers.js';
import './ui/knowledge.js';
import {tasks,selectTask,loadCatalog,scopeChanged,selectedTask} from './ui/tasks.js';
import {watchRun} from './ui/events.js';
import {refreshConversations,openConversation,restoreTaskLayout} from './ui/conversation.js';
Object.assign(bridge,{tasks,selectTask,watchRun,openConversation});
for(const button of document.querySelectorAll('nav button'))button.onclick=()=>{if(button.dataset.view==='tasks')restoreTaskLayout();view(button.dataset.view);};
installSettings();
try{const settings=await api('/api/settings');$('endpoint').value=settings.model_endpoint;$('chatModel').value=settings.chat_model;$('embeddingModel').value=settings.embedding_model;view(localStorage.getItem('esa-view')||'conversations');await Promise.all([status(),library(),tasks(),loadCatalog()]);scopeChanged();await refreshConversations();const history=await api('/api/history');$('answerHistory').replaceChildren(...history.conversations.map(renderAnswer));const taskId=localStorage.getItem('esa-task');if(localStorage.getItem('esa-view')==='conversations'&&localStorage.getItem('esa-conversation'))await openConversation(localStorage.getItem('esa-conversation'));else if(taskId)await selectTask(taskId);const runId=localStorage.getItem('esa-active-run');if(runId){const run=await api('/api/runs/'+runId);if(['queued','running'].includes(run.status))await watchRun(run,async()=>{await tasks();if(selectedTask)await selectTask(selectedTask.task_id);});}}catch(error){showError(error);}
