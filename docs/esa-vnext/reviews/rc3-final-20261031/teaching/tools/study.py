"""Read one resource at a time. No progress writes; no product imports."""
import argparse, json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
g=sub.add_parser('get');g.add_argument('id');g.add_argument('--answer',action='store_true')
s=sub.add_parser('search');s.add_argument('text')
a=p.parse_args()
questions=[json.loads(line) for line in (root/'questions.jsonl').read_text(encoding='utf-8').splitlines() if line]
if a.command=='search':
    for q in questions:
        if a.text.lower() in (q['title']+' '+q['question']).lower(): print(q['id'],q['title'])
else:
    found=next((q for q in questions if q['id']==a.id),None)
    if found is None: raise SystemExit('Unknown question ID; no state was changed.')
    print(json.dumps(found,ensure_ascii=False,indent=2))
    if a.answer:
        for line in (root/'answers.jsonl').read_text(encoding='utf-8').splitlines():
            answer=json.loads(line)
            if answer['id']==a.id:print(json.dumps(answer,ensure_ascii=False,indent=2));break
