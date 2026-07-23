from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[2]
ASK_PAGE = ROOT / "streamlit_app" / "pages" / "1_Ask.py"
TRACE_PAGE = ROOT / "streamlit_app" / "pages" / "2_Trace.py"
EVALUATION_PAGE = ROOT / "streamlit_app" / "pages" / "3_Evaluation.py"


def _run(path: Path) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=10).run()


def test_ask_page_renders_offline_and_initializes_session_contract() -> None:
    app = _run(ASK_PAGE)

    assert not app.exception
    assert app.title[0].value == "Ask"
    for key in [
        "selected_demo",
        "last_answer",
        "last_request_id",
        "last_feedback_receipt",
        "last_http_trace",
        "last_latency_ms",
    ]:
        assert key in app.session_state
    assert any(button.label == "Run Agent" for button in app.button)


def test_custom_mode_uses_a_fixed_persona_and_has_no_editable_identity() -> None:
    app = _run(ASK_PAGE)
    app.button_group[0].set_value("Custom").run()

    assert not app.exception
    labels = [item.label for item in app.text_input]
    assert "User ID" not in labels
    assert "Tenant" not in labels
    assert "Groups" not in labels
    assert "Roles" not in labels
    assert any(item.label == "Persona" for item in app.selectbox)


def test_streamlit_sources_never_store_or_read_private_keys_or_tokens_in_state() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "streamlit_app").rglob("*.py")
    )

    assert "private_key" not in sources
    assert "last_token" not in sources
    assert "session_state.token" not in sources
    assert "user_context" not in (ASK_PAGE.read_text(encoding="utf-8"))
    shell = (ROOT / "streamlit_app" / "shell.py").read_text(encoding="utf-8")
    assert '"persona_tokens.json"' in shell
    assert '"operator_token.txt"' in shell
    assert "RAG_BEARER_TOKEN" not in shell


def test_ask_input_change_clears_previous_result_state() -> None:
    app = _run(ASK_PAGE)
    app.session_state.last_answer = {"mode": "answered"}
    app.session_state.last_request_id = "stale-request"
    app.session_state.last_feedback_receipt = "a" * 64
    app.session_state.last_http_trace = {"request_id": "stale-request"}
    app.session_state.last_latency_ms = 100.0

    app.button_group[0].set_value("Custom").run()

    assert not app.exception
    assert app.session_state.last_answer is None
    assert app.session_state.last_request_id == ""
    assert app.session_state.last_feedback_receipt == ""
    assert app.session_state.last_http_trace is None
    assert app.session_state.last_latency_ms is None


def test_trace_page_has_safe_empty_state_without_sensitive_surfaces() -> None:
    app = _run(TRACE_PAGE)

    assert not app.exception
    assert app.title[0].value == "Trace"
    visible_text = "\n".join(
        item.value for item in [*app.info, *app.caption, *app.markdown]
    )
    assert "No Agent decision trace is available for this request" in visible_text
    source = TRACE_PAGE.read_text(encoding="utf-8")
    for forbidden in ["last_question", "source_rows", "preview", "tenant_id"]:
        assert forbidden not in source


def test_trace_page_never_combines_different_agent_and_service_requests() -> None:
    app = AppTest.from_file(str(TRACE_PAGE), default_timeout=10)
    app.session_state.last_answer = {
        "mode": "answered",
        "trace": {
            "request_id": "req-agent",
            "intent": "fact",
            "analysis_source": "rules",
            "stop_reason": "completed",
            "steps": [{"sequence": 1, "tool": "search", "status": "ok"}],
        },
    }
    app.session_state.last_request_id = "req-agent"
    app.session_state.trace_view_request_id = "req-service"
    app.session_state.last_http_trace = {
        "request_id": "req-service",
        "method": "POST",
        "route": "/agent/v2/chat",
        "status_code": 200,
        "duration_ms": 100.0,
        "outcome": "answered",
        "model_calls": 1,
        "model_retries": 0,
        "model_errors": 0,
        "spans": [],
    }

    app.run()

    assert not app.exception
    assert any(
        "No Agent decision trace is available for this request" in item.value
        for item in app.info
    )
    assert "Agent actions" not in [item.value for item in app.subheader]
    assert "200" in [metric.value for metric in app.metric]


def test_trace_matching_request_shows_complete_request_overview() -> None:
    app = AppTest.from_file(str(TRACE_PAGE), default_timeout=10)
    app.session_state.last_answer = {
        "mode": "answered",
        "trace": {
            "request_id": "req-agent",
            "intent": "fact",
            "analysis_source": "rules+model",
            "stop_reason": "completed",
            "steps": [],
            "evidence": {
                "required": 1,
                "supported": 1,
                "missing": 0,
                "conflicting": 0,
                "coverage": 1.0,
                "recommended_action": "answer",
            },
        },
    }
    app.session_state.last_request_id = "req-agent"
    app.session_state.trace_view_request_id = "req-agent"

    app.run()

    values = [metric.value for metric in app.metric]
    captions = [item.value for item in app.caption]
    assert not app.exception
    assert "Fact" in values
    assert "Rules+Model" in values
    assert "Answered" in values
    assert any("Agent request ID: req-agent" in item for item in captions)


def test_evaluation_page_uses_strict_public_snapshot() -> None:
    app = _run(EVALUATION_PAGE)

    assert not app.exception
    assert app.title[0].value == "Evaluation"
    values = [metric.value for metric in app.metric]
    assert "28/28" in values
    assert "23/24" in values
    assert "31/31" in values
    visible = "\n".join(
        str(item.value)
        for item in [*app.markdown, *app.caption, *app.info, *app.warning]
    )
    # Dataframe.value performs a PyArrow-to-Pandas test-only round trip.
    assert len(app.dataframe) == 6
    assert "NOT RUN" in visible
    assert "20260716T135632Z_7aec4b9_test_suite" in visible
    assert "20260716T165304Z_7aec4b9_demo_load_r2" in visible

    source = EVALUATION_PAGE.read_text(encoding="utf-8")
    assert 'st.info("Optional reranker: NOT RUN")' not in source
    assert 'st.warning("Indirect document injection: NOT RUN")' not in source


def test_navigation_and_css_source_contract() -> None:
    entrypoint = (ROOT / "streamlit_app" / "ui.py").read_text(encoding="utf-8")
    shell = (ROOT / "streamlit_app" / "shell.py").read_text(encoding="utf-8")

    assert "st.navigation" in entrypoint
    assert entrypoint.count("st.Page(") == 3
    assert "default=True" in entrypoint
    assert entrypoint.count(":material/") >= 4
    assert "gradient" not in shell.casefold()
    assert "letter-spacing: 0" in shell
    assert "border-radius: 8px" in shell
    assert "border-radius: 999" not in shell

    theme = (ROOT / ".streamlit" / "config.toml").read_text(
        encoding="utf-8"
    )
    assert 'primaryColor = "#147D64"' in theme
    assert 'backgroundColor = "#F5F7F6"' in theme
    assert 'secondaryBackgroundColor = "#EDF2EF"' in theme
    assert 'textColor = "#17211E"' in theme
    assert 'address = "127.0.0.1"' in theme


def test_navigation_entrypoint_renders_default_page_offline() -> None:
    app = _run(ROOT / "streamlit_app" / "ui.py")

    assert not app.exception
    assert app.title[0].value == "Ask"
