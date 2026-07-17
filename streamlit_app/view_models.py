from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domain.evidence import AnswerResponse
from app.evaluation.public_snapshot import PublicDemoSnapshot
from app.observability.tracing import RequestTrace


_MODE_LABELS = {
    "answered": "Answered",
    "partial": "Partial evidence",
    "not_found": "Not found",
    "permission": "Permission denied",
    "unsafe": "Unsafe request",
    "system": "System error",
    "budget": "Budget stopped",
}
_BUDGET_LABELS = (
    ("search_calls", "Search calls"),
    ("find_calls", "Find calls"),
    ("open_calls", "Open calls"),
    ("steps", "Agent steps"),
    ("context_chars", "Context chars"),
)


def mode_label(mode: str) -> str:
    return _MODE_LABELS.get(mode, mode.replace("_", " ").title())


def resolve_request_id(entered: str, current: str) -> str:
    return entered.strip() or current.strip()


def citation_rows(response: AnswerResponse) -> list[dict[str, Any]]:
    claims = {claim.claim_id: claim for claim in response.claims}
    rows: list[dict[str, Any]] = []
    for citation in response.citations:
        claim = claims.get(citation.claim_id)
        rows.append(
            {
                "claim": claim.text if claim is not None else citation.claim_id,
                "critical": claim.critical if claim is not None else None,
                "citation_present": citation.citation_present,
                "visible_evidence": citation.references_visible_evidence,
                "support_verdict": (
                    "Verified" if citation.supported else "Unsupported"
                ),
                "lexical_support": f"{citation.lexical_support:.1%}",
                "cited_chunks": ", ".join(citation.cited_chunk_ids),
                "reason": citation.unsupported_reason or "",
            }
        )
    return rows


def source_rows(response: AnswerResponse) -> list[dict[str, Any]]:
    return [
        {
            "document": source.doc_id,
            "section": " / ".join(source.section_path),
            "chunk": source.chunk_id,
            "preview": source.preview,
        }
        for source in response.sources
    ]


def action_rows(trace: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(trace, Mapping) or not isinstance(trace.get("steps"), list):
        return []
    rows: list[dict[str, Any]] = []
    for index, step in enumerate(trace["steps"], start=1):
        if not isinstance(step, Mapping):
            continue
        rows.append(
            {
                "step": _safe_int(step.get("sequence"), index),
                "tool": str(step.get("tool", "unknown")),
                "status": str(step.get("status", "unknown")),
                "latency": format_milliseconds(step.get("latency_ms")),
                "visible": _safe_int(step.get("visible_count"), 0),
                "context_chars": _safe_int(
                    step.get("context_chars_added"),
                    0,
                ),
                "error": str(step.get("error_code") or ""),
            }
        )
    return rows


def evidence_summary(trace: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = {
        "required": 0,
        "supported": 0,
        "missing": 0,
        "conflicting": 0,
        "coverage": 0.0,
        "recommended_action": "unavailable",
    }
    if not isinstance(trace, Mapping) or not isinstance(
        trace.get("evidence"),
        Mapping,
    ):
        return defaults
    value = trace["evidence"]
    return {
        "required": _safe_int(value.get("required"), 0),
        "supported": _safe_int(value.get("supported"), 0),
        "missing": _safe_int(value.get("missing"), 0),
        "conflicting": _safe_int(value.get("conflicting"), 0),
        "coverage": _safe_float(value.get("coverage"), 0.0),
        "recommended_action": str(
            value.get("recommended_action") or "unavailable"
        ),
    }


def budget_rows(trace: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(trace, Mapping) or not isinstance(
        trace.get("budget"),
        Mapping,
    ):
        return []
    budget = trace["budget"]
    return [
        {"resource": label, "used": _safe_int(budget.get(key), 0)}
        for key, label in _BUDGET_LABELS
    ]


def span_rows(
    trace: RequestTrace | Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if trace is None:
        return []
    if isinstance(trace, RequestTrace):
        spans = [span.model_dump(mode="json") for span in trace.spans]
    elif isinstance(trace, Mapping) and isinstance(trace.get("spans"), list):
        spans = trace["spans"]
    else:
        return []
    return [
        {
            "span": str(span.get("name", "unknown")),
            "status": str(span.get("status", "unknown")),
            "duration": format_milliseconds(span.get("duration_ms")),
        }
        for span in spans
        if isinstance(span, Mapping)
    ]


def quality_layer_rows(snapshot: PublicDemoSnapshot) -> list[dict[str, Any]]:
    deterministic = snapshot.quality.deterministic
    live = snapshot.quality.live
    deterministic_run = _evidence_run_id(snapshot, "Deterministic quality")
    live_run = _evidence_run_id(snapshot, "Live quality")
    return [
        {
            "layer": row.layer.replace("_", " ").title(),
            "deterministic": row.deterministic_rate,
            "deterministic_mode": (
                f"{deterministic.mode}/{deterministic.split}"
            ),
            "deterministic_cases": deterministic.cases,
            "deterministic_run": deterministic_run,
            "live": row.live_rate,
            "live_mode": f"{live.mode}/{live.split}",
            "live_cases": live.cases,
            "live_run": live_run,
        }
        for row in snapshot.quality.layers
    ]


def quality_metric_rows(snapshot: PublicDemoSnapshot) -> list[dict[str, Any]]:
    deterministic = snapshot.quality.deterministic
    live = snapshot.quality.live
    deterministic_run = _evidence_run_id(snapshot, "Deterministic quality")
    live_run = _evidence_run_id(snapshot, "Live quality")
    return [
        {
            "metric": row.label,
            "layer": row.layer.title(),
            "deterministic": row.deterministic,
            "deterministic_mode": (
                f"{deterministic.mode}/{deterministic.split}"
            ),
            "deterministic_cases": deterministic.cases,
            "deterministic_run": deterministic_run,
            "live": row.live,
            "live_mode": f"{live.mode}/{live.split}",
            "live_cases": live.cases,
            "live_run": live_run,
        }
        for row in snapshot.quality.metrics
    ]


def security_rows(snapshot: PublicDemoSnapshot) -> list[dict[str, Any]]:
    labels = {
        "direct_prompt_injection": "Direct prompt injection",
        "acl_isolation": "ACL isolation",
        "trace_redaction": "Trace redaction",
        "indirect_document_injection": "Indirect document injection",
    }
    run_id = _evidence_run_id(snapshot, "Deterministic quality")
    rows: list[dict[str, Any]] = []
    for key, label in labels.items():
        check = getattr(snapshot.security, key)
        rows.append(
            {
                "check": label,
                "status": check.status.upper(),
                "observations": check.checks,
                "failures": check.failures,
                "success_rate": check.success_rate,
                "note": check.note,
                "mode": "deterministic",
                "split": "test",
                "sample_size": check.checks,
                "run_id": run_id,
            }
        )
    return rows


def ablation_rows(snapshot: PublicDemoSnapshot) -> list[dict[str, Any]]:
    run_id = _evidence_run_id(snapshot, "Ablation study")
    return [
        {
            "variant": row.variant,
            "family": row.family,
            "status": row.status.upper(),
            "cases": row.cases,
            "case_pass_rate": row.case_pass_rate,
            "outcome_accuracy": row.outcome_accuracy,
            "document_recall_at_5": row.document_recall_at_5,
            "ndcg_at_5": row.ndcg_at_5,
            "latency_ms_avg": row.latency_ms_avg,
            "tool_calls": row.tool_calls,
            "mode": "deterministic",
            "split": "test",
            "sample_size": row.cases,
            "run_id": run_id,
        }
        for row in snapshot.ablation
    ]


def load_rows(snapshot: PublicDemoSnapshot) -> list[dict[str, Any]]:
    run_id = _evidence_run_id(snapshot, "Load profile")
    return [
        {
            "concurrency": row.concurrency,
            "requests": row.requests,
            "successful": row.successful,
            "failed": row.failed,
            "p50": format_milliseconds(row.p50_ms),
            "p95": format_milliseconds(row.p95_ms),
            "mode": "live",
            "sample_size": row.requests,
            "run_id": run_id,
        }
        for row in snapshot.load.warm
    ]


def evidence_rows(snapshot: PublicDemoSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "evidence": row.label,
            "run_id": row.run_id,
            "artifact": row.artifact,
            "sha256": row.sha256,
        }
        for row in snapshot.evidence
    ]


def format_milliseconds(value: Any) -> str:
    if value is None:
        return "-"
    milliseconds = _safe_float(value, 0.0)
    if milliseconds >= 1000:
        return f"{milliseconds / 1000:.2f} s"
    return f"{milliseconds:.1f} ms"


def _evidence_run_id(snapshot: PublicDemoSnapshot, label: str) -> str:
    return next(item.run_id for item in snapshot.evidence if item.label == label)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "ablation_rows",
    "action_rows",
    "budget_rows",
    "citation_rows",
    "evidence_rows",
    "evidence_summary",
    "format_milliseconds",
    "load_rows",
    "mode_label",
    "quality_layer_rows",
    "quality_metric_rows",
    "resolve_request_id",
    "security_rows",
    "source_rows",
    "span_rows",
]
