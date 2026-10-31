"""AST-only lookup; does not import or execute the product."""
import argparse,ast,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--lesson')
a=p.parse_args();root=Path(__file__).resolve().parents[1]
entries=json.loads((root/'SOURCE_MAP.json').read_text(encoding='utf-8'))
if a.lesson: entries=[x for x in entries if x['lesson']==a.lesson]
def positions(nodes,parents=()):
    out={}
    for n in nodes:
        if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
            symbol='.'.join((*parents,n.name));out[symbol]=(n.lineno,n.end_lineno)
            out.update(positions(n.body,(*parents,n.name)))
    return out
missing=0
for e in entries:
    path=a.source/e['path']
    if not path.exists():
        print(e['id'],'PATH_CHANGED',e['path']);missing+=1;continue
    index=positions(ast.parse(path.read_text(encoding='utf-8')).body)
    span=index.get(e['symbol'])
    if span is None:
        print(e['id'],'SYMBOL_CHANGED',e['path'],e['symbol']);missing+=1
    else:
        print(f"{e['id']} {e['path']}:{span[0]}-{span[1]} :: {e['symbol']}")
print('Missing/changed symbols:',missing,'; historical line numbers must not be silently reused.')
raise SystemExit(1 if missing else 0)
