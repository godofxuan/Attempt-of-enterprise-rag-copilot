import json

from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.v2_test_support import user_context


def test_generation_explains_finite_typo_view_and_separate_claim_ids(snapshot_factory, document_factory, chunk_factory):
    text = '报销需要发票。'
    runner, _ = runner_fixture(snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text)
    observed = []
    def chat(model, messages, **kwargs):
        observed.append(messages)
        return json.dumps(dict(answer=text, claims=[dict(claim_id='C1', text=text, critical=True, cited_source_ids=['S1'])]), ensure_ascii=False)
    runner.response_builder.chat_fn = chat
    question = '出差报肖要带啥？'
    runner.run(question, user_context())
    content = observed[0][1]['content']
    metadata = json.loads(content.splitlines()[1])
    assert metadata['question'] == question
    assert metadata['normalized_question'] == '出差报销需要哪些材料？'
    assert 'unique claim_id' in content
    assert 'C1' in content and 'cited_source_ids' in content
    assert 'reimbursement' in content
    assert len(observed) == 1
