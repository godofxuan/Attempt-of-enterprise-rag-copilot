"""Frozen synthetic development checks, not independent validation."""
import json
from pathlib import Path
import pytest
from tests.api_v2.test_runtime_closure_flow import service
from app.agent.evidence_relevance import has_query_anchor_support
from tests.v2_test_support import admitted_search_hit
CASES = [
 ('g2_approval_only','这笔报销由谁审批？','这笔报销需要审批。','incomplete',[]),
 ('g2_process_only','这笔报销由谁审批？','这笔报销按流程审批。','incomplete',[]),
 ('g3_roles','这笔报销由谁审批？','这笔报销由员工提交，财务核验，部门负责人审批。','complete',['部门负责人']),
 ('g3_paraphrase','这笔报销由谁审批？','这笔报销审批由部门负责人完成。','complete',['部门负责人']),
 ('g4_no_approval','这笔报销由谁审批？','这笔报销无需审批。','complete',['无需审批']),
 ('g4_unknown','这笔报销由谁审批？','这笔报销材料未说明审批人。','incomplete',[]),
 ('g5_threshold','报销金额超过 100 元由谁审批？','报销金额不超过 100 元由直属经理审批；超过 100 元由部门负责人审批。','complete',['超过 100 元','部门负责人']),
 ('g5_units','员工报销上限是多少元？','员工报销上限为 20 元；承包商报销上限为 20 美元。','complete',['员工','20 元']),
 ('g6_two_aspects','出差申请需要提前多少天提交，以及由谁审批？','出差申请必须提前 7 天提交。','partial',['7 天']),
 ('g6_no_relation','出差申请由谁审批？','出差申请必须提前 7 天提交。','incomplete',[]),
]
def record(case,question,evidence,data,seen):
 p=Path(__file__).resolve().parents[1]/'audit/observations'; p.mkdir(parents=True,exist_ok=True)
 (p/(case+'.json')).write_text(json.dumps(dict(case=case,question=question,evidence=evidence,response=data,model_boundary_spies=seen),ensure_ascii=True,indent=2),encoding='utf8')
@pytest.mark.parametrize('question',['快递报销制度每单上限是多少？','《快递报销制度》每单上限是多少？','差旅费用一般如何报销'])
def test_g1_names_and_topic(question):
 if '快递' in question:
  good='快递报销制度。每单报销上限为 40 元。'; bad='运费标准表。每单运费上限为 20 元。'
  assert has_query_anchor_support(question,admitted_search_hit(matched_text=good,context_text=good))
  assert not has_query_anchor_support(question,admitted_search_hit(matched_text=bad,context_text=bad))
 else:
  text='差旅费用报销需要提交票据。'
  assert has_query_anchor_support(question,admitted_search_hit(matched_text=text,context_text=text))
@pytest.mark.parametrize('case,question,text,expected,required',CASES,ids=[c[0] for c in CASES])
def test_g2_to_g6_http(service,case,question,text,expected,required):
 start,seen,_=service
 with start([dict(id='policy',text=text)]) as client:
  response=client.post('/agent/v2/chat',json={'question':question})
 data=response.json(); record(case,question,text,data,seen)
 assert response.status_code==200
 if expected=='incomplete': assert data['mode']!='answered','Missing approver is not complete'
 elif expected=='partial':
  assert data['mode']=='partial'
  assert any(x in data['answer'] for x in ['未','不足','无法','缺','not','missing'])
 else: assert data['mode']=='answered'
 assert all(x in data['answer'] for x in required)
 if expected=='complete':
  assert seen['llm'] and text in json.dumps(seen['llm'],ensure_ascii=False)
  assert data['citations'] and all(c['supported'] for c in data['citations'])
def test_cross_policy_conflict(service):
 start,seen,_=service
 rows=[dict(id='policy_a',policy='refund_a',text='退款争议处理期限为 7 天。'),dict(id='policy_b',policy='refund_b',text='退款争议处理期限为 30 天。')]
 question='退款争议处理期限是多少天？'
 with start(rows,'safe_dense_raw20_bge') as client:
  data=client.post('/agent/v2/chat',json={'question':question}).json()
 record('cross_policy_conflict',question,rows,data,seen)
 assert all(r['text'] in seen['scorer'] for r in rows)
 assert all(r['text'] in json.dumps(seen['llm'],ensure_ascii=False) for r in rows)
 assert data['mode']=='partial','CONFLICT_SCOPE_GAP: incompatible legal policies silently choose a winner'
 assert '7 天' in data['answer'] and '30 天' in data['answer']
