// A real contextual follow-up from persisted history; no old answer fed as evidence.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert'),path=require('path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage();
 const out=path.resolve('.private/esa-vnext/logs/FOLLOWUP_'+new Date().toISOString().replace(/[:.]/g,'-')+'.json'),record={kind:'REAL_UI_MODEL_FOLLOWUP',errors:[]};
 page.on('pageerror',e=>record.errors.push(e.message));
 try{await page.goto('http://127.0.0.1:8740/');await page.getByRole('button',{name:'知识问答',exact:true}).click();
  const history=await(await page.request.get('http://127.0.0.1:8740/api/history')).json();record.previous=history.conversations.find(a=>a.question.includes('维修')&&a.result.sources.length);
  assert(record.previous);await page.locator('#answerHistory article').filter({has:page.getByRole('heading',{name:record.previous.question,exact:true})}).first().getByRole('button',{name:'继续追问'}).click();
  record.question='那押金可以当作零元吗？';await page.locator('#question').fill(record.question);await page.locator('#askForm button').first().click();
  let runId;for(let n=0;n<100&&!runId;n++){runId=await page.evaluate(()=>localStorage.getItem('esa-active-run'));if(!runId)await page.waitForTimeout(100);}assert(runId);
  for(let n=0;n<245;n++){record.run=await(await page.request.get('http://127.0.0.1:8740/api/runs/'+runId)).json();if(!['queued','running'].includes(record.run.status))break;await page.waitForTimeout(1000);}
  assert.equal(record.run.status,'succeeded',record.run.error);const answer=record.run.result;assert.equal(answer.conversation_id,record.previous.conversation_id);assert(answer.result.answer.includes('未规定'));assert(answer.result.answer.includes('不能')||answer.result.answer.includes('不可'));assert(answer.result.sources.length);
  await page.reload();await page.getByRole('heading',{name:record.question,exact:true}).waitFor();await page.screenshot({path:out.replace('.json','.png'),fullPage:true});assert.deepEqual(record.errors,[]);record.passed=true;
 }catch(e){record.error=e.stack;process.exitCode=1;}finally{fs.writeFileSync(out,JSON.stringify(record,null,2));console.log(JSON.stringify({passed:record.passed,error:record.error,result:record.run?.result?.result}));await browser.close();}
})();
