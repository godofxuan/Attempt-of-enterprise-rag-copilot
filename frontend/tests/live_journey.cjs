/* Real UI + native Ollama + real tools/SQLite. No action/model substitution.
 * Explicit test user selects scope, supplies facts and confirms exact previews.
 */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const option=(name)=>{const i=process.argv.indexOf(name);return i<0?undefined:process.argv[i+1];};
const base=option('--url'),kb=option('--kb'),out=option('--out'),commit=option('--commit');
const resumeTask=option('--resume-task');
if(!base||!kb||!out||!commit)throw Error('Required --url --kb --out --commit');
if(fs.existsSync(out))throw Error('Preserve original run; use a new distinct measurement output');
fs.mkdirSync(path.dirname(out),{recursive:true});
const report={kind:'REAL_PACKAGED_UI_MODEL_AND_SYNTHETIC_TEST_BUSINESS',commit,inputs:[],runs:[],confirmations:[],actions:[],page_errors:[]};
const save=()=>fs.writeFileSync(out,JSON.stringify(report,null,2));
(async()=>{
 const browser=await chromium.launch({channel:process.env.ESA_BROWSER_CHANNEL||'msedge',headless:true});
 const p=await browser.newPage({viewport:{width:1440,height:1000}});
 p.on('pageerror',e=>report.page_errors.push(String(e)));
 const get=async route=>{const r=await p.request.get(base+route);assert(r.ok(),await r.text());return r.json();};
 const post=async(route,data)=>{const r=await p.request.post(base+route,{headers:{'X-ESA-Request':'1'},data});assert(r.ok(),await r.text());return r.json();};
 async function wait(run){
  const deadline=Date.now()+250000;
  while(Date.now()<deadline){const r=await get('/api/runs/'+run.id);if(!['queued','running'].includes(r.status)){report.runs.push(r);save();assert.equal(r.status,'succeeded',r.error);return r.result;}await p.waitForTimeout(400);}
  await post('/api/runs/'+run.id+'/cancel',{});throw Error('Existing run deadline exceeded; cancellation requested');
 }
 async function say(text){
  report.inputs.push({text,at:new Date().toISOString()});save();
  await p.getByLabel('给助理发消息',{exact:true}).fill(text);
  const response=p.waitForResponse(r=>r.request().method()==='POST'&&/\/api\/conversations\/[^/]+\/turns$/.test(r.url()));
  await p.getByRole('button',{name:'发送',exact:true}).click();return wait(await(await response).json());
 }
 async function start(kind,scope){
  await p.getByRole('button',{name:kind==='loan'?'借用电脑':'IT 报修',exact:true}).click();
  if(scope==='PREVIEW_ONLY')await p.getByLabel('只生成完整预览，绝不提交',{exact:true}).check();
  if(scope==='READ_ONLY')await p.getByLabel('先了解：只查询，不准备申请',{exact:true}).check();
  const response=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/tasks'));
  await p.getByRole('button',{name:'按所选范围开始',exact:true}).click();
  const task=await(await response).json();await p.getByRole('dialog').waitFor();await p.getByRole('button',{name:'关闭详情',exact:true}).click();return task;
 }
 async function open(task){await p.goto(base+'/#/assistant?c='+task.conversation_id);await p.getByRole('button',{name:/查看参数与下一步/}).click();}
 async function ensurePreview(task){
  let current=await get('/api/tasks/'+task.task_id);
  if(!current.preview){
   await open(current);
   const prepared=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/prepare'));
   if(current.guided_request.kind==='loan'){
    const options=await get('/api/product/tasks/'+task.task_id+'/alternatives');assert(options.length);
    report.resource_choice={chosen:options[0],origin:'EXPLICIT_TEST_USER_CURRENT_UI_OPTION'};save();
    const choices=p.locator('details.resource-options');if(!(await choices.getAttribute('open')))await choices.getByText('可选设备与日期',{exact:true}).click();
    await p.getByRole('radio',{name:'选择设备 '+options[0].asset_id,exact:true}).check();await p.getByRole('button',{name:'选择并生成预览',exact:true}).click();
   } else await p.getByRole('button',{name:'生成当前预览',exact:true}).click();
   const response=await prepared;assert(response.ok(),await response.text());
   report.actions.push({action:'EXPLICIT_USER_PREPARE_SHARED_USECASE',result:await response.json()});save();
   await p.getByRole('button',{name:'关闭详情',exact:true}).click();
   current=await get('/api/tasks/'+task.task_id);
  }
  assert(current.preview&&!current.receipt,'No actual preview; do not replace it with an oracle action');return current;
 }
 async function commitPreview(task){
  await open(task);
  report.confirmations.push({scope:'EXACT_CURRENT_TEST_USER_CONFIRMATION',task_id:task.task_id,proposal:task.preview,accepted:true});save();
  const response=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/submit'));
  await p.getByRole('button',{name:'确认并提交当前预览',exact:true}).click();
  const result=await(await response).json();assert(result.receipt);save();
  await p.getByRole('button',{name:'关闭详情',exact:true}).click();return result;
 }
 async function lifecycle(ticketId,names){
  await p.getByRole('link',{name:'演示服务台',exact:true}).click();
  for(const action of names){
   const row=(await get('/api/service-desk')).tickets.find(x=>x.ticket.ticket_id===ticketId);assert(row);
   const candidate=row.actions.find(a=>a.name===action);assert(candidate,action);
   const card=p.getByRole('article',{name:'工单 '+ticketId,exact:true});await card.getByRole('button',{name:candidate.label,exact:true}).click();
   await p.getByLabel('处理说明',{exact:true}).fill('本地合成TEST：'+candidate.label);
   if(action==='extend')await p.getByLabel('新的结束日期',{exact:true}).fill('2026-11-28');
   let response=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/service-desk/proposals'));
   await p.getByRole('button',{name:'查看本次动作预览',exact:true}).click();const preview=await(await response).json();
   report.actions.push({action,preview,confirmed_by:'EXPLICIT_TEST_USER'});save();
   response=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/service-desk/commit'));
   await p.getByRole('button',{name:'确认办理此动作',exact:true}).click();report.actions.at(-1).receipt=await(await response).json();save();
   await p.getByRole('dialog').waitFor({state:'hidden'});
  }
  return (await get('/api/service-desk')).tickets.find(x=>x.ticket.ticket_id===ticketId).ticket;
 }
 try{
  report.instance=await get('/api/instance');assert.equal(report.instance.source_commit,commit,'Actual running source must match measured candidate');report.before=await get('/api/status');assert.equal(report.before.mode,'SYNTHETIC_LOCAL');report.before_desk=await get('/api/service-desk');save();
  let created;
  if(resumeTask){
   created=await get('/api/tasks/'+resumeTask);assert(!created.receipt);assert.equal(created.guided_request.kind,'loan');
   report.recovery_basis='Same task now has the domain rule actually read in the saved failed run; no recreated task, no oracle action.';
   await p.goto(base+'/#/assistant?c='+created.conversation_id);
   await say('继续办理当前任务，保持现有参数与已选设备不变。');
  }else{
   await p.goto(base+'/#/assistant');await p.getByLabel('当前资料库').selectOption(kb);
   created=await start('loan','SUBMIT_AFTER_CONFIRMATION');
   await say('我想从2026年11月24日借到11月26日，用于本地合成现场培训，至少16GB内存。请准备完整预览，并说明借用期限。');
  }
  report.loan_task_id=created.task_id;save();
  let loan=await ensurePreview(created);report.first_loan_preview=loan;save();
  await open(loan);await p.getByLabel(/结束日期/).fill('2026-11-27');
  const next=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/prepare'));
  const patch=p.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().endsWith('/facts'));
  await p.getByRole('button',{name:'保存并生成预览',exact:true}).click();await patch;
  const stale=await p.request.post(base+'/api/tasks/'+loan.task_id+'/submit',{headers:{'X-ESA-Request':'1'},data:{proposal_id:loan.preview.proposal_id,content_digest:loan.preview.content_digest,expected_facts_revision:loan.facts_revision,accepted:true}});
  report.stale_confirmation={status:stale.status(),body:await stale.json()};save();assert.equal(stale.status(),409);
  const preparedResponse=await next;assert(preparedResponse.ok(),await preparedResponse.text());
  await p.getByRole('button',{name:'关闭详情',exact:true}).click();loan=await ensurePreview(loan);
  assert.equal(loan.preview.content.parameters.loan_end,'2026-11-27');loan=await commitPreview(loan);report.loan_receipt=loan.receipt;save();assert.equal(loan.receipt.ticket.status,'PENDING_APPROVAL');
  const again=await post('/api/tasks/'+loan.task_id+'/submit',{proposal_id:loan.preview.proposal_id,content_digest:loan.preview.content_digest,expected_facts_revision:loan.facts_revision,accepted:true});
  assert.equal(again.receipt.command_id,loan.receipt.command_id);report.idempotent=again.receipt;
  await p.screenshot({path:out+'.pending.png',fullPage:true});
  report.returned=await lifecycle(loan.receipt.ticket_id,['approve','checkout','extend','return']);assert.equal(report.returned.status,'RETURNED');assert.equal(report.returned.parameters.loan_end,'2026-11-28');
  await p.goto(base+'/#/assistant?c='+loan.conversation_id);
  const repairCreated=await start('repair','SUBMIT_AFTER_CONFIRMATION');report.repair_task_id=repairCreated.task_id;save();
  await say('我的笔记本无法开机，请帮我准备报修预览。');
  const waiting=await get('/api/tasks/'+repairCreated.task_id);report.repair_clarification=waiting;save();
  assert.equal(waiting.status,'WAITING_USER');assert(waiting.missing_fields.length);
  await open(waiting);await p.locator('[data-field-name="asset_id"]').fill('employee-laptop-1');await p.locator('[data-field-name="impact"]').selectOption('high');
  const repairPrepared=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/prepare'));
  await p.getByRole('button',{name:'保存参数',exact:true}).click();assert((await repairPrepared).ok());await p.getByRole('button',{name:'关闭详情',exact:true}).click();
  let repair=await ensurePreview(repairCreated);repair=await commitPreview(repair);report.repair_receipt=repair.receipt;save();assert.equal(repair.receipt.ticket.status,'OPEN');
  report.closed=await lifecycle(repair.receipt.ticket_id,['start','resolve','close','reopen','start','resolve','close']);assert.equal(report.closed.status,'CLOSED');
  await p.screenshot({path:out+'.closed.png',fullPage:true});
  report.passed=true;
 }catch(error){report.failure=String(error.stack||error);process.exitCode=1;}
 finally{report.after=await get('/api/status');report.after_desk=await get('/api/service-desk');save();await browser.close();console.log(JSON.stringify({passed:report.passed,failure:report.failure,out,before:report.before?.generation_calls,after:report.after.generation_calls}));}
})().catch(e=>{console.error(e);process.exitCode=1});
