from __future__ import annotations

import streamlit as st

from streamlit_app.shell import inject_css


st.set_page_config(
    page_title="Enterprise Agentic RAG",
    page_icon=":material/hub:",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

page = st.navigation(
    [
        st.Page(
            "pages/1_Ask.py",
            title="Ask",
            icon=":material/forum:",
            default=True,
        ),
        st.Page(
            "pages/2_Trace.py",
            title="Trace",
            icon=":material/account_tree:",
        ),
        st.Page(
            "pages/3_Evaluation.py",
            title="Evaluation",
            icon=":material/monitoring:",
        ),
    ],
    position="sidebar",
)
page.run()
