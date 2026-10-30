"""Real child server, owned sockets and current product assets; zero inference."""
import json
import os
import socket
from pathlib import Path

import httpx

from app.launcher.core import open_workspace
from app.workspace import initialize


def test_open_reuses_instance_chooses_free_port_and_preserves_workspace(tmp_path):
    root=tmp_path/'中文 工作区'
    initialize(root)
    config=root/'workspace.json'
    values=json.loads(config.read_text('utf8'));values['model_endpoint']='http://127.0.0.1:1'
    config.write_text(json.dumps(values),'utf8')
    registry=tmp_path/'registered.json'
    blocker=socket.socket();blocker.bind(('127.0.0.1',0));blocker.listen()
    occupied=blocker.getsockname()[1]
    first=None
    try:
        first=open_workspace(root,registry=registry,port=occupied,browser=False)
        assert first['url']!='http://127.0.0.1:'+str(occupied)
        assert first['pid']!=os.getpid() and not first['reused']
        second=open_workspace(root,registry=registry,port=occupied,browser=False)
        assert second['reused'] and second['instance_id']==first['instance_id']
        with httpx.Client(base_url=first['url'],trust_env=False,timeout=5,headers={'X-ESA-Request':'1'}) as client:
            assert '/ui/assets/' in client.get('/').text
            status=client.get('/api/status').json()
            assert status['storage'] and not status['chat']['ready'] and status['generation_calls']==0
            assert client.get('/api/conversations').status_code==200
            assert client.get('/api/settings').status_code==200
            assert client.post('/api/product/shutdown').status_code==200
    finally:
        blocker.close()
        if first:
            try:httpx.post(first['url']+'/api/product/shutdown',headers={'X-ESA-Request':'1'},timeout=2,trust_env=False)
            except httpx.HTTPError:pass
