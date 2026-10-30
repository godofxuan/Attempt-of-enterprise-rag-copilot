"""Actual shipped JS/CSS in Chromium, synthetic read-only API replay.
This is a frontend integration reproduction, NOT a live backend/LLM E2E pass.
"""
import argparse,json,sys,tempfile,threading
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,unquote
from playwright.sync_api import sync_playwright
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True);args=p.parse_args()
src=Path(args.source).resolve();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(src))
from app.workspace import initialize,WorkspaceConfig
from app.workbench_service import TaskService,local_actor
from app.conversations import ConversationService
from app.service_desk.catalog import SERVICES
from app.service_desk.lifecycle import Lifecycle

with tempfile.TemporaryDirectory(prefix='esa040_ui_fixture_') as td:
 root=Path(td);initialize(root,sample=True);w=SimpleNamespace(root=root,db_path=root/'app.sqlite3',config=WorkspaceConfig(sample_data=True))
 w.service=TaskService(w);w.conversations=ConversationService(w)
 c=w.conversations.create('kb-fixture','出差电脑借用 · 合成界面回放');day=w.service.store.today()
 t=w.service.create({'kind':'loan','execution_ceiling':'SUBMIT_AFTER_CONFIRMATION','confirmed':True,'facts':{'loan_start':str(day+timedelta(days=1)),'loan_end':str(day+timedelta(days=3)),'purpose':'出差演示'}},kb_id='kb-fixture',conversation_id=c['id'])
 w.conversations.append(c['id'],'user','message','我需要借用一台电脑，用于出差演示。')
 w.conversations.append(c['id'],'assistant','message','已保存借用需求，请选择可用设备。')
 static={
  '/api/settings':w.config.model_dump(),
  '/api/status':{'web':True,'storage':True,'chat':{'ready':False,'model':'模型未连接（界面回放）'},'embedding':{'ready':False,'model':'bge-m3'},'models':[],'mode':'SYNTHETIC_LOCAL','data_dir':'审核临时合成目录','database':'审核临时数据库','model_error':None},
  '/api/library':{'bases':[{'id':'kb-fixture','name':'合成规则资料库'}],'documents':[],'jobs':[],'directory_sources':[]},
  '/api/tasks':w.service.list(),'/api/services':[s.public() for s in SERVICES.values()],
  '/api/conversations':w.conversations.list(),'/api/conversations/'+c['id']:w.conversations.get(c['id']),
  '/api/tasks/'+t['task_id']:w.service.view(t['task_id']),
  '/api/history':{'tasks':w.service.list(),'conversations':[],'threads':w.conversations.list(),'database':'合成数据库'},
  '/api/service-desk':Lifecycle(w.service.store).list(local_actor())}
 errors=[];result={}
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  page=browser.new_page(viewport={'width':1440,'height':1000})
  page.on('pageerror',lambda e:errors.append(str(e)))
  # Browser network/file navigation is disabled in the review environment.
  # Render original DOM/CSS and JS through local Blob modules without network.
  import re
  web=src/'app/web'
  html=(web/'index.html').read_text()
  html=re.sub(r'<link[^>]+rel="stylesheet"[^>]*>','',html)
  html=re.sub(r'<script.*?</script>','',html,flags=re.S)
  css=(web/'workbench.css').read_text()+'\n'+(web/'tasks.css').read_text()
  html=html.replace('</head>','<style>'+css+'</style></head>')
  page.set_content(html)
  page.evaluate("""([fixture,cid])=>{
    window.__reads=[];
    const m=new Map([['esa-view','conversations'],['esa-conversation',cid]]);
    Object.defineProperty(window,'localStorage',{value:{getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k)}});
    window.fetch=async(path,options)=>{
      const key=new URL(path,'https://esa.test').pathname;window.__reads.push(key);
      const ok=Object.prototype.hasOwnProperty.call(fixture,key);
      return new Response(JSON.stringify(ok?fixture[key]:{error:{message:'No replay fixture '+key}}),{status:ok?200:404,headers:{'Content-Type':'application/json'}});
    };
  }""",[static,c['id']])
  cache={}
  def blob(path):
   path=path.resolve()
   if path in cache:return cache[path]
   text=path.read_text()
   pattern=r"(?P<prefix>(?:from\s*|import\s*)['\"])(?P<path>\.\.?/[^'\"]+)(?P<suffix>['\"])"
   text=re.sub(pattern,lambda m:m['prefix']+blob(path.parent/m['path'])+m['suffix'],text)
   url=page.evaluate("text=>URL.createObjectURL(new Blob([text],{type:'text/javascript'}))",text)
   cache[path]=url;return url
  entry=blob(web/'workbench.js')
  page.evaluate('async url=>{await import(url)}',entry)
  page.wait_for_selector('#conversationSide #taskDetail',state='visible',timeout=5000)
  before=page.locator('#conversationSide #taskDetail').count();textareas=page.locator('textarea:visible').count()
  page.screenshot(path=str(out/'current_conversation_desktop.png'),full_page=True)
  page.locator('nav button[data-view="tasks"]').click()
  page.locator('nav button[data-view="conversations"]').click()
  after=page.locator('#conversationSide #taskDetail').count()
  visible=page.locator('#taskDetail').is_visible()
  page.screenshot(path=str(out/'current_conversation_after_switch.png'),full_page=True)
  result={'mode':'real 5ff9aac2 DOM/CSS/JS in Chromium via Blob module resolution; localStorage/fetch are synthetic replay adapters, domain fixture real; not full backend or LLM E2E',
    'browser':browser.version,'dom_handoff':{'before_task_panels':before,'after_switch_back_task_panels':after,'task_detail_visible_after_switch_back':visible,'result':'DEFECT_REPRODUCED' if before==1 and after==0 and not visible else 'NOT_REPRODUCED'},
    'visible_message_textareas_before_switch':textareas,'page_errors':errors,'api_reads':page.evaluate('window.__reads')}
  browser.close()
(out/'ui_replay.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
