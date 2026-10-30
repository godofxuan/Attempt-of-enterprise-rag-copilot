"""Run README CLI from an unrelated caller using only the installed wheel package."""
import json,os,sqlite3,subprocess,time,argparse
from pathlib import Path
import httpx

parser=argparse.ArgumentParser();parser.add_argument('--label',default='wheel-040');args=parser.parse_args()
root=Path('.private/esa-vnext/build').resolve();site=root/(args.label+'-site')
python=root/'clean-670fdb66/.venv/Scripts/python.exe';caller=root/(args.label+'-caller');caller.mkdir(exist_ok=False)
data=caller/'data';folder=Path('.private/esa-vnext/upgrade-030-040').resolve()
env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','ESA_DATA_DIR')};env.update(PYTHONPATH=str(site),PYTHONUTF8='1')
record={'kind':'INSTALLED_WHEEL_CLI_REAL_HTTP_NO_INFERENCE','package_site':str(site),'dependency_environment':str(python.parent.parent),'starts':[]}
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
def command(*args):
 r=subprocess.run([str(python),'-B','-X','utf8',*args],cwd=caller,env=env,creationflags=flags,capture_output=True,text=True,encoding='utf8',timeout=25)
 assert r.returncode==0,r.stderr
 return r.stdout
try:
 record['package']=json.loads(command('-c',"import app.cli,importlib.metadata,json;from importlib.resources import files;print(json.dumps({'path':app.cli.__file__,'version':importlib.metadata.version('enterprise-service-agent'),'resource':files('app.resources').joinpath('sample_meeting.md').is_file()}))"))
 assert Path(record['package']['path']).resolve().is_relative_to(site) and record['package']['version']=='0.4.0' and record['package']['resource']
 record['init']=command('-m','app.cli','init','--sample','--data-dir',str(data))
 record['doctor']=json.loads(command('-m','app.cli','doctor','--data-dir',str(data)))
 assert record['doctor']['inspection']=='READ_ONLY_NO_STARTUP_OR_RECOVERY'
 for stage in range(2):
  started=time.monotonic()
  with (folder/f'{args.label.upper()}_START_{stage}.log').open('w',encoding='utf8') as log:
   p=subprocess.Popen([str(python),'-B','-X','utf8','-m','app.cli','serve','--data-dir',str(data),'--port','8742'],cwd=caller,env=env,creationflags=flags,stdout=log,stderr=subprocess.STDOUT)
   try:
    with httpx.Client(base_url='http://127.0.0.1:8742',timeout=3,trust_env=False,headers={'X-ESA-Request':'1'}) as c:
     for _ in range(80):
      assert p.poll() is None,'Installed server exited'
      try:
       if c.get('/health/live').status_code==200:break
      except httpx.TransportError:pass
      time.sleep(.1)
     else:raise TimeoutError('Installed server not live')
     status=c.get('/api/status').json();assert Path(status['data_dir'])==data
     record['starts'].append({'stage':stage,'seconds':round(time.monotonic()-started,3)})
     assert c.get('/').status_code==c.get('/assets/ui/service-desk.js').status_code==200
     assert c.get('/api/service-desk').json()['origin']=='LOCAL_SYNTHETIC_TEST_ONLY'
     if stage==0:
      r=c.post('/api/conversations',json={'title':'wheel重启保留记录'});r.raise_for_status();record['conversation']=r.json()
     else:assert c.get('/api/conversations/'+record['conversation']['id']).json()['title']=='wheel重启保留记录'
   finally:p.terminate();p.wait(timeout=15)
 with sqlite3.connect(data/'app.sqlite3') as db:
  assert db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0]==0
  assert db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]==db.execute('SELECT COUNT(*) FROM it_repair_tickets').fetchone()[0]==0
 record['passed']=True
except BaseException as e:record['failure']={'type':type(e).__name__,'message':str(e)};raise
finally:(folder/(args.label.upper()+'_PROBE.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf8')
print(json.dumps({'passed':record.get('passed'),'starts':record['starts'],'output':str(folder/(args.label.upper()+'_PROBE.json'))},ensure_ascii=False))
