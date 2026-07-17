from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit as st

from streamlit_app.api_client import EnterpriseRagClient, UiApiError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
_SESSION_DEFAULTS: dict[str, Any] = {
    "selected_demo": "fact_hr_remote_2026_notice",
    "last_answer": None,
    "last_request_id": "",
    "last_http_trace": None,
    "last_latency_ms": None,
    "last_question": "",
    "last_expected_mode": None,
    "trace_lookup_id": "",
    "trace_view_request_id": "",
    "readiness_status": None,
}


def ensure_session_state() -> None:
    for key, value in _SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_answer_state(state: Any) -> None:
    for key, value in {
        "last_answer": None,
        "last_request_id": "",
        "last_http_trace": None,
        "last_latency_ms": None,
        "last_question": "",
        "last_expected_mode": None,
        "trace_lookup_id": "",
        "trace_view_request_id": "",
    }.items():
        state[key] = value


@st.cache_resource(show_spinner=False)
def _cached_client(base_url: str) -> EnterpriseRagClient:
    return EnterpriseRagClient(base_url, timeout_seconds=30.0)


def get_client() -> EnterpriseRagClient:
    return _cached_client(
        os.environ.get("RAG_API_BASE_URL", DEFAULT_API_BASE_URL).strip()
        or DEFAULT_API_BASE_URL
    )


def render_sidebar() -> None:
    ensure_session_state()
    with st.sidebar:
        st.markdown(
            "<div class='rag-brand'>Enterprise RAG</div>"
            "<div class='rag-brand-subtitle'>Agentic knowledge operations</div>",
            unsafe_allow_html=True,
        )
        st.divider()
        if st.button(
            "Check service",
            icon=":material/monitor_heart:",
            key="check_service",
            width="stretch",
        ):
            try:
                snapshot = get_client().readiness()
                st.session_state.readiness_status = snapshot.status
            except UiApiError as exc:
                st.session_state.readiness_status = "unavailable"
                st.error(str(exc))
        status = st.session_state.readiness_status
        if status == "ready":
            st.success("Service ready")
        elif status == "not_ready":
            st.warning("Dependencies not ready")
        elif status == "unavailable":
            st.error("Service unavailable")
        else:
            st.caption("Service status not checked")
        if st.session_state.last_request_id:
            st.divider()
            st.caption("Current request")
            st.code(st.session_state.last_request_id, language=None)


def inject_css() -> None:
    st.markdown(
        """
<style>
:root {
  --rag-ink: #17211e;
  --rag-muted: #5f6c67;
  --rag-surface: #ffffff;
  --rag-canvas: #f5f7f6;
  --rag-border: #d5ddda;
  --rag-green: #147d64;
  --rag-amber: #aa6417;
  --rag-red: #b7443e;
}

html, body, [class*="st-"] {
  letter-spacing: 0;
}

[data-testid="stAppViewContainer"] {
  background: var(--rag-canvas);
  color: var(--rag-ink);
}

[data-testid="stMainBlockContainer"] {
  max-width: 1180px;
  padding-top: 1.6rem;
  padding-bottom: 3rem;
}

[data-testid="stSidebar"] {
  background: #edf2ef;
  border-right: 1px solid var(--rag-border);
}

.rag-brand {
  color: var(--rag-ink);
  font-size: 1.3rem;
  font-weight: 700;
  line-height: 1.3;
}

.rag-brand-subtitle {
  color: var(--rag-muted);
  font-size: 0.82rem;
  margin-top: 0.2rem;
}

[data-testid="stMetric"] {
  min-height: 94px;
  background: var(--rag-surface);
  border: 1px solid var(--rag-border);
  border-radius: 8px;
  padding: 0.85rem 1rem;
}

[data-testid="stMetricValue"] {
  color: var(--rag-ink);
  font-size: 1.35rem;
  overflow-wrap: anywhere;
}

[data-testid="stDataFrame"],
[data-testid="stTable"] {
  border: 1px solid var(--rag-border);
  border-radius: 8px;
  overflow: hidden;
}

button,
[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
textarea {
  border-radius: 8px !important;
}

button {
  min-height: 2.55rem;
}

h1, h2, h3, p, code, [data-testid="stMarkdownContainer"] {
  overflow-wrap: anywhere;
}

[data-testid="stAlert"] {
  border-radius: 8px;
}

@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] {
    padding: 1rem 0.85rem 2rem;
  }

  [data-testid="stMetric"] {
    min-height: 82px;
  }

  [data-testid="stHorizontalBlock"] {
    gap: 0.65rem;
  }
}
</style>
""",
        unsafe_allow_html=True,
    )


__all__ = [
    "PROJECT_ROOT",
    "clear_answer_state",
    "ensure_session_state",
    "get_client",
    "inject_css",
    "render_sidebar",
]
