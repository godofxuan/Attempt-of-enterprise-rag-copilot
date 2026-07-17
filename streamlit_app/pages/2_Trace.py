from __future__ import annotations

from collections.abc import Mapping

import streamlit as st
from pydantic import ValidationError

from app.observability.tracing import RequestTrace
from streamlit_app.api_client import UiApiError
from streamlit_app.shell import ensure_session_state, get_client, render_sidebar
from streamlit_app.view_models import (
    action_rows,
    budget_rows,
    evidence_summary,
    format_milliseconds,
    mode_label,
    resolve_request_id,
    span_rows,
)


ensure_session_state()
render_sidebar()

st.title("Trace")
st.caption("Agent decisions and service telemetry")

lookup_columns = st.columns([4, 1])
lookup_id = lookup_columns[0].text_input(
    "Request ID",
    placeholder=st.session_state.last_request_id or "Enter request ID",
    key="trace_lookup_id",
)
fetch_trace = lookup_columns[1].button(
    "Fetch",
    icon=":material/search:",
    key="fetch_trace",
    width="stretch",
)

if fetch_trace:
    effective_request_id = resolve_request_id(
        lookup_id,
        st.session_state.last_request_id,
    )
    if not effective_request_id:
        st.warning("A request ID is required.")
    else:
        st.session_state.trace_view_request_id = effective_request_id
        st.session_state.last_http_trace = None
        try:
            trace = get_client().trace(effective_request_id)
            st.session_state.last_http_trace = trace.model_dump(mode="json")
        except UiApiError as exc:
            st.error(str(exc))

view_request_id = resolve_request_id(
    st.session_state.trace_view_request_id,
    st.session_state.last_request_id,
)
payload = st.session_state.last_answer
agent_trace = payload.get("trace") if isinstance(payload, Mapping) else None
agent_request_id = (
    str(agent_trace.get("request_id", ""))
    if isinstance(agent_trace, Mapping)
    else ""
)
if not isinstance(agent_trace, Mapping) or agent_request_id != view_request_id:
    st.info("No Agent decision trace is available for this request.")
else:
    evidence = evidence_summary(agent_trace)
    summary_columns = st.columns(6)
    summary_columns[0].metric(
        "Intent",
        str(agent_trace.get("intent", "unknown")).replace("_", " ").title(),
    )
    summary_columns[1].metric(
        "Analysis",
        str(agent_trace.get("analysis_source", "unknown"))
        .replace("_", " ")
        .title(),
    )
    summary_columns[2].metric(
        "Mode",
        mode_label(str(payload.get("mode", "unknown"))),
    )
    summary_columns[3].metric(
        "Stop reason",
        str(agent_trace.get("stop_reason", "-")).replace("_", " ").title(),
    )
    summary_columns[4].metric(
        "Evidence",
        f"{evidence['supported']}/{evidence['required']}",
    )
    summary_columns[5].metric(
        "Next action",
        str(evidence["recommended_action"]).replace("_", " ").title(),
    )
    st.caption(f"Agent request ID: {agent_request_id}")
    st.progress(
        min(1.0, max(0.0, float(evidence["coverage"]))),
        text=f"Evidence coverage {float(evidence['coverage']):.0%}",
    )

    st.subheader("Agent actions")
    actions = action_rows(agent_trace)
    if actions:
        st.dataframe(actions, hide_index=True, width="stretch")
    else:
        st.info("No action records are available.")

    st.subheader("Budget usage")
    budget = budget_rows(agent_trace)
    if budget:
        st.dataframe(budget, hide_index=True, width="stretch")

st.divider()
st.subheader("Service trace")
http_payload = st.session_state.last_http_trace
if not isinstance(http_payload, Mapping):
    st.info("No service trace is loaded.")
else:
    try:
        http_trace = RequestTrace.model_validate(http_payload)
    except ValidationError:
        st.error("The saved service trace is invalid.")
    else:
        if http_trace.request_id != view_request_id:
            st.error("The saved service trace does not match this request.")
        else:
            http_columns = st.columns(4)
            http_columns[0].metric("HTTP", str(http_trace.status_code))
            http_columns[1].metric(
                "Duration",
                format_milliseconds(http_trace.duration_ms),
            )
            http_columns[2].metric("Model calls", str(http_trace.model_calls))
            http_columns[3].metric("Retries", str(http_trace.model_retries))
            st.caption(f"Service request ID: {http_trace.request_id}")
            spans = span_rows(http_trace)
            if spans:
                st.dataframe(spans, hide_index=True, width="stretch")
