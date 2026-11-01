import {$,api,showError} from './api.js';
export async function status(){
 const value=await api('/api/status');$('connection').textContent=value.chat.ready?'聊天模型可用':'聊天模型未连接';$('mode').textContent=value.mode==='SYNTHETIC_LOCAL'?'本地合成数据':'';
 const pairs=[['网页','可用'],['存储',value.storage?'可用':'不可用'],['聊天模型',value.chat.ready?value.chat.model+' · 可用':value.chat.model+' · 不可用'],['嵌入模型',value.embedding.ready?value.embedding.model+' · 可用':value.embedding.model+' · 不可用']];
 $('capabilities').replaceChildren();for(const [key,text] of pairs){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=text;$('capabilities').append(dt,dd);}
 $('paths').textContent=value.data_dir+'\n'+value.database;
 for(const id of ['chatModel','embeddingModel']){let choices=document.getElementById(id+'Choices');if(!choices){choices=document.createElement('datalist');choices.id=id+'Choices';document.body.append(choices);$(id).setAttribute('list',choices.id);}choices.replaceChildren(...value.models.map(m=>{const option=document.createElement('option');option.value=m.name;return option;}));}
 const guide=$('onboarding');if(guide){guide.hidden=value.chat.ready&&value.embedding.ready;guide.textContent='开始使用：选择本机已安装模型 → 资料库导入文档或规则示例 → 建立索引 → 会话提问或开始服务事项。'+(value.model_error?' 当前模型服务未连接，可继续查看设置和历史。':'');}
}
export function installSettings(){$('settingsForm').onsubmit=async event=>{event.preventDefault();try{await api('/api/settings',{model_endpoint:$('endpoint').value,chat_model:$('chatModel').value,embedding_model:$('embeddingModel').value},'PATCH');$('saved').textContent='已保存';await status();}catch(error){showError(error);}};}
