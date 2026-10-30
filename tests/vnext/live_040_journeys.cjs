/* Finite current browser + native Ollama choices + same persistent TEST database. */
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert'),cp=require('child_process');
const root=path.resolve('.private/esa-vnext'),folder=path.join(root,'upgrade-030-040');
const output=path.join(folder,'S3_UI_'+new Date().toISOString().replace(/[:.]/g,'-'));
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1500,height:1050}});
 const resume=process.env.ESA_RESUME_JOURNEY;const previous=resume?JSON.parse(fs.readFileSync(resume,'utf8')):null;const record={...(previous||{}),resumed_from:resume,kind:'REAL_LOCAL_MODEL_BROWSER_SAME_DATABASE',commit:cp.execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),runs:[],actions:[],errors:[]};
 page.on('pageerror',e=>record.errors.push(e.message));
 const save=()=>fs.writeFileSync(output+'.json',JSON.stringify(record,null,2));
 const get=async p=>{const r=await page.request.get('http://127.0.0.1:8740'+p);assert(r.ok(),await r.text());return r.json();};
 const database=()=>JSON.parse(cp.execFileSync(path.resolve('.venv/Scripts/python.exe'),['-B','-X','utf8','-c',
   "import sqlite3,json,sys;c=sqlite3.connect(sys.argv[1]);print(json.dumps({t:c.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in ['tickets','it_repair_tickets','repairs','asset_reservations','command_ledger','confirmations','model_calls']},ensure_ascii=False))",path.join(root,'app.sqlite3')],{encoding:'utf8',maxBuffer:20*1024*1024}));
 async function waitRun(run){let r;for(let n=0;n<245;n++){r=await get('/api/runs/'+run.id);if(!['running','queued'].includes(r.status))break;await page.waitForTimeout(1000);}record.runs.push(r);save();assert.equal(r.status,'succeeded',r.error);return r;}
 async function clickRun(locator,needle){const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes(needle));await locator.click();const r=await response;assert(r.ok(),await r.text());return waitRun(await r.json());}
 async function deskAction(kind,id,name){await page.locator('nav [data-view=desk]').click();await page.locator('[data-ticket-id="'+id+'"]').waitFor();
  const card=page.locator('[data-ticket-id="'+id+'"]');await card.locator('textarea').fill('明确的本地合成 TEST 操作：'+name);
  const preview=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/service-desk/proposals'));
  await card.locator('[data-action="'+name+'"]').click();const p=await preview;assert(p.ok(),await p.text());record.actions.push({kind,id,name,preview:await p.json()});save();
  await card.locator('input[type=checkbox]').check();const committed=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/service-desk/commit'));
  await card.getByRole('button',{name:'确认当前处理',exact:true}).click();const r=await committed;assert(r.ok(),await r.text());const receipt=await r.json();record.actions.at(-1).receipt=receipt;save();return receipt.ticket;
 }
 async function newTask(kind){await page.locator('nav [data-view=tasks]').click();await page.locator('#newTaskPanel').evaluate(e=>e.open=true);
  await page.locator('#taskKind').selectOption(kind);await page.locator('#taskScope').selectOption('SUBMIT_AFTER_CONFIRMATION');await page.locator('#taskBase').selectOption('kb_18fb91057a234ace');await page.locator('#scopeConfirmed').check();
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/tasks'));await page.locator('#newTaskForm button').click();const r=await response;assert(r.ok(),await r.text());const task=await r.json();await page.locator('#taskDetail[data-task-id="'+task.task_id+'"]').waitFor();return task;
 }
 async function refreshTask(task){await page.reload();await page.locator('#taskDetail[data-task-id="'+task.task_id+'"]').waitFor();return get('/api/tasks/'+task.task_id);}
 async function submit(task){await page.locator('#exactConfirmation').check();const done=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/tasks/'+task.task_id+'/submit'));await page.locator('#submitCurrent').click();const r=await done;assert(r.ok(),await r.text());return r.json();}
 try{
  record.before=record.before||database();record.resume_calls_before=(await get('/api/status')).generation_calls;if(record.calls_before===undefined)record.calls_before=record.resume_calls_before;delete record.failure;save();await page.goto('http://127.0.0.1:8740/');await page.waitForFunction(()=>document.querySelector('#taskKind').options.length===3);
  let task;
  if(!resume){
  // Finish old existing synthetic records through the actual UI, never editing SQL.
  const old=await get('/api/service-desk');for(const item of old.tickets){if(item.kind==='loan'&&item.ticket.status==='PENDING_APPROVAL')await deskAction('loan',item.ticket.ticket_id,'withdraw');
   if(item.kind==='repair'){let t=item.ticket;for(const [from,action] of [['OPEN','start'],['IN_PROGRESS','resolve'],['RESOLVED','close']])if(t.status===from)t=await deskAction('repair',t.ticket_id,action);}}
  task=await newTask('loan');record.loan_task_id=task.task_id;save();
  // Real run cancellation and continuation, preserving the same task.
  let resp=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/tasks/'+task.task_id+'/runs'));await page.getByRole('button',{name:'继续处理',exact:true}).click();let run=await(await resp).json();
  const cancel=await page.request.post('http://127.0.0.1:8740/api/runs/'+run.id+'/cancel',{headers:{'X-ESA-Request':'1'},data:{}});assert(cancel.ok());
  for(let n=0;n<30;n++){const r=await get('/api/runs/'+run.id);if(!['running','queued'].includes(r.status)){record.cancelled_run=r;break;}await page.waitForTimeout(200);}
  task=await refreshTask(task);assert(!task.active_run_id&&task.status!=='CANCELLED');save();
  const form=page.locator('#taskDetail form').filter({has:page.getByRole('heading',{name:'当前会话消息',exact:true})});
  const text='我需要从2026年11月2日借到11月4日，用途是现场办公。设备至少16GB内存，在B区服务台领取。另外这份借用规则是否要求押金？';record.mixed_input=text;
  await form.locator('textarea').fill(text);await clickRun(form.getByRole('button',{name:'发送消息',exact:true}),'/messages');task=await refreshTask(task);record.mixed_result=task;save();
  assert.equal(task.facts.loan_start,'2026-11-02');assert.equal(task.facts.loan_end,'2026-11-04');assert.equal(task.facts.min_memory_gb,16);assert.equal(task.facts.pickup_location,'B区服务台');assert(task.knowledge_result.result.answer.includes('押金'));
  await page.getByRole('button',{name:'查看真实可选设备',exact:true}).click();const card=page.locator('#taskDetail article').filter({has:page.getByRole('heading',{name:'loan-laptop-2',exact:true})});
  await clickRun(card.getByRole('button',{name:'选择此设备',exact:true}),'/runs');task=await refreshTask(task);assert(task.preview);record.first_preview=task.preview;save();
  }else{
   task=await get('/api/tasks/'+record.loan_task_id);await page.evaluate(id=>{localStorage.setItem('esa-task',id);localStorage.setItem('esa-view','tasks');},task.task_id);task=await refreshTask(task);
   await clickRun(page.getByRole('button',{name:'继续处理',exact:true}),'/runs');task=await refreshTask(task);assert(task.preview);record.first_preview=task.preview;save();
  }
  await page.locator('#exactConfirmation').check();await page.locator('[name=loan_end]').fill('2026-11-06');assert(!(await page.locator('#exactConfirmation').isChecked()));
  await clickRun(page.getByRole('button',{name:'保存参数',exact:true}),'/runs');task=await refreshTask(task);record.changed=task;save();
  const stale=await page.request.post('http://127.0.0.1:8740/api/tasks/'+task.task_id+'/submit',{headers:{'X-ESA-Request':'1'},data:{proposal_id:record.first_preview.proposal_id,content_digest:record.first_preview.content_digest,expected_facts_revision:task.facts_revision,accepted:true}});
  record.stale={status:stale.status(),body:await stale.json()};assert.equal(stale.status(),409);assert(task.preview);
  task=await submit(task);record.submission=task;assert.equal(task.receipt.ticket.status,'PENDING_APPROVAL');assert.equal(task.receipt.ticket.parameters.loan_end,'2026-11-06');save();
  await page.screenshot({path:output+'_SUBMITTED.png',fullPage:true});
  let ticket=await deskAction('loan',task.receipt.ticket_id,'approve');assert.equal(ticket.status,'RESERVED');
  let state=await get('/api/service-desk');assert(state.reservations.some(r=>r.ticket_id===ticket.ticket_id&&r.active===1));
  ticket=await deskAction('loan',ticket.ticket_id,'checkout');ticket=await deskAction('loan',ticket.ticket_id,'return');assert.equal(ticket.status,'RETURNED');
  state=await get('/api/service-desk');assert(state.reservations.some(r=>r.ticket_id===ticket.ticket_id&&r.active===0));
  const current=await get('/api/tasks/'+task.task_id);assert.deepEqual(current.receipt,task.receipt);assert.equal(current.current_ticket.status,'RETURNED');record.returned=current;save();
  let second=await newTask('loan');record.second_loan_task_id=second.task_id;save();
  for(const [key,value] of Object.entries({loan_start:'2026-11-09',loan_end:'2026-11-10',purpose:'归还后同一数据目录再次申请'}))await page.locator('[name='+key+']').fill(value);
  await clickRun(page.getByRole('button',{name:'保存参数',exact:true}),'/runs');second=await refreshTask(second);assert(second.preview);second=await submit(second);record.second_submission=second;save();await deskAction('loan',second.receipt.ticket_id,'withdraw');
  let repair=await newTask('repair');record.repair_task_id=repair.task_id;save();await clickRun(page.getByRole('button',{name:'继续处理',exact:true}),'/runs');repair=await refreshTask(repair);assert(repair.question.includes('故障')&&repair.question.includes('设备'));
  const repairForm=page.locator('#taskDetail form').filter({has:page.getByRole('heading',{name:'当前会话消息',exact:true})});record.repair_input='我的设备编号是employee-laptop-1，屏幕间歇闪烁，影响程度高。请按当前任务准备报修预览。';
  await repairForm.locator('textarea').fill(record.repair_input);await clickRun(repairForm.getByRole('button',{name:'发送消息',exact:true}),'/messages');repair=await refreshTask(repair);record.repair_normalized=repair;save();
  if(!repair.preview){await clickRun(page.getByRole('button',{name:'继续处理',exact:true}),'/runs');repair=await refreshTask(repair);}
  assert.equal(repair.facts.impact,'high');assert(repair.preview);repair=await submit(repair);assert.equal(repair.receipt.ticket.status,'OPEN');record.repair_submission=repair;save();
  let rt=repair.receipt.ticket;for(const name of ['start','resolve','close'])rt=await deskAction('repair',rt.ticket_id,name);assert.equal(rt.status,'CLOSED');record.repair_closed=await get('/api/tasks/'+repair.task_id);
  await page.reload();await page.locator('nav [data-view=desk]').click();await page.locator('[data-ticket-id="'+rt.ticket_id+'"]').waitFor();await page.screenshot({path:output+'_CLOSED.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  record.after=database();record.calls_after=(await get('/api/status')).generation_calls;
  assert.equal(record.after.tickets.length,record.before.tickets.length+2);assert.equal(record.after.it_repair_tickets.length,record.before.it_repair_tickets.length+1);assert.deepEqual(record.before.repairs,record.after.repairs);assert.deepEqual(record.errors,[]);record.passed=true;
 }catch(e){record.failure=e.stack;process.exitCode=1;}finally{record.calls_after=(await get('/api/status')).generation_calls;save();console.log(JSON.stringify({passed:record.passed,failure:record.failure,loan:record.loan_task_id,repair:record.repair_task_id,calls_before:record.calls_before,calls_after:record.calls_after,output}));await browser.close();}
})();
