"""Real ModelService ledger/transport boundary, external HTTP explicitly doubled."""
import asyncio
import httpx
import pytest
from tests.product.test_turn_recovery import product
from app.runtime.request_context import bind_request_context, reset_request_context


def test_all_nested_attempts_share_run_limit_and_old_rows_are_not_rewritten(tmp_path):
    with product(tmp_path) as c:
        w=c.app.state.workspace
        calls=[]
        async def scenario():
            await w.models.client.aclose()
            def external(request):
                calls.append(request)
                return httpx.Response(200,json={'message':{'role':'assistant','content':'program test'},'done_reason':'stop'})
            w.models.client=httpx.AsyncClient(transport=httpx.MockTransport(external),trust_env=False)
            token=bind_request_context('all-nested-one-run',deadline_ms=5000)
            try:
                for _ in range(8): await w.models.chat([{'role':'user','content':'Explicit test transport'}])
                with pytest.raises(ValueError,match='RUN_CHAT_LIMIT'):
                    await w.models.chat([{'role':'user','content':'Ninth actual send must not occur'}])
            finally: reset_request_context(token)
        c.portal.call(scenario)
        with w.models.db() as db:
            rows=db.execute('SELECT run_id,status FROM model_calls').fetchall()
        assert rows==[('all-nested-one-run','OK')]*8 and len(calls)==8
