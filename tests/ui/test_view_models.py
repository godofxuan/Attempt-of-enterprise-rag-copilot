from __future__ import annotations

from pathlib import Path

from app.domain.evidence import AnswerResponse
from app.evaluation.public_snapshot import PublicDemoSnapshot
from app.observability.tracing import RequestTrace
from streamlit_app.view_models import (
    ablation_rows,
    action_rows,
    budget_rows,
    citation_rows,
    evidence_summary,
    format_milliseconds,
    load_rows,
    mode_label,
    quality_layer_rows,
    quality_metric_rows,
    resolve_request_id,
    security_rows,
    source_rows,
    span_rows,
)


ROOT = Path(__file__).resolve().parents[2]


def _response() -> AnswerResponse:
    return AnswerResponse.model_validate(
        {
            "mode": "answered",
            "answer": "Two working days notice is required.",
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": "Two working days notice is required.",
                    "cited_chunk_ids": ["chunk-1"],
                }
            ],
            "citations": [
                {
                    "claim_id": "claim-1",
                    "cited_chunk_ids": ["chunk-1"],
                    "citation_present": True,
                    "references_visible_evidence": True,
                    "lexical_support": 0.875,
                    "supported": True,
                    "unsupported_reason": None,
                }
            ],
            "sources": [
                {
                    "doc_id": "policy-1",
                    "source_path": "policies/remote.md",
                    "section_path": ["Remote work", "Notice"],
                    "chunk_id": "chunk-1",
                    "preview": "Two working days notice is required.",
                }
            ],
            "stop_reason": "completed",
            "trace": {
                "steps": [
                    {
                        "sequence": 1,
                        "tool": "search",
                        "status": "ok",
                        "latency_ms": 12.345,
                        "visible_count": 2,
                        "context_chars_added": 420,
                        "error_code": None,
                    }
                ],
                "evidence": {
                    "required": 1,
                    "supported": 1,
                    "missing": 0,
                    "conflicting": 0,
                    "coverage": 1.0,
                    "recommended_action": "answer",
                },
                "budget": {
                    "search_calls": 1,
                    "find_calls": 0,
                    "open_calls": 0,
                    "steps": 1,
                    "context_chars": 420,
                },
            },
        }
    )


def test_formats_modes_citations_and_sources() -> None:
    response = _response()

    assert mode_label("answered") == "Answered"
    assert mode_label("permission") == "Permission denied"
    assert citation_rows(response) == [
        {
            "claim": "Two working days notice is required.",
            "critical": True,
            "citation_present": True,
            "visible_evidence": True,
            "support_verdict": "Verified",
            "lexical_support": "87.5%",
            "cited_chunks": "chunk-1",
            "reason": "",
        }
    ]
    assert source_rows(response) == [
        {
            "document": "policy-1",
            "section": "Remote work / Notice",
            "chunk": "chunk-1",
            "preview": "Two working days notice is required.",
        }
    ]


def test_builds_action_evidence_and_budget_rows() -> None:
    trace = _response().trace

    assert action_rows(trace) == [
        {
            "step": 1,
            "tool": "search",
            "status": "ok",
            "latency": "12.3 ms",
            "visible": 2,
            "context_chars": 420,
            "error": "",
        }
    ]
    assert evidence_summary(trace) == {
        "required": 1,
        "supported": 1,
        "missing": 0,
        "conflicting": 0,
        "coverage": 1.0,
        "recommended_action": "answer",
    }
    assert budget_rows(trace)[0] == {
        "resource": "Search calls",
        "used": 1,
    }
    assert budget_rows(trace)[-1] == {
        "resource": "Context chars",
        "used": 420,
    }


def test_missing_optional_trace_fields_return_safe_empty_defaults() -> None:
    assert action_rows({}) == []
    assert budget_rows({}) == []
    assert span_rows(None) == []
    assert evidence_summary({}) == {
        "required": 0,
        "supported": 0,
        "missing": 0,
        "conflicting": 0,
        "coverage": 0.0,
        "recommended_action": "unavailable",
    }


def test_formats_request_spans_and_milliseconds() -> None:
    trace = RequestTrace(
        request_id="req-1",
        method="POST",
        route="/agent/v2/chat",
        status_code=200,
        duration_ms=1234.5,
        outcome="answered",
        model_calls=2,
        model_retries=0,
        model_errors=0,
        spans=[
            {"name": "agent.run", "status": "ok", "duration_ms": 1200.0},
            {"name": "model.chat", "status": "ok", "duration_ms": 850.25},
        ],
    )

    assert span_rows(trace) == [
        {"span": "agent.run", "status": "ok", "duration": "1.20 s"},
        {"span": "model.chat", "status": "ok", "duration": "850.2 ms"},
    ]
    assert format_milliseconds(None) == "-"
    assert format_milliseconds(0) == "0.0 ms"
    assert format_milliseconds(1234.5) == "1.23 s"


def test_request_id_resolution_prefers_custom_then_current_session() -> None:
    assert resolve_request_id(" custom.req-1 ", "current.req-1") == "custom.req-1"
    assert resolve_request_id("", "current.req-1") == "current.req-1"
    assert resolve_request_id("   ", "") == ""


def test_evaluation_rows_colocate_mode_split_sample_and_run_provenance() -> None:
    snapshot = PublicDemoSnapshot.model_validate_json(
        (ROOT / "data" / "v2" / "public" / "demo_snapshot.json").read_text(
            encoding="utf-8"
        )
    )

    layer = quality_layer_rows(snapshot)[0]
    metric = quality_metric_rows(snapshot)[0]
    for row in [layer, metric]:
        assert row["deterministic_mode"] == "deterministic/test"
        assert row["deterministic_cases"] == 28
        assert row["deterministic_run"].endswith("test_suite")
        assert row["live_mode"] == "live/dev"
        assert row["live_cases"] == 24
        assert row["live_run"].endswith("live_dev_suite_r01")

    ablation = ablation_rows(snapshot)[0]
    assert ablation["mode"] == "deterministic"
    assert ablation["split"] == "test"
    assert ablation["run_id"].endswith("test_ablation")

    runtime = load_rows(snapshot)[0]
    assert runtime["mode"] == "live"
    assert runtime["sample_size"] == runtime["requests"]
    assert runtime["run_id"].endswith("demo_load_r2")

    security = security_rows(snapshot)[0]
    assert security["mode"] == "deterministic"
    assert security["split"] == "test"
    assert security["run_id"].endswith("test_suite")
