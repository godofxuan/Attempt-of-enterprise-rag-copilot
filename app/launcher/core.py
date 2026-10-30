"""Discover an owned local instance, or start the same product factory once."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import webbrowser

import httpx
from app.runtime.workspace_lock import WorkspaceLease

APP_ID = 'esa-workbench'

def registry_path(value=None):
    return Path(value) if value else Path(os.getenv('LOCALAPPDATA', Path.home())) / 'ESA' / 'workspaces.json'

def read_json(path):
    try:
        return json.loads(path.read_text('utf8'))
    except (OSError, ValueError):
        return {}

def remember(root, registry):
    record=read_json(registry)
    known=list(dict.fromkeys([str(root), *record.get('known', [])]))
    registry.parent.mkdir(parents=True, exist_ok=True)
    temp=registry.with_suffix('.tmp')
    temp.write_text(json.dumps({'current':str(root),'known':known},ensure_ascii=False,indent=2),'utf8')
    temp.replace(registry)

def selected_workspace(value, registry):
    if value:return Path(value).expanduser().resolve()
    if os.getenv('ESA_DATA_DIR'):return Path(os.environ['ESA_DATA_DIR']).resolve()
    record=read_json(registry)
    if record.get('current'):return Path(record['current']).resolve()
    development=Path.cwd()/'.private/esa-vnext'
    if (development/'workspace.json').is_file() and (development/'app.sqlite3').is_file():return development.resolve()
    return (Path.home()/'.esa').resolve()

def running_instance(root):
    info=read_json(root/'instance.json')
    if not info.get('url') or not info.get('instance_id'):return None
    try:
        from urllib.parse import urlsplit
        if urlsplit(info['url']).hostname not in {'127.0.0.1','::1','localhost'}:return None
        with httpx.Client(trust_env=False,timeout=1,follow_redirects=False) as client:
            response=client.get(info['url']+'/api/instance')
            response.raise_for_status(); actual=response.json()
        if actual.get('app')==APP_ID and actual.get('instance_id')==info['instance_id'] and Path(actual['data_dir']).resolve()==root.resolve() and actual.get('ready'):
            return actual
    except (httpx.HTTPError, ValueError, KeyError):pass
    return None

def open_workspace(root, *, registry=None, port=8740, browser=True, wait_seconds=25):
    root=Path(root).resolve(); registry=registry_path(registry)
    root.mkdir(parents=True,exist_ok=True)
    lease=None; deadline=time.monotonic()+wait_seconds
    while lease is None:
        try:lease=WorkspaceLease(root,'launcher.lock').acquire()
        except RuntimeError:
            if time.monotonic()>=deadline:raise RuntimeError('另一个启动操作仍在进行，请稍后重新打开。')
            time.sleep(.15)
    try:
        existing=running_instance(root)
        if existing:
            remember(root,registry)
            if browser:webbrowser.open(existing['url'])
            return {**existing,'reused':True}
        # Do not guess ownership from a port or kill an old/unrelated process.
        try:
            with WorkspaceLease(root):pass
        except RuntimeError as exc:
            raise RuntimeError('此工作区已有旧版本实例。请从原窗口停止服务后再打开；资料未被修改。') from exc
        from app.workspace import initialize
        if not (root/'workspace.json').exists():initialize(root)
        log_path=root/'logs/launcher.log'; log_path.parent.mkdir(exist_ok=True)
        executable=Path(sys.executable)
        if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
        environment=os.environ.copy(); environment['PYTHONUTF8']='1'; environment['PYTHONNOUSERSITE']='1'
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        with log_path.open('a',encoding='utf8') as log:
            process=subprocess.Popen([str(executable),'-B','-X','utf8','-m','app.launcher','serve','--data-dir',str(root),'--port',str(port)],
                stdout=log,stderr=subprocess.STDOUT,creationflags=flags,env=environment)
        while time.monotonic()<deadline:
            info=running_instance(root)
            if info:
                remember(root,registry)
                if browser:webbrowser.open(info['url'])
                return {**info,'reused':False}
            if process.poll() is not None:raise RuntimeError('启动未完成。请查看日志：'+str(log_path))
            time.sleep(.15)
        raise RuntimeError('服务仍未就绪。未终止任何进程；请查看日志：'+str(log_path))
    finally:lease.close()

def serve_workspace(root, port=8740, *, auto_port=True, host='127.0.0.1'):
    import uvicorn
    from app.config import Settings
    from app.workspace import load_config
    from app.workbench_app import create_workbench_app
    root=Path(root).resolve()
    sock=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_STREAM)
    if os.name=='nt':sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
    try:
        try:sock.bind((host,port))
        except OSError:
            if not auto_port:raise
            sock.bind((host,0))
        sock.listen(2048);sock.setblocking(False)
        actual_port=sock.getsockname()[1]; url='http://'+('['+host+']' if ':' in host else host)+':'+str(actual_port)
        app=create_workbench_app(Settings(workbench_enabled=True,data_dir=root,sqlite_path=root/'app.sqlite3'))
        workspace=app.state.workspace
        workspace.instance_info={'app':APP_ID,'instance_id':uuid.uuid4().hex,'data_dir':str(root),'url':url,'pid':os.getpid()}
        server=uvicorn.Server(uvicorn.Config(app,host=host,port=actual_port,access_log=False))
        workspace.request_shutdown=lambda:setattr(server,'should_exit',True)
        print('Workspace:',root,flush=True);print('URL:',url,flush=True)
        server.run(sockets=[sock])
    finally:sock.close()

def main():
    parser=argparse.ArgumentParser(prog='esa-launcher');parser.add_argument('action',choices=['open','serve'],nargs='?',default='open')
    parser.add_argument('--data-dir');parser.add_argument('--registry');parser.add_argument('--port',type=int,default=8740);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    root=selected_workspace(args.data_dir,registry_path(args.registry))
    if args.action=='serve':serve_workspace(root,args.port)
    else:print(json.dumps(open_workspace(root,registry=args.registry,port=args.port,browser=not args.no_browser),ensure_ascii=False))
