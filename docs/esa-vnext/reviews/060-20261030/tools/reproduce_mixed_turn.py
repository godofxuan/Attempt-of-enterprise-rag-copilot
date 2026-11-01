import sys,asyncio,tempfile,json
from pathlib import Path
from types import SimpleNamespace
import argparse, os
parser=argparse.ArgumentParser(description="Reproduce ORIGINAL 0.6 findings; not fixed-version acceptance. Uses only synthetic temporary workspaces.")
parser.add_argument("--source", type=Path, required=True, help="Root of extracted 0.6 source containing app/ and tests/")
parser.add_argument("--out", type=Path, default=Path("review-probe-output"))
args=parser.parse_args()
source=args.source.resolve()
if not (source/"app/workbench_app.py").is_file():
    parser.error("--source must point to the actual project root")
args.out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(source))
os.environ["PYTHONPATH"]=str(source)+os.pathsep+os.environ.get("PYTHONPATH", "")
from tests.vnext.test_upgrade_paths import workspace
from tests.vnext.test_conversations import SequenceModel
from tests.vnext.test_service_lifecycle import create
from app.conversations import ConversationService
async def check(root):
 w=workspace(root);w.conversations=ConversationService(w);task=create(w.service);calls=[]
 async def answer(kb,q,**kw):
  calls.append(q);return {'id':'synthetic_knowledge','conversation_id':task['conversation_id'],'kb_id':kb,'question':q,'result':{'mode':'answered','answer':'这是合成政策说明。','sources':[]}}
 w.library=SimpleNamespace(answer=answer)
 # Attach a valid knowledge scope to the real task; only the external model/answer is scripted.
 from app.workbench_service import local_actor
 with w.service.store.transaction() as db:
  current=w.service.store._task(db,local_actor(),task['task_id']);current['kb_id']='probe-kb';w.service.store._save(db,current)
 w.models=SequenceModel([('loan_policy',{}),('assets_search',{}),('tickets_list_mine',{})],[('prepare_preview',{'asset_id':'loan-laptop-1'}),('knowledge_answer',{'question':'是否需要押金？'})])
 result=await w.service.message(task['task_id'],'先准备借用预览，再解释是否需要押金；不要提交。','prepare-and-explain',task['facts_revision'])
 row={'id':'F06_PREVIEW_EARLY_RETURN_DROPS_PENDING_TOOL','method':'real service/run/store with scripted model tool batches and synthetic knowledge adapter','proposed_second_batch':['prepare_preview','knowledge_answer'],'preview_created':bool(result.get('preview')),'knowledge_calls':calls,'knowledge_result':result.get('knowledge_result'),'message_done':w.conversations.turns(result['conversation_id'])[0]['status'],'receipt_exists':bool(result.get('receipt')),'defect_reproduced':bool(result.get('preview')) and not calls}
 await w.runs.close();return row
with tempfile.TemporaryDirectory(prefix='esa-review-mixed-') as td: row=asyncio.run(check(Path(td)))
out=args.out.resolve()/'mixed_request_probe.json';out.write_text(json.dumps(row,ensure_ascii=False,indent=2));print(out.read_text())
