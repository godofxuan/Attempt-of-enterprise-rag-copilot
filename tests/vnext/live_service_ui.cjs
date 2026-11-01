// Real installed-model journey through the current UI and TEST SQLite.
const {chromium}=require('playwright');const fs=require('fs');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1450,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
const root='.private/esa-vnext/logs';let record={kind:'LIVE_MODEL_UI_SYNTHETIC_LOCAL',errors};
try{await page.goto('http://127.0.0.1:8740/');await page.getByRole('button',{name:'服务任务',exact:true}).click();
const resume=process.env.ESA_RESUME_TASK;if(resume){await page.locator('#taskList button').filter({hasText:resume.slice(0,8)}).click();record.task_id=resume;}else{
await page.locator('#newTaskPanel').evaluate(el=>el.open=true);await page.locator('#taskKind').selectOption('loan');await page.locator('#taskScope').selectOption('SUBMIT_AFTER_CONFIRMATION');await page.locator('#scopeConfirmed').check();await page.locator('#newTaskForm button').click();await page.locator('#currentFacts').waitFor();
await page.locator('[name=loan_start]').fill('2026-11-01');await page.locator('[name=loan_end]').fill('2026-11-03');await page.locator('[name=purpose]').fill('本地合成测试：会议期间临时电脑');await page.getByRole('button',{name:'保存参数',exact:true}).click();
await page.waitForTimeout(300);record.task_id=await page.evaluate(()=>localStorage.getItem('esa-task'));
await page.getByRole('button',{name:'继续处理',exact:true}).click();
await page.waitForFunction(()=>!!localStorage.getItem('esa-active-run'),null,{timeout:10000});
const firstRun=await page.evaluate(()=>localStorage.getItem('esa-active-run'));
await page.waitForFunction(async id=>{const r=await fetch('/api/runs/'+id),t=await r.json();return !['queued','running'].includes(t.status);},firstRun,{timeout:240000});}
record.task=await page.evaluate(async id=>(await fetch('/api/tasks/'+id)).json(),record.task_id);
await page.screenshot({path:root+'/M4_LIVE_PREVIEW.png',fullPage:true});
if(record.task.status!=='WAITING_CONFIRMATION')throw Error('Expected actual preview; '+JSON.stringify(record.task.outcome||record.task.last_error));
await page.locator('#exactConfirmation').check();await page.locator('[name=loan_end]').fill('2026-11-04');if(await page.locator('#exactConfirmation').isChecked())throw Error('Date edit kept stale front-end consent');
record.old_preview=record.task.preview;await page.getByRole('button',{name:'保存参数',exact:true}).click();await page.waitForTimeout(300);
record.stale_response=await page.evaluate(async ({id,old,revision})=>{const r=await fetch('/api/tasks/'+id+'/submit',{method:'POST',headers:{'Content-Type':'application/json','X-ESA-Request':'1'},body:JSON.stringify({proposal_id:old.proposal_id,content_digest:old.content_digest,expected_facts_revision:revision,accepted:true})});return {status:r.status,body:await r.json()};},{id:record.task_id,old:record.old_preview,revision:record.task.facts_revision});
if(record.stale_response.status!==409)throw Error('Old consent unexpectedly accepted');
await page.getByRole('button',{name:'继续处理',exact:true}).click();await page.waitForFunction(async id=>(await(await fetch('/api/tasks/'+id)).json()).status==='WAITING_CONFIRMATION',record.task_id,{timeout:240000});
await page.locator('#exactConfirmation').check();await page.locator('#submitCurrent').click();await page.waitForFunction(async id=>!!(await(await fetch('/api/tasks/'+id)).json()).receipt,record.task_id,{timeout:20000});
record.final=await page.evaluate(async id=>(await fetch('/api/tasks/'+id)).json(),record.task_id);if(record.final.receipt.ticket.status!=='PENDING_APPROVAL'||record.final.receipt.ticket.parameters.loan_end!=='2026-11-04')throw Error('Wrong authoritative receipt');
await page.reload();await page.locator('#taskDetail').getByText('实际回执 · 待审批',{exact:true}).waitFor();await page.screenshot({path:root+'/M4_LIVE_RECEIPT.png',fullPage:true});record.passed=true;
}catch(error){record.error=error.stack;process.exitCode=1;}finally{fs.writeFileSync(root+'/M4_LIVE_UI.json',JSON.stringify(record,null,2));console.log(JSON.stringify({task_id:record.task_id,passed:record.passed,error:record.error,errors}));await browser.close();}})();
