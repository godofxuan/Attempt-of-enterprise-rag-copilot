"""Read-only product event projection uses actual recorded origins."""

from tests.product.test_turn_recovery import product


def test_model_choices_tools_and_program_steps_are_not_conflated(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        with w.runs.db() as db:
            db.execute(
                "INSERT INTO workbench_runs(id,kind,target,status,input_json) VALUES('view-test','service','test-task','succeeded','{}')"
            )
        w.runs.event(
            "view-test",
            "model_decision",
            {
                "thinking": "NOT_FOR_DISPLAY",
                "content": "not an execution receipt",
                "tool_calls": [{"function": {"name": "assets_search", "arguments": {}}}],
            },
        )
        w.runs.event(
            "view-test",
            "tool_result",
            {
                "tool": "assets_search",
                "result": {"status": "ok", "data": {"assets": [{"asset_id": "test-device"}]}},
            },
        )
        w.runs.event(
            "view-test",
            "finished",
            {
                "result": {
                    "trace": {"steps": [{"tool": "search", "status": "ok", "visible_count": 2}]}
                }
            },
        )
        response = client.get("/api/product/runs/view-test/events")
        assert response.status_code == 200, response.text
        rows = response.json()
        assert (
            rows[0]["actor"] == "model"
            and rows[0]["status"] == "proposed"
            and rows[0]["observation"] == "assets_search"
        )
        assert (
            rows[1]["actor"] == "tool"
            and rows[1]["action"] == "assets_search"
            and rows[1]["status"] == "ok"
        )
        assert rows[-1]["actor"] == "program" and rows[-1]["action"] == "search"
        assert (
            "NOT_FOR_DISPLAY" not in response.text
            and "not an execution receipt" not in response.text
        )
