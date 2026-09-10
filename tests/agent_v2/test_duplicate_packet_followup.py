from tests.agent_v2.test_query_coverage_v1 import runner_fixture
from tests.v2_test_support import user_context


def test_same_document_search_open_text_is_not_delivered_twice(
    snapshot_factory, document_factory, chunk_factory
):
    text = "值班要求：警报应在5分钟内响应。"
    runner, seen = runner_fixture(
        snapshot_factory, document_factory, chunk_factory, texts=[text], claim=text
    )
    response = runner.run("完整列出值班要求。", user_context())
    assert response.mode == "answered"
    assert response.trace["budget"]["open_calls"] == 1
    assert len(seen[0]) == 1
    assert response.citations[0].supported
