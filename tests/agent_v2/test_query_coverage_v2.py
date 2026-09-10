import json

import pytest

from app.agent.query_needs import assess_need_coverage
from app.domain.queries import SearchRequest
from app.retrieval.pipeline import HybridRetrievalPipeline
from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.v2_test_support import user_context


def test_three_supported_needs_survive_approval_publication(snapshot_factory, document_factory, chunk_factory):
    texts = ['报销由部门经理审批。', '报销需要发票。报销额度为500元。']
    runner, _ = runner_fixture(snapshot_factory, document_factory, chunk_factory, texts=texts, claim=texts[0])

    def chat(model, messages, **kwargs):
        records = next(json.loads(line) for line in messages[1]['content'].splitlines() if line.startswith('[{'))
        claims = [dict(claim_id=f'c{i}', text=r['matched_text'], critical=True,
                       cited_source_ids=[r['source_id']]) for i, r in enumerate(records)]
        return json.dumps(dict(answer='\n'.join(c['text'] for c in claims), claims=claims), ensure_ascii=False)

    runner.response_builder.chat_fn = chat
    response = runner.run('报销需要哪些材料、由谁审批、额度是多少？', user_context())
    assert response.mode == 'answered'
    assert all(t in response.answer for t in ('部门经理', '发票', '500元'))
    assert all(c.supported for c in response.citations)
    assert response.trace.get('query_need_coverage', {}).get('missing') == 0


@pytest.mark.parametrize('evidence,claims', [
    (['报销需要发票。', '超过500元的报销还需要发票原件。'], ['报销需要发票。']),
    (['报销不需要发票。', '报销需要行程单。'], ['报销需要行程单。']),
    (['报销需要航班取消证明。', '报销需要发票。'], ['报销需要发票。']),
    (['合同需要发票。'], ['合同需要发票。']),
])
def test_material_coverage_is_not_a_bag_of_names(evidence, claims):
    assert 'materials' in assess_need_coverage('报销需要哪些材料？', claims, evidence).missing


@pytest.mark.parametrize('statement', [
    '报销需要发票和行程单。', '报销无需提交材料。', '报销不需要发票。',
    '超过500元的报销需要发票原件。', '报销需要航班取消证明。',
])
def test_fully_copied_material_obligation_is_covered(statement):
    assert 'materials' not in assess_need_coverage('报销需要哪些材料？', [statement], [statement]).missing


@pytest.mark.parametrize('evidence,claims,missing', [
    (['报销额度为500元。', '境外报销额度为900元。'], ['报销额度为500元。'], True),
    (['合同额度为500元。'], ['合同额度为500元。'], True),
    (['超过500元的报销额度上限为900元。'], ['超过500元的报销额度上限为900元。'], False),
])
def test_limit_coverage_preserves_scope(evidence, claims, missing):
    assert ('limit' in assess_need_coverage('报销额度是多少？', claims, evidence).missing) == missing


def test_typo_reaches_real_bm25_without_mutating_request(snapshot_factory, chunk_factory):
    chunks = [chunk_factory(chunk_id='a', text='住房公积金缴存。'),
              chunk_factory(chunk_id='b', text='报销材料需要发票。'),
              chunk_factory(chunk_id='c', text='年假天数计算。')]
    pipeline = HybridRetrievalPipeline(snapshot_factory(chunks))
    request = SearchRequest(query='报消', purpose='typo probe', user=user_context(), mode='bm25', top_k=1)
    result = pipeline.search(request)
    assert result.hits[0].chunk_id == 'b'
    assert result.query == request.query == '报消'


def test_dense_receives_normalized_query_once(snapshot_factory, chunk_factory):
    seen = []
    def embed(text):
        seen.append(text)
        return [1., 1.]
    pipeline = HybridRetrievalPipeline(snapshot_factory([chunk_factory()]), embed_text=embed)
    request = SearchRequest(query='出差报消要带啥，不超过500元？', purpose='probe', user=user_context(), mode='dense')
    pipeline.search(request)
    assert seen == ['出差报销需要哪些材料，不超过500元？']
    assert request.query == '出差报消要带啥，不超过500元？'


@pytest.mark.parametrize('question', [
    '《报消制度》在2026-09-01的规定？', '"报消"这个词什么意思？',
    '合同审皮是什么意思？', '不要报销超过500元的发票。',
])
def test_literal_names_and_other_domains_unchanged(question, snapshot_factory, chunk_factory):
    seen = []
    pipeline = HybridRetrievalPipeline(snapshot_factory([chunk_factory()]), embed_text=lambda text: seen.append(text) or [1., 1.])
    pipeline.search(SearchRequest(query=question, purpose='probe', user=user_context(), mode='dense'))
    assert seen == [question]
