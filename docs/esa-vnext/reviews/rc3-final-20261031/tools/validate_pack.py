"""Read-only resource validation. No hashes, no product changes, no student-state writes."""
from pathlib import Path
import argparse, json, ast

p=argparse.ArgumentParser()
p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
a=p.parse_args();r=a.root.resolve()
def readj(rel): return json.loads((r/rel).read_text(encoding='utf-8'))
def rows(rel): return [json.loads(s) for s in (r/rel).read_text(encoding='utf-8').splitlines() if s.strip()]
required=['00_START_HERE.md','01_AUDIT.md','02_FINAL_PLAN.md','03_CODEX_ENGINEERING.md','04_ACCEPTANCE.md','work_items.jsonl','acceptance.jsonl','REFERENCES.md','teaching/01_CODEX_TEACHING.md','teaching/NEXT_LESSON.md','teaching/lessons.jsonl','teaching/questions.jsonl','teaching/answers.jsonl','teaching/SOURCE_MAP.json','teaching/tools/study.py','teaching/tools/locate_source.py','tools/reproduce_rc3.py','evidence/current_probes.json']
for rel in required: assert (r/rel).is_file(), f'Missing: {rel}'
q=rows('teaching/questions.jsonl');ans=rows('teaching/answers.jsonl');lessons=rows('teaching/lessons.jsonl');sm=readj('teaching/SOURCE_MAP.json')
assert len(q)==48 and len(ans)==48 and len(lessons)==8
qids=[x['id'] for x in q];aids=[x['id'] for x in ans]
assert len(set(qids))==len(qids) and set(qids)==set(aids) and len(set(aids))==len(aids)
sourceids={x['id'] for x in sm}
for x in q:
    assert x['question'].strip() and x['source_refs']
    assert set(x['source_refs'])<=sourceids
    assert not {'answer','explanation','reference_answer','rubric','solution','follow_up'}.intersection(x), x['id']
for x in ans:
    assert len(x['answer'])>=80 and x['pitfalls'] and x['follow_up'], x['id']
for x in lessons:
    assert (r/'teaching'/x['document']).is_file()
    assert set(x['question_ids'])<=set(qids)
    for lab in x['labs']: assert (r/f'teaching/labs/{lab}.py').exists(), lab
for file in r.rglob('*.py'): ast.parse(file.read_text(encoding='utf-8'))
work=rows('work_items.jsonl');known={x['id'] for x in work}
assert len(work)==6 and len(known)==6
for x in work: assert set(x['depends_on'])<=known and x['id'] not in x['depends_on']
seen=set()
while len(seen)<len(known):
    ready={x['id'] for x in work if set(x['depends_on'])<=seen}-seen
    assert ready,'Cyclic dependencies'
    seen|=ready
assert len(rows('acceptance.jsonl'))==10
probes=readj('evidence/current_probes.json')
assert len(probes)==5 and all(x['status']!='HARNESS_ERROR' for x in probes)
for name in ('request_projection','rrf_demo','sqlite_store','history','dates_preview','evidence_view'):
    assert (r/f'teaching/labs/{name}.py').exists()
report={'status':'RESOURCE_STRUCTURE_OK','questions':len(q),'answers':len(ans),'lessons':len(lessons),'labs':6,'source_anchors':len(sm),'work_items':len(work),'acceptance_categories':10,'product_fixed_by_this_pack':False,'student_mastery_updated':False}
print(json.dumps(report,ensure_ascii=False,indent=2))
