"""Trusted host scope and source refs, not a keyword topic classifier."""
import json
from tests.product.test_turn_recovery import product
from app.agent.generation_v2 import _parse_generated_answer


def test_business_context_is_scoped_but_pure_knowledge_is_not_forced_into_a_task(tmp_path):
    with product(tmp_path) as c:
        w=c.app.state.workspace; kb=w.library.create('主题原件')['id']
        cid=w.conversations.create(kb)['id']
        with w.library.db() as db:
            for name,scope,question in [('loan','loan','借用期限？'),('repair','repair','报修提交后的状态？'),('unknown',None,'无可信主题的历史')]:
                db.execute('INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation,context_scope) VALUES(?,?,?,?,?,?,?)',
                    (name,cid,kb,question,json.dumps({'answer':'TEST_HISTORY_NOT_EVIDENCE'}),'historical',scope))
        assert [r['id'] for r in w.library.conversation_context(kb,cid,context_scope='repair')] == ['repair']
        assert {r['id'] for r in w.library.conversation_context(kb,cid)} == {'loan','repair','unknown'}


def test_thin_experimental_status_keeps_the_same_host_reference_parser():
    wire={'answer_blocks':[{'text':'本规则的最长时间是14天。','source_unit_ids':['S1U1'], 'need_refs':['N1'], 'assumptions':[]}],
          'need_status':{'N1':'supported'}}
    parsed=_parse_generated_answer(json.dumps(wire))
    assert parsed.claims[0].source_unit_id == 'S1U1'
    assert parsed.request_coverage[0].claim_ids == [parsed.claims[0].claim_id]
    empty=_parse_generated_answer(json.dumps({'answer_blocks':[], 'need_status':{'N1':'evidence_insufficient'}}))
    assert not empty.claims and empty.request_coverage[0].status=='evidence_insufficient'
