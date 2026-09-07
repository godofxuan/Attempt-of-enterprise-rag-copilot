"""Block outgoing sockets without substituting product logic."""
import json, socket, sys, threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ATTEMPTS=[]
ORIGINAL_CONNECT=socket.socket.connect
ORIGINAL_PAIR=socket.socketpair
LOCAL=threading.local()
def pair(*a,**kw):
 LOCAL.in_pair=True
 try: return ORIGINAL_PAIR(*a,**kw)
 finally: LOCAL.in_pair=False
def blocked(*a,**kw):
 if getattr(LOCAL,'in_pair',False) and len(a)>1 and a[1][0] in {'127.0.0.1','::1'}:
  return ORIGINAL_CONNECT(*a,**kw)
 ATTEMPTS.append('outbound_socket_blocked')
 raise RuntimeError('Audit forbids network and live models')
socket.socket.connect=blocked
socket.socket.connect_ex=blocked
socket.create_connection=blocked
socket.socketpair=pair
def pytest_sessionfinish(session,exitstatus):
 paths={n:str(m.__file__) for n,m in sys.modules.items() if n.startswith(('app.','tests.')) and getattr(m,'__file__',None)}
 label='external' if any('external_checks' in str(a) for a in session.config.args) else 'existing'
 path=ROOT/'audit'/('imports_'+label+'.json')
 if path.exists(): path=ROOT/'audit'/('imports_'+label+'_retry.json')
 path.write_text(json.dumps(dict(modules=paths,blocked_network_attempts=ATTEMPTS,exitstatus=int(exitstatus)),indent=2),encoding='utf8')
