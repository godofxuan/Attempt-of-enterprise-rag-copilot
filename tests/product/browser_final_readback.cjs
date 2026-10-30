/* Current artifact, real persisted sources/receipts; separate presentation XSS fixture. */
const {chromium}=require('playwright'),assert=require('assert'),fs=require('fs');
(async()=>{const folder='.private/esa-vnext/upgrade-050-060',record={kind:'CURRENT_PACKAGE_REAL_READBACK_AND_SEPARATE_PRESENTATION_FIXTURE',chat_delta:0};
 const original=JSON.parse(fs.readFileSync(folder+'/LIVE_050_2026-10-30T12-32-24-468Z.json','utf8'));
 const b=await chromium.launch({channel:'msedge',headless:true}),p=await b.newPage({viewport:{width:1440,height:1000}}),errors=[];p.on('pageerror',e=>errors.push(e.message));
 const get=async(path)=>{const r=await p.request.get('http://127.0.0.1:8740'+path);assert(r.ok(),await r.text());return r.json();};
 try{
  const before=await get('/api/status');record.instance=await get('/api/instance');
  const task=await get('/api/tasks/'+original.loan_task_id);assert.equal(task.current_ticket.status,'RETURNED');
  await p.goto('http://127.0.0.1:8740/#/assistant?c='+task.conversation_id+'&task='+task.task_id);
  const dialog=p.getByRole('dialog');await dialog.waitFor();await dialog.getByText(task.current_ticket.parameters.loan_end,{exact:true}).first().waitFor();assert((await dialog.innerText()).includes(task.current_ticket.parameters.loan_end));
  assert.equal(await p.getByRole('button',{name:'确认并提交当前预览',exact:true}).count(),0);
  await dialog.getByText('查看提交当时的回执',{exact:true}).click();assert((await dialog.innerText()).includes(task.receipt.ticket.parameters.loan_end));
  await p.screenshot({path:folder+'/FINAL_RETURNED_RECEIPT.png',fullPage:true});await p.getByRole('button',{name:'关闭详情',exact:true}).click();
  const cid=original.answer.conversation_id;await p.goto('http://127.0.0.1:8740/#/assistant?c='+cid);
  await p.getByRole('button',{name:/^1\./}).first().click();await dialog.waitFor();assert((await dialog.innerText()).includes('维修'));
  await p.screenshot({path:folder+'/FINAL_SOURCE_READER.png',fullPage:true});await p.getByRole('button',{name:'关闭详情',exact:true}).click();
  await p.route('**/api/conversations/'+cid,async route=>{const response=await route.fetch(),value=await response.json();value.turns.push({id:'presentation-only-xss',role:'assistant',kind:'presentation_fixture',status:'DONE',text:'安全渲染与换行。\n'.repeat(240)+'<script>window.__ESA_XSS=1</script><img src=x onerror="window.__ESA_XSS=1">',payload:null});await route.fulfill({response,json:value});});
  await p.reload();await p.getByText('安全渲染与换行。',{exact:false}).last().waitFor();assert.equal(await p.evaluate(()=>window.__ESA_XSS),undefined);
  assert.equal(await p.locator('img[src="x"]').count(),0);await p.setViewportSize({width:390,height:844});assert(await p.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await p.screenshot({path:folder+'/FINAL_NARROW_LONG_TEXT_FIXTURE.png',fullPage:true});
  const after=await get('/api/status');assert.equal(before.generation_calls,after.generation_calls);assert.deepEqual(errors,[]);
  record.loan_task=task.task_id;record.current_date=task.current_ticket.parameters.loan_end;record.original_receipt_date=task.receipt.ticket.parameters.loan_end;
  record.source_conversation=cid;record.presentation_fixture='BROWSER_RESPONSE_OVERLAY_ONLY_NOT_MODEL_OR_BUSINESS_EVIDENCE';record.errors=errors;record.passed=true;
 }catch(e){record.failure=e.stack;process.exitCode=1;}
 finally{fs.writeFileSync(folder+'/FINAL_BROWSER_READBACK.json',JSON.stringify(record,null,2));console.log(JSON.stringify(record));await b.close();}
})();
