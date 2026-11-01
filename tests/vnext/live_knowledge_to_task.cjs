// Actual installed-model UI journey; explicit synthetic backend, no recorded actions/results.
const {chromium}=require('playwright');const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const out=path.resolve(process.env.ESA_JOURNEY_DATA||'.private/esa-vnext/demo-validation','logs');fs.mkdirSync(out,{recursive:true});
 const stamp=new Date().toISOString().replace(/[:.]/g,'-'),record={kind:'LIVE_KNOWLEDGE_TO_TASK_TEST_BACKEND',errors:[]};
 const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1400,height:1000}});
 page.on('pageerror',e=>record.errors.push(e.message));
 const base=process.env.ESA_JOURNEY_URL||'http://127.0.0.1:8741';
 const get=async url=>{const r=await page.request.get(base+url);assert(r.ok(),await r.text());return r.json();};
 async function waitRun(savedId){let id=savedId;for(let n=0;!id&&n<150;n++){id=await page.evaluate(()=>localStorage.getItem('esa-active-run'));if(!id)await page.waitForTimeout(100);}assert(id,'No persisted run');
  let done;for(let n=0;n<490;n++){done=await get('/api/runs/'+id);if(!['queued','running'].includes(done.status))break;await page.waitForTimeout(500);}
  (record.runs??=[]).push(done);assert.equal(done.status,'succeeded',done.error);return done;}
 try{
  await page.goto(base);await page.getByRole('button',{name:'资料库',exact:true}).click();
  if(process.env.ESA_RESUME_KB){await page.locator('#uploadBase').selectOption(process.env.ESA_RESUME_KB);record.kb_id=process.env.ESA_RESUME_KB;}else{
  await page.locator('#baseName').fill('知识转任务合成演示 '+stamp);await page.locator('#baseForm button').click();
  await page.waitForFunction(()=>document.getElementById('uploadBase').options.length>0);record.kb_id=await page.locator('#uploadBase').inputValue();
  for(const name of ['loan.md','meeting.md']){await page.locator('#documentFile').setInputFiles(path.resolve('examples/esa/demo_policies',name));await page.locator('#uploadForm button').filter({hasText:'导入文档'}).click();await page.getByText(name+' · v1',{exact:true}).waitFor();}
  await page.locator('#buildIndex').click();}
  for(let n=0;n<360;n++){record.library=await get('/api/library');const job=record.library.jobs.find(j=>j.kb_id===record.kb_id);if(job&&['SUCCEEDED','FAILED','INTERRUPTED'].includes(job.status))break;await page.waitForTimeout(500);}
  assert.equal(record.library.jobs.find(j=>j.kb_id===record.kb_id)?.status,'SUCCEEDED');
  await page.getByRole('button',{name:'知识问答',exact:true}).click();
  await page.locator('#askBase').selectOption(record.kb_id);
  record.question='我的电脑正在维修，计划从2026-11-01借到2026-11-03，用途是异地会议。请说明临时电脑借用的资格、期限、开始日期限制、申请数量、待审批是否等于已分配，以及押金规定。';
  await page.locator('#question').fill(record.question);
  if(process.env.ESA_RESUME_KNOWLEDGE_RUN){record.answer=(await waitRun(process.env.ESA_RESUME_KNOWLEDGE_RUN)).result;await page.reload();await page.getByRole('button',{name:'知识问答',exact:true}).click();}
  else{await page.locator('#askForm button').click();record.answer=(await waitRun()).result;}
  assert(record.answer.result.answer);assert(record.answer.result.sources.length);
  const cta=page.locator('#answerHistory article').first().getByText('从知识继续办理',{exact:true});await cta.click();
  const group=page.locator('#answerHistory article').first().locator('details').filter({has:page.getByRole('button',{name:'按所选范围开始电脑借用任务'})});
  await group.locator('select').selectOption('SUBMIT_AFTER_CONFIRMATION');await group.locator('input[type=checkbox]').check();await group.getByRole('button',{name:'按所选范围开始电脑借用任务'}).click();
  await waitRun();record.task_id=await page.evaluate(()=>localStorage.getItem('esa-task'));let task=await get('/api/tasks/'+record.task_id);
  assert.deepEqual([task.facts.loan_start,task.facts.loan_end,task.facts.purpose],['2026-11-01','2026-11-03','异地会议']);assert.equal(task.user_execution_ceiling,'SUBMIT_AFTER_CONFIRMATION');
  await page.getByRole('button',{name:'查看真实可选设备',exact:true}).click();await page.getByRole('heading',{name:'loan-laptop-2',exact:true}).locator('..').getByRole('button',{name:'选择此设备'}).click();
  await page.getByRole('button',{name:'继续处理',exact:true}).click();await waitRun();await page.locator('#exactConfirmation').waitFor();task=await get('/api/tasks/'+record.task_id);assert.equal(task.preview.content.target,'loan-laptop-2');record.first_preview=task.preview;
  await page.locator('#exactConfirmation').check();await page.locator('[name=loan_end]').fill('2026-11-04');assert.equal(await page.locator('#exactConfirmation').isChecked(),false);
  await page.getByRole('button',{name:'保存参数',exact:true}).click();await page.waitForFunction(async id=>(await(await fetch('/api/tasks/'+id)).json()).facts.loan_end==='2026-11-04',record.task_id);
  const stale=await page.request.post(base+'/api/tasks/'+record.task_id+'/submit',{headers:{'X-ESA-Request':'1'},data:{proposal_id:task.preview.proposal_id,content_digest:task.preview.content_digest,expected_facts_revision:task.facts_revision,accepted:true}});record.old_confirmation={status:stale.status(),body:await stale.json()};assert.equal(stale.status(),409);
  await page.getByRole('button',{name:'继续处理',exact:true}).click();await waitRun();await page.locator('#exactConfirmation').waitFor();task=await get('/api/tasks/'+record.task_id);record.final_preview=task.preview;
  await page.locator('#exactConfirmation').check();await page.locator('#submitCurrent').click();await page.getByText('实际回执 · 待审批',{exact:true}).waitFor();
  record.final=await get('/api/tasks/'+record.task_id);assert.equal(record.final.receipt.ticket.asset_id,'loan-laptop-2');assert.equal(record.final.receipt.ticket.parameters.loan_end,'2026-11-04');assert.equal(record.final.receipt.ticket.status,'PENDING_APPROVAL');
  const retry=await page.request.post(base+'/api/tasks/'+record.task_id+'/submit',{headers:{'X-ESA-Request':'1'},data:{proposal_id:task.preview.proposal_id,content_digest:task.preview.content_digest,expected_facts_revision:task.facts_revision,accepted:true}});record.retry={status:retry.status(),body:await retry.json()};assert.equal(retry.status(),200);assert.equal(record.retry.body.receipt.ticket.ticket_id,record.final.receipt.ticket.ticket_id);
  await page.reload();await page.getByText('实际回执 · 待审批',{exact:true}).waitFor();await page.screenshot({path:path.join(out,'J10_'+stamp+'.png'),fullPage:true});assert.deepEqual(record.errors,[]);record.passed=true;
 }catch(error){record.error=error.stack;process.exitCode=1;}finally{fs.writeFileSync(path.join(out,'J10_'+stamp+'.json'),JSON.stringify(record,null,2));console.log(JSON.stringify({passed:record.passed,task_id:record.task_id,error:record.error,runs:record.runs?.map(r=>({id:r.id,status:r.status}))}));await browser.close();}
})();
