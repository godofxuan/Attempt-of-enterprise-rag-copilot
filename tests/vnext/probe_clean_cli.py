"""Real installed CLI/network/restart check; creates TEST data, no model inference."""
import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

import httpx


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--code', type=Path, required=True)
parser.add_argument('--port', type=int, default=8742)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
code = args.code.resolve()
binary = code / '.venv' / ('Scripts/esa.exe' if os.name == 'nt' else 'bin/esa')
caller = code / '.private/cli-caller'
caller.mkdir(parents=True, exist_ok=False)
data = code / '.private/cli-data'
environment = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'ESA_DATA_DIR'}}
environment['PYTHONUTF8'] = '1'
creation = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
record = {'kind': 'INSTALLED_CLI_REAL_HTTP_NO_INFERENCE', 'code': str(code),
          'caller': str(caller), 'data': str(data), 'starts': []}
init = subprocess.run([str(binary), 'init', '--sample', '--data-dir', str(data)],
    cwd=caller, env=environment, creationflags=creation, capture_output=True, text=True,
    encoding='utf8', timeout=20, check=True)
record['init_stdout'] = init.stdout
with sqlite3.connect(data / 'app.sqlite3') as db:
    initialized = db.execute("SELECT value FROM workspace_meta WHERE key='initialized_at'").fetchone()[0]
base = 'http://127.0.0.1:' + str(args.port)
for stage in range(2):
    out_path = args.output.with_suffix('.start' + str(stage) + '.log')
    started = time.monotonic()
    with out_path.open('w', encoding='utf8') as output:
        process = subprocess.Popen([str(binary), 'serve', '--data-dir', str(data), '--port', str(args.port)],
            cwd=caller, env=environment, stdout=output, stderr=subprocess.STDOUT, creationflags=creation)
        try:
            with httpx.Client(base_url=base, trust_env=False, timeout=3, headers={'X-ESA-Request': '1'}) as client:
                for attempt in range(80):
                    assert process.poll() is None, out_path.read_text('utf8')
                    try:
                        if client.get('/health/live').status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                else:
                    raise TimeoutError('Clean installed server did not become live')
                record['starts'].append({'stage': stage, 'startup_seconds': round(time.monotonic()-started, 3)})
                assert client.get('/').status_code == client.get('/assets/workbench.js').status_code == 200
                assert client.get('/api/status').json()['storage']
                if stage == 0:
                    today = date.today()
                    result = client.post('/api/tasks', json={'request': {'kind': 'loan', 'confirmed': True,
                        'execution_ceiling': 'READ_ONLY', 'facts': {'loan_start': str(today+timedelta(days=1)),
                        'loan_end': str(today+timedelta(days=2)), 'purpose': '独立启动TEST记录'}}})
                    result.raise_for_status()
                    record['task'] = result.json()
                else:
                    restored = client.get('/api/tasks/' + record['task']['task_id']).json()
                    assert restored['task_id'] == record['task']['task_id']
                    assert restored['facts'] == record['task']['facts']
                    record['restored'] = restored
        finally:
            process.terminate()
            process.wait(timeout=15)
with sqlite3.connect(data / 'app.sqlite3') as db:
    assert db.execute("SELECT value FROM workspace_meta WHERE key='initialized_at'").fetchone()[0] == initialized
    assert db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM it_repair_tickets').fetchone()[0] == 0
record.update(passed=True, model_calls=0, business_tickets=0)
args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2), 'utf8')
print(json.dumps({'passed': True, 'starts': record['starts'], 'output': str(args.output)}, ensure_ascii=False))
