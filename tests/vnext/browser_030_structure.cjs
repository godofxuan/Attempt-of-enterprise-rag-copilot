/* Real current browser/API presentation check; no model or ticket submission. */
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
const folder=path.resolve('.private/esa-vnext/upgrade-030-040');
const stamp=new Date().toISOString().replace(/[:.]/g,'-');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1440,height:960}});
 const record={kind:'CURRENT_BROWSER_API_NO_MODEL',errors:[],httpErrors:[]};
 page.on('pageerror',e=>record.errors.push(String(e)));page.on('response',r=>{if(r.status()>=400)record.httpErrors.push([r.status(),r.url()]);});
 try{
  await page.goto('http://127.0.0.1:8740/');
  await page.waitForFunction(()=>document.querySelector('#conversationService').options.length===2);
  await page.locator('nav [data-view=conversations]').click();
  await page.locator('#conversationName').fill('会话界面 TEST <script>');
  await page.locator('#newConversation').click();
  await page.waitForFunction(()=>document.querySelector('#conversationTitle').textContent==='会话界面 TEST <script>');
  await page.getByText('在当前会话开始一个服务事项',{exact:true}).click();
  await page.locator('#conversationService').selectOption('repair');await page.locator('#conversationScope').selectOption('PREVIEW_ONLY');
  await page.locator('#conversationScopeConfirmed').check();await page.locator('#conversationTaskForm button').click();
  await page.waitForSelector('#conversationSide #currentFacts');
  assert.equal(await page.locator('#conversationSide #currentFacts input').count(),2);
  assert.equal(await page.locator('#conversationSide #submitCurrent').count(),0);
  await page.reload();await page.waitForSelector('#conversationSide #currentFacts');
  await page.screenshot({path:path.join(folder,'S1_BROWSER_'+stamp+'.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(200);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  assert.deepEqual(record.errors,[]);assert.deepEqual(record.httpErrors,[]);record.passed=true;
 }catch(e){record.failure=String(e);throw e;}finally{
  fs.writeFileSync(path.join(folder,'S1_BROWSER_'+stamp+'.json'),JSON.stringify(record,null,2));await browser.close();
 }
 console.log(JSON.stringify(record));
})().catch(e=>{console.error(e);process.exitCode=1;});
