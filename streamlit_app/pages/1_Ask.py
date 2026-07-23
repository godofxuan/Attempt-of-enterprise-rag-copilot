from __future__ import annotations

import time

import streamlit as st
from pydantic import ValidationError

from app.domain.evidence import AnswerResponse
from streamlit_app.api_client import UiApiError
from streamlit_app.demo_cases import DemoCase, load_demo_cases
from streamlit_app.shell import (
    PROJECT_ROOT,
    clear_answer_state,
    ensure_session_state,
    get_client,
    render_sidebar,
)
from streamlit_app.view_models import (
    citation_rows,
    format_milliseconds,
    mode_label,
    source_rows,
)


def _clear_result_state() -> None:
    clear_answer_state(st.session_state)


ensure_session_state()
render_sidebar()

st.title("Ask")
st.caption("Enterprise Agentic RAG workbench")

try:
    demo_cases = load_demo_cases(PROJECT_ROOT)
except ValueError:
    st.error("Canonical demo cases are unavailable.")
    demo_cases = ()

input_mode = st.segmented_control(
    "Input mode",
    ["Demo", "Custom"],
    default="Demo",
    key="ask_input_mode",
    on_change=_clear_result_state,
    width="stretch",
)

selected_case: DemoCase | None = None
expected_mode: str | None = None
persona_id: str | None = None
if input_mode == "Demo" and demo_cases:
    case_ids = [case.provenance_id for case in demo_cases]
    current = st.session_state.selected_demo
    index = case_ids.index(current) if current in case_ids else 0
    selected_id = st.selectbox(
        "Scenario",
        case_ids,
        index=index,
        format_func=lambda case_id: next(
            case.label for case in demo_cases if case.provenance_id == case_id
        ),
        key="ask_scenario",
        on_change=_clear_result_state,
    )
    st.session_state.selected_demo = selected_id
    selected_case = next(
        case for case in demo_cases if case.provenance_id == selected_id
    )
    question = st.text_area(
        "Question",
        value=selected_case.question,
        height=118,
        disabled=True,
        key=f"demo_{selected_case.provenance_id}",
    )
    persona_id = selected_case.user.user_id
    expected_mode = selected_case.expected_mode
else:
    question = st.text_area(
        "Question",
        key="custom_question",
        on_change=_clear_result_state,
        height=118,
        placeholder="Ask about a policy, process, or cross-document requirement.",
    )
    persona_ids = list(
        dict.fromkeys(case.user.user_id for case in demo_cases)
    )
    persona_id = st.selectbox(
        "Persona",
        persona_ids,
        format_func=lambda value: value.replace("-", " ").title(),
        on_change=_clear_result_state,
        disabled=not persona_ids,
    ) if persona_ids else None

top_k = st.slider(
    "Retrieval depth",
    min_value=1,
    max_value=10,
    value=5,
    key="ask_top_k",
    on_change=_clear_result_state,
)

if selected_case is not None:
    context_columns = st.columns(4)
    context_columns[0].metric("Tenant", selected_case.user.tenant_id)
    context_columns[1].metric("Region", selected_case.user.region.upper())
    context_columns[2].metric(
        "Access groups",
        str(len(selected_case.user.groups)),
    )
    context_columns[3].metric(
        "Expected mode",
        mode_label(selected_case.expected_mode),
    )
    st.caption(
        f"Identity: {selected_case.user.user_id} | "
        f"Groups: {', '.join(selected_case.user.groups)} | "
        f"Source: {selected_case.provenance}/{selected_case.provenance_id}"
    )

run_agent = st.button(
    "Run Agent",
    type="primary",
    icon=":material/play_arrow:",
    key="run_agent",
)

if run_agent:
    clear_answer_state(st.session_state)
    if not question.strip():
        st.warning("A question is required.")
    else:
        if persona_id is None:
            st.error("A demo persona is required.")
        else:
            started = time.perf_counter()
            try:
                with st.spinner("Running Agent"):
                    result = get_client().ask(
                        question,
                        persona_id=persona_id,
                        top_k=int(top_k),
                    )
                st.session_state.last_latency_ms = (
                    time.perf_counter() - started
                ) * 1000
                st.session_state.last_answer = result.response.model_dump(
                    mode="json"
                )
                st.session_state.last_question = question
                st.session_state.last_request_id = result.request_id
                st.session_state.last_feedback_receipt = (
                    result.feedback_receipt
                )
                st.session_state.last_expected_mode = expected_mode
                st.session_state.last_persona_id = persona_id
                st.session_state.trace_lookup_id = result.request_id
                st.session_state.trace_view_request_id = result.request_id
                try:
                    http_trace = get_client().trace(result.request_id)
                    st.session_state.last_http_trace = http_trace.model_dump(
                        mode="json"
                    )
                except UiApiError:
                    st.session_state.last_http_trace = None
            except UiApiError as exc:
                st.error(str(exc))
                st.caption(f"Request: {exc.request_id}")

payload = st.session_state.last_answer
if isinstance(payload, dict):
    try:
        response = AnswerResponse.model_validate(payload)
    except ValidationError:
        st.error("The saved response is invalid.")
    else:
        st.divider()
        response_columns = st.columns(4)
        response_columns[0].metric("Mode", mode_label(response.mode))
        response_columns[1].metric(
            "Stop reason",
            str(response.stop_reason or "-").replace("_", " ").title(),
        )
        request_id = st.session_state.last_request_id
        request_value = (
            f"{request_id[:10]}..." if len(request_id) > 13 else request_id
        )
        response_columns[2].metric("Request", request_value or "-")
        response_columns[3].metric(
            "Latency",
            format_milliseconds(st.session_state.last_latency_ms),
        )
        if request_id:
            st.caption(f"Request ID: {request_id}")

        st.subheader("Response")
        st.write(response.answer)
        for warning in response.warnings:
            st.warning(warning)

        citations = citation_rows(response)
        if citations:
            st.subheader("Claim verification")
            st.dataframe(citations, hide_index=True, width="stretch")

        sources = source_rows(response)
        if sources:
            st.subheader("Authorized sources")
            st.dataframe(sources, hide_index=True, width="stretch")

        st.subheader("Feedback")
        feedback_available = bool(
            st.session_state.last_feedback_receipt
        )
        feedback_columns = st.columns(2)
        helpful = feedback_columns[0].button(
            "Helpful",
            icon=":material/thumb_up:",
            key="feedback_helpful",
            width="stretch",
            disabled=not feedback_available,
        )
        not_helpful = feedback_columns[1].button(
            "Not helpful",
            icon=":material/thumb_down:",
            key="feedback_not_helpful",
            width="stretch",
            disabled=not feedback_available,
        )
        if helpful or not_helpful:
            try:
                get_client().feedback(
                    persona_id=st.session_state.last_persona_id,
                    target_request_id=st.session_state.last_request_id,
                    question=st.session_state.last_question,
                    answer=response.answer,
                    helpful=helpful,
                    receipt=st.session_state.last_feedback_receipt,
                )
                st.session_state.last_feedback_receipt = ""
                st.success("Feedback recorded")
            except UiApiError as exc:
                st.error(str(exc))
