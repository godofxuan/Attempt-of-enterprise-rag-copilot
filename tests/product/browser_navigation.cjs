/* Real React bundle and API, TEST task creation/cancellation; zero model sends. */
const {chromium}=require('playwright'),assert=require('assert'),fs=require('fs');
(async()=>{
 const b=await chromium.launch({channel:'msedge',headless:true}),p=await b.newPage({viewport:{width:1400,height:950}});
 const errors=[];p.on('pageerror',e=>errors.push(e.message));
 const folder='.private/esa-vnext/upgrade-050-060',stamp=new Date().toISOString().replace(/[:.]/g,'-'),record={kind:'REAL_UI_API_NO_MODEL_SEND'};
 try{
  const before=await(await p.request.get('http://127.0.0.1:8740/api/status')).json();
  await p.goto('http://127.0.0.1:8740/');await p.getByRole('button',{name:'IT 报修',exact:true}).click();
  const creation=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/tasks'));
  await p.getByRole('button',{name:'按所选范围开始',exact:true}).click();const task=await(await creation).json();
  await p.getByRole('dialog').waitFor();
  assert(new URLSearchParams(p.url().split('?')[1]).get('c')===task.conversation_id,p.url());
  await p.getByRole('button',{name:'关闭详情',exact:true}).click();
  const conversation=await(await p.request.get('http://127.0.0.1:8740/api/conversations/'+task.conversation_id)).json();
  assert.equal(conversation.active_task_id,task.task_id);
  const input=p.getByRole('textbox',{name:'给助理发消息',exact:true});await input.fill('导航后仍保留这段草稿');
  await p.getByRole('link',{name:'▤ 我的事项',exact:true}).click();
  await p.locator('a[href="#/assistant?c='+task.conversation_id+'"]').click();
  await p.getByRole('textbox',{name:'给助理发消息',exact:true}).waitFor();assert.equal(await input.inputValue(),'导航后仍保留这段草稿');
  assert.equal(await p.locator('textarea:visible').count(),1);
  await input.dispatchEvent('compositionstart');await input.dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true});await input.dispatchEvent('compositionend');
  await p.getByRole('button',{name:/查看参数与下一步/}).click();
  const cancelled=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/cancel'));
  await p.getByRole('button',{name:'结束这个事项',exact:true}).click();await cancelled;
  const ended=await(await p.request.get('http://127.0.0.1:8740/api/conversations/'+task.conversation_id)).json();assert.equal(ended.active_task_id,null);
  await p.getByRole('button',{name:'关闭详情',exact:true}).click();
  await p.screenshot({path:folder+'/CURRENT_UI_DESKTOP.png',fullPage:true});
  await p.setViewportSize({width:390,height:844});await p.screenshot({path:folder+'/CURRENT_UI_MOBILE.png',fullPage:true});
  assert(await p.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  const after=await(await p.request.get('http://127.0.0.1:8740/api/status')).json();assert.equal(before.generation_calls,after.generation_calls);
  record.task=task.task_id;record.conversation=task.conversation_id;record.chat_delta=after.generation_calls-before.generation_calls;
  record.composition='SYNTHETIC_COMPOSITION_EVENT_ONLY_NOT_MANUAL_IME';record.errors=errors;assert.deepEqual(errors,[]);record.passed=true;
 }catch(e){record.failure=e.stack;process.exitCode=1;}
 finally{fs.writeFileSync(folder+'/UI_NAVIGATION_'+stamp+'.json',JSON.stringify(record,null,2));console.log(JSON.stringify(record));await b.close();}
})();
