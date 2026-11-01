export const $=id=>document.getElementById(id);
export async function api(path,data,method='GET'){
 const response=await fetch(path,{method,headers:{...(data instanceof FormData?{}:{'Content-Type':'application/json'}),'X-ESA-Request':'1'},body:data===undefined?undefined:data instanceof FormData?data:JSON.stringify(data)});
 const body=await response.json();if(!response.ok){const error=Error(body.error?.message||(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail||body)));error.payload=body;throw error;}return body;
}
export function showError(error){$('error').hidden=false;$('error').textContent=error.message;}
export function view(name){for(const section of document.querySelectorAll('main>section'))section.hidden=section.id!==name;for(const button of document.querySelectorAll('nav button'))button.setAttribute('aria-selected',String(button.dataset.view===name));localStorage.setItem('esa-view',name);}
export const bridge={};
export const uiState={knowledgeConversation:null,conversationId:null};
