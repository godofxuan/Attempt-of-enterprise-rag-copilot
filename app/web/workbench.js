const $=id=>document.getElementById(id);
async function api(path,data,method='GET'){
 const response=await fetch(path,{method,headers:{'Content-Type':'application/json','X-ESA-Request':'1'},body:data===undefined?undefined:JSON.stringify(data)});
 const body=await response.json();if(!response.ok)throw Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail||body));return body;
}
function showError(error){$('error').hidden=false;$('error').textContent=error.message;}
function view(name){for(const section of document.querySelectorAll('main>section'))section.hidden=section.id!==name;for(const button of document.querySelectorAll('nav button'))button.setAttribute('aria-selected',String(button.dataset.view===name));localStorage.setItem('esa-view',name);}
for(const button of document.querySelectorAll('nav button'))button.onclick=()=>view(button.dataset.view);
async function status(){
 const value=await api('/api/status');$('connection').textContent=value.chat.ready?'聊天模型可用':'聊天模型未连接';$('mode').textContent=value.mode==='SYNTHETIC_LOCAL'?'本地合成数据':'';
 const pairs=[['网页','可用'],['存储',value.storage?'可用':'不可用'],['聊天模型',value.chat.ready?value.chat.model+' · 可用':value.chat.model+' · 不可用'],['嵌入模型',value.embedding.ready?value.embedding.model+' · 可用':value.embedding.model+' · 不可用']];
 $('capabilities').replaceChildren();for(const [key,text] of pairs){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=text;$('capabilities').append(dt,dd);}
 $('paths').textContent=value.data_dir+'\n'+value.database;
}
$('settingsForm').onsubmit=async event=>{event.preventDefault();try{await api('/api/settings',{model_endpoint:$('endpoint').value,chat_model:$('chatModel').value,embedding_model:$('embeddingModel').value},'PATCH');$('saved').textContent='已保存';await status();}catch(error){showError(error);}};
try{const settings=await api('/api/settings');$('endpoint').value=settings.model_endpoint;$('chatModel').value=settings.chat_model;$('embeddingModel').value=settings.embedding_model;view(localStorage.getItem('esa-view')||'knowledge');await status();}catch(error){showError(error);}
