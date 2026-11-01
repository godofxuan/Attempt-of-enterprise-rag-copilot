"""Check this teaching subset only; never writes learner progress."""
from pathlib import Path
import json,ast
r=Path(__file__).resolve().parents[1]
def rows(n):return [json.loads(x) for x in (r/n).read_text(encoding='utf-8').splitlines() if x]
q=rows('questions.jsonl');a=rows('answers.jsonl');lessons=rows('lessons.jsonl')
assert len(q)==len(a)==48 and len(lessons)==8
assert len({x['id'] for x in q})==48
assert {x['id'] for x in q}=={x['id'] for x in a}
for x in q:assert not {'answer','explanation','solution'}.intersection(x)
for x in lessons:
 assert (r/x['document']).exists()
 for lab in x['labs']:assert (r/f'labs/{lab}.py').exists()
for p in r.rglob('*.py'):ast.parse(p.read_text(encoding='utf-8'))
assert len(json.loads((r/'SOURCE_MAP.json').read_text(encoding='utf-8')))==24
print('48 questions, 48 answers, 8 lessons, 24 source anchors: resources OK; no learner state changed.')
