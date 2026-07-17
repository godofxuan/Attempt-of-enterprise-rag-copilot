from __future__ import annotations

import streamlit as st
from pydantic import ValidationError

from app.evaluation.public_snapshot import PublicDemoSnapshot
from streamlit_app.shell import PROJECT_ROOT, ensure_session_state, render_sidebar
from streamlit_app.view_models import (
    ablation_rows,
    evidence_rows,
    format_milliseconds,
    load_rows,
    quality_layer_rows,
    quality_metric_rows,
    security_rows,
)


ensure_session_state()
render_sidebar()

st.title("Evaluation")
st.caption("Frozen quality evidence and runtime measurements")

snapshot_path = PROJECT_ROOT / "data" / "v2" / "public" / "demo_snapshot.json"
try:
    snapshot = PublicDemoSnapshot.model_validate_json(
        snapshot_path.read_text(encoding="utf-8")
    )
except (OSError, UnicodeDecodeError, ValidationError):
    st.error("The public evaluation snapshot is unavailable.")
    snapshot = None

if snapshot is not None:
    evidence_by_label = {item.label: item for item in snapshot.evidence}
    deterministic_ref = evidence_by_label["Deterministic quality"]
    live_ref = evidence_by_label["Live quality"]
    ablation_ref = evidence_by_label["Ablation study"]
    load_ref = evidence_by_label["Load profile"]
    headline = st.columns(4)
    deterministic = snapshot.quality.deterministic
    live = snapshot.quality.live
    headline[0].metric(
        "Frozen test",
        f"{deterministic.passed}/{deterministic.cases}",
    )
    headline[1].metric("Live dev", f"{live.passed}/{live.cases}")
    headline[2].metric(
        "Load requests",
        f"{snapshot.load.successful}/{snapshot.load.total_requests}",
    )
    headline[3].metric("Snapshot", snapshot.snapshot_id.removeprefix("public-demo-"))
    st.caption(
        f"Frozen: {deterministic.mode}/{deterministic.split} | "
        f"n={deterministic.cases} | run {deterministic_ref.run_id}  \n"
        f"Live: {live.mode}/{live.split} | n={live.cases} | "
        f"run {live_ref.run_id}"
    )

    quality_tab, ablation_tab, runtime_tab, security_tab = st.tabs(
        ["Quality", "Ablation", "Runtime", "Security"]
    )

    with quality_tab:
        st.caption(
            f"Compared runs: {deterministic_ref.run_id} "
            f"({deterministic.mode}/{deterministic.split}, n={deterministic.cases}) "
            f"and {live_ref.run_id} "
            f"({live.mode}/{live.split}, n={live.cases})"
        )
        layers = quality_layer_rows(snapshot)
        st.subheader("Layer pass rates")
        st.bar_chart(
            layers,
            x="layer",
            y=["deterministic", "live"],
            color=["#147d64", "#aa6417"],
            horizontal=True,
            stack=False,
            height=280,
        )
        st.dataframe(layers, hide_index=True, width="stretch")
        st.subheader("Selected metrics")
        st.dataframe(
            quality_metric_rows(snapshot),
            hide_index=True,
            width="stretch",
        )

    with ablation_tab:
        st.caption(
            f"Mode deterministic | split test | variants {len(snapshot.ablation)} "
            f"| run {ablation_ref.run_id}"
        )
        st.subheader("Retrieval and workflow variants")
        st.dataframe(
            ablation_rows(snapshot),
            hide_index=True,
            width="stretch",
        )
        reranker = next(
            row
            for row in snapshot.ablation
            if row.variant == "hybrid_optional_reranker"
        )
        reranker_status = reranker.status.replace("_", " ").upper()
        reranker_reason = f" ({reranker.reason})" if reranker.reason else ""
        st.info(f"Optional reranker: {reranker_status}{reranker_reason}")

    with runtime_tab:
        st.caption(
            f"Mode live | sample size {snapshot.load.total_requests} | "
            f"run {load_ref.run_id}"
        )
        runtime_columns = st.columns(4)
        runtime_columns[0].metric(
            "Cold p95",
            format_milliseconds(snapshot.load.cold_p95_ms),
        )
        runtime_columns[1].metric(
            "Model calls",
            str(snapshot.load.model_calls_delta),
        )
        runtime_columns[2].metric(
            "RSS delta",
            f"{snapshot.load.rss_delta_bytes / 1024 / 1024:.1f} MiB",
        )
        runtime_columns[3].metric(
            "Index",
            f"{snapshot.load.index.chunk_count} chunks",
        )
        st.subheader("Warm concurrency")
        st.dataframe(load_rows(snapshot), hide_index=True, width="stretch")
        st.caption(
            f"{snapshot.load.index.embedding_model} | "
            f"{snapshot.load.index.embedding_dimension} dimensions"
        )

    with security_tab:
        st.caption(
            f"Mode {deterministic.mode} | split {deterministic.split} | "
            f"sample size {deterministic.cases} | run {deterministic_ref.run_id}"
        )
        st.subheader("Security checks")
        st.dataframe(
            security_rows(snapshot),
            hide_index=True,
            width="stretch",
        )
        indirect = snapshot.security.indirect_document_injection
        indirect_status = indirect.status.replace("_", " ").upper()
        indirect_message = (
            f"Indirect document injection: {indirect_status} - {indirect.note}"
        )
        if indirect.status == "passed":
            st.success(indirect_message)
        elif indirect.status == "failed":
            st.error(indirect_message)
        else:
            st.warning(indirect_message)

    st.divider()
    st.subheader("Evidence provenance")
    st.dataframe(evidence_rows(snapshot), hide_index=True, width="stretch")
    st.caption(
        f"Evidence cutoff: {snapshot.evidence_cutoff_utc.isoformat()} | "
        f"Schema: {snapshot.schema_version}"
    )
    with st.expander("Known limitations"):
        for limitation in snapshot.limitations:
            st.markdown(f"- {limitation}")
