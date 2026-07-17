from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SnapshotLayer = Literal["retrieval", "response", "agent", "security"]
MetricKey = Literal[
    "document_recall_at_5",
    "ndcg_at_5",
    "precision_at_5",
    "mrr",
    "authority_accuracy",
    "atomic_fact_completeness",
    "citation_correctness",
    "unsupported_claim_rate",
    "final_outcome_correct",
    "tool_choice_correct",
    "trace_complete",
    "exact_trajectory_contract",
]
AblationVariant = Literal[
    "bm25",
    "dense",
    "hybrid_rrf",
    "hybrid_metadata_temporal",
    "hybrid_diversity_parent",
    "hybrid_optional_reranker",
    "fixed_rag",
    "bounded_agentic_retrieval",
]
_EXPECTED_LAYERS = {"retrieval", "response", "agent", "security"}
_EXPECTED_ABLATIONS = {
    "bm25",
    "dense",
    "hybrid_rrf",
    "hybrid_metadata_temporal",
    "hybrid_diversity_parent",
    "hybrid_optional_reranker",
    "fixed_rag",
    "bounded_agentic_retrieval",
}
_EXPECTED_EVIDENCE_ARTIFACTS = {
    "Deterministic quality": "summary.json",
    "Live quality": "summary.json",
    "Ablation study": "ablation.csv",
    "Load profile": "summary.json",
    "Load manifest": "manifest.json",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        strict=True,
    )


class EvidenceRef(StrictModel):
    label: str = Field(min_length=1, max_length=80)
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    artifact: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OutcomeSummary(StrictModel):
    mode: Literal["deterministic", "live"]
    split: Literal["dev", "test"]
    cases: int = Field(ge=1)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    rate: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_outcome(self) -> OutcomeSummary:
        if self.passed + self.failed != self.cases:
            raise ValueError("passed and failed must equal cases")
        if abs(self.rate - self.passed / self.cases) > 1e-12:
            raise ValueError("rate must equal passed / cases")
        return self


class LayerComparison(StrictModel):
    layer: SnapshotLayer
    deterministic_rate: float = Field(ge=0.0, le=1.0)
    live_rate: float = Field(ge=0.0, le=1.0)


class MetricComparison(StrictModel):
    key: MetricKey
    label: str = Field(min_length=1, max_length=80)
    layer: SnapshotLayer
    deterministic: float | None = None
    live: float | None = None


class QualitySnapshot(StrictModel):
    deterministic: OutcomeSummary
    live: OutcomeSummary
    layers: list[LayerComparison] = Field(min_length=4, max_length=4)
    metrics: list[MetricComparison] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_semantic_roles(self) -> QualitySnapshot:
        if (self.deterministic.mode, self.deterministic.split) != (
            "deterministic",
            "test",
        ):
            raise ValueError("deterministic quality must be deterministic test")
        if (self.live.mode, self.live.split) != ("live", "dev"):
            raise ValueError("live quality must be live dev")
        layers = [item.layer for item in self.layers]
        if set(layers) != _EXPECTED_LAYERS or len(layers) != len(set(layers)):
            raise ValueError("quality layers must contain each layer exactly once")
        metric_keys = [item.key for item in self.metrics]
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("quality metric keys must be unique")
        return self


class SecurityCheck(StrictModel):
    status: Literal["passed", "failed", "not_run"]
    checks: int = Field(ge=0)
    failures: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_check(self) -> SecurityCheck:
        if self.status == "not_run":
            if self.checks != 0 or self.failures != 0 or self.success_rate is not None:
                raise ValueError("not_run checks must have no observations")
            return self
        if self.checks == 0 or self.failures > self.checks:
            raise ValueError("executed checks require valid observation counts")
        expected = (self.checks - self.failures) / self.checks
        if self.success_rate is None or abs(self.success_rate - expected) > 1e-12:
            raise ValueError("success_rate must match observation counts")
        if (self.status == "passed") != (self.failures == 0):
            raise ValueError("status must agree with failures")
        return self


class SecuritySnapshot(StrictModel):
    direct_prompt_injection: SecurityCheck
    acl_isolation: SecurityCheck
    trace_redaction: SecurityCheck
    indirect_document_injection: SecurityCheck


class AblationResult(StrictModel):
    variant: AblationVariant
    family: Literal["retrieval", "workflow"]
    status: Literal["completed", "not_run"]
    reason: str | None = Field(default=None, max_length=120)
    cases: int = Field(ge=0)
    case_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    document_recall_at_5: float | None = Field(default=None, ge=0.0, le=1.0)
    ndcg_at_5: float | None = Field(default=None, ge=0.0, le=1.0)
    precision_at_5: float | None = Field(default=None, ge=0.0, le=1.0)
    acl_leakage_count: float | None = Field(default=None, ge=0.0)
    outcome_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms_avg: float | None = Field(default=None, ge=0.0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    context_chars: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_status(self) -> AblationResult:
        if self.status == "not_run":
            if self.cases != 0 or not self.reason:
                raise ValueError("not_run ablations require zero cases and a reason")
        elif self.cases == 0:
            raise ValueError("completed ablations require observed cases")
        return self


class WarmLoadLevel(StrictModel):
    concurrency: int = Field(ge=1)
    requests: int = Field(ge=1)
    successful: int = Field(ge=0)
    failed: int = Field(ge=0)
    p50_ms: float = Field(ge=0.0)
    p95_ms: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_requests(self) -> WarmLoadLevel:
        if self.successful + self.failed != self.requests:
            raise ValueError("load outcomes must equal requests")
        if self.p50_ms > self.p95_ms:
            raise ValueError("p50 must not exceed p95")
        return self


class IndexSummary(StrictModel):
    embedding_model: str = Field(min_length=1, max_length=80)
    embedding_dimension: int = Field(ge=1)
    chunk_count: int = Field(ge=1)


class LoadSnapshot(StrictModel):
    profile: str = Field(min_length=1, max_length=40)
    total_requests: int = Field(ge=1)
    successful: int = Field(ge=0)
    failed: int = Field(ge=0)
    cold_p95_ms: float = Field(ge=0.0)
    warm: list[WarmLoadLevel] = Field(min_length=1, max_length=10)
    model_calls_delta: int = Field(ge=0)
    rss_delta_bytes: int
    index: IndexSummary

    @model_validator(mode="after")
    def validate_totals(self) -> LoadSnapshot:
        if self.successful + self.failed != self.total_requests:
            raise ValueError("load totals must equal total_requests")
        observed = 1 + sum(level.requests for level in self.warm)
        if observed != self.total_requests:
            raise ValueError("cold and warm requests must equal total_requests")
        concurrency = [level.concurrency for level in self.warm]
        if len(concurrency) != len(set(concurrency)):
            raise ValueError("warm concurrency levels must be unique")
        return self


class PublicDemoSnapshot(StrictModel):
    schema_version: Literal["public_demo_snapshot_v1"] = "public_demo_snapshot_v1"
    producer: Literal["enterprise_agentic_rag_v2"] = "enterprise_agentic_rag_v2"
    snapshot_id: str = Field(pattern=r"^public-demo-[0-9a-f]{12}$")
    evidence_cutoff_utc: datetime
    quality: QualitySnapshot
    security: SecuritySnapshot
    ablation: list[AblationResult] = Field(min_length=1, max_length=8)
    load: LoadSnapshot
    evidence: list[EvidenceRef] = Field(min_length=5, max_length=5)
    limitations: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_snapshot_contract(self) -> PublicDemoSnapshot:
        variants = [item.variant for item in self.ablation]
        if (
            set(variants) != _EXPECTED_ABLATIONS
            or len(variants) != len(set(variants))
        ):
            raise ValueError(
                "ablation must contain every canonical variant exactly once"
            )
        for item in self.ablation:
            expected_family = (
                "workflow"
                if item.variant in {"fixed_rag", "bounded_agentic_retrieval"}
                else "retrieval"
            )
            if item.family != expected_family:
                raise ValueError("ablation variant family is invalid")

        labels = [item.label for item in self.evidence]
        if (
            set(labels) != set(_EXPECTED_EVIDENCE_ARTIFACTS)
            or len(labels) != len(set(labels))
        ):
            raise ValueError(
                "evidence must contain every canonical role exactly once"
            )
        refs = {item.label: item for item in self.evidence}
        if any(
            refs[label].artifact != artifact
            for label, artifact in _EXPECTED_EVIDENCE_ARTIFACTS.items()
        ):
            raise ValueError("evidence role artifact is invalid")
        if refs["Load profile"].run_id != refs["Load manifest"].run_id:
            raise ValueError("load evidence must reference one run")
        if self.snapshot_id != _snapshot_id_from_evidence(self.evidence):
            raise ValueError("snapshot_id must be derived from evidence hashes")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("limitations must be unique")
        return self


@dataclass(frozen=True)
class SnapshotInputs:
    deterministic_run: Path
    live_run: Path
    ablation_run: Path
    load_run: Path


_LAYER_MAP: tuple[tuple[str, SnapshotLayer], ...] = (
    ("retrieval", "retrieval"),
    ("answer", "response"),
    ("agent", "agent"),
    ("security", "security"),
)
_METRIC_MAP: tuple[tuple[str, str, MetricKey, str, SnapshotLayer], ...] = (
    (
        "retrieval",
        "document_recall@5",
        "document_recall_at_5",
        "Document recall@5",
        "retrieval",
    ),
    ("retrieval", "ndcg@5", "ndcg_at_5", "NDCG@5", "retrieval"),
    (
        "retrieval",
        "precision@5",
        "precision_at_5",
        "Precision@5",
        "retrieval",
    ),
    ("retrieval", "mrr", "mrr", "MRR", "retrieval"),
    (
        "retrieval",
        "authority_accuracy",
        "authority_accuracy",
        "Authority accuracy",
        "retrieval",
    ),
    (
        "answer",
        "atomic_fact_completeness",
        "atomic_fact_completeness",
        "Atomic fact completeness",
        "response",
    ),
    (
        "answer",
        "citation_correctness",
        "citation_correctness",
        "Citation correctness",
        "response",
    ),
    (
        "answer",
        "unsupported_claim_rate",
        "unsupported_claim_rate",
        "Unsupported claim rate",
        "response",
    ),
    (
        "agent",
        "final_outcome_correct",
        "final_outcome_correct",
        "Final outcome accuracy",
        "agent",
    ),
    (
        "agent",
        "tool_choice_correct",
        "tool_choice_correct",
        "Tool choice accuracy",
        "agent",
    ),
    (
        "agent",
        "trace_complete",
        "trace_complete",
        "Trace completeness",
        "agent",
    ),
    (
        "agent",
        "exact_trajectory_contract",
        "exact_trajectory_contract",
        "Exact trajectory contract",
        "agent",
    ),
)
_FORBIDDEN_PUBLIC_TEXT = (
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"/Users/", re.IGNORECASE),
    re.compile(r'"(?:question|answer|tenant_id|user_id|source_preview)"', re.I),
)


def build_public_snapshot(inputs: SnapshotInputs) -> PublicDemoSnapshot:
    deterministic_manifest = _read_manifest(inputs.deterministic_run)
    live_manifest = _read_manifest(inputs.live_run)
    ablation_manifest = _read_manifest(inputs.ablation_run)
    load_manifest = _read_manifest(inputs.load_run)

    deterministic_bytes, deterministic_hash = _verified_artifact(
        inputs.deterministic_run,
        deterministic_manifest,
        "summary.json",
    )
    live_bytes, live_hash = _verified_artifact(
        inputs.live_run,
        live_manifest,
        "summary.json",
    )
    ablation_bytes, ablation_hash = _verified_artifact(
        inputs.ablation_run,
        ablation_manifest,
        "ablation.csv",
    )
    load_bytes, load_hash = _verified_artifact(
        inputs.load_run,
        load_manifest,
        "summary.json",
    )

    deterministic = _json_object(deterministic_bytes, "deterministic summary")
    live = _json_object(live_bytes, "live summary")
    load_summary = _json_object(load_bytes, "load summary")
    _validate_evaluation_source(
        deterministic_manifest,
        deterministic,
        mode="deterministic",
        split="test",
    )
    _validate_evaluation_source(
        live_manifest,
        live,
        mode="live",
        split="dev",
    )
    _validate_run_id(ablation_manifest, None)
    _validate_run_id(load_manifest, load_summary)

    evidence = [
        _evidence_ref(
            "Deterministic quality",
            deterministic_manifest,
            "summary.json",
            deterministic_hash,
        ),
        _evidence_ref(
            "Live quality",
            live_manifest,
            "summary.json",
            live_hash,
        ),
        _evidence_ref(
            "Ablation study",
            ablation_manifest,
            "ablation.csv",
            ablation_hash,
        ),
        _evidence_ref(
            "Load profile",
            load_manifest,
            "summary.json",
            load_hash,
        ),
        _evidence_ref(
            "Load manifest",
            load_manifest,
            "manifest.json",
            _sha256(inputs.load_run / "manifest.json"),
        ),
    ]
    snapshot = PublicDemoSnapshot(
        snapshot_id=_snapshot_id_from_evidence(evidence),
        evidence_cutoff_utc=max(
            _completed_at(manifest)
            for manifest in [
                deterministic_manifest,
                live_manifest,
                ablation_manifest,
                load_manifest,
            ]
        ),
        quality=_quality_snapshot(deterministic, live),
        security=_security_snapshot(deterministic),
        ablation=_ablation_results(ablation_bytes),
        load=_load_snapshot(load_manifest, load_summary),
        evidence=evidence,
        limitations=[
            "Metrics use a generated enterprise demo corpus.",
            "Live quality is one local development run, not a production SLO.",
            "The optional reranker was not admitted and remains NOT RUN.",
            "Indirect instruction injection in retrieved content remains NOT RUN.",
        ],
    )
    _assert_public_payload(snapshot.model_dump_json())
    return snapshot


def export_public_snapshot(
    *,
    deterministic_run: Path,
    live_run: Path,
    ablation_run: Path,
    load_run: Path,
    output: Path,
) -> Path:
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"public snapshot already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_public_snapshot(
        SnapshotInputs(
            deterministic_run=Path(deterministic_run),
            live_run=Path(live_run),
            ablation_run=Path(ablation_run),
            load_run=Path(load_run),
        )
    )
    content = (snapshot.model_dump_json(indent=2) + "\n").encode("utf-8")
    stage = output.parent / f".{output.name}.staging-{uuid.uuid4().hex}"
    try:
        stage.write_bytes(content)
        if output.exists():
            raise FileExistsError(f"public snapshot already exists: {output}")
        _promote_no_replace(stage, output)
    finally:
        stage.unlink(missing_ok=True)
    return output


def _snapshot_id_from_evidence(evidence: list[EvidenceRef]) -> str:
    snapshot_hash = hashlib.sha256(
        "|".join(item.sha256 for item in evidence).encode("ascii")
    ).hexdigest()
    return f"public-demo-{snapshot_hash[:12]}"


def _promote_no_replace(stage: Path, output: Path) -> None:
    os.link(stage, output)


def _read_manifest(run: Path) -> dict[str, Any]:
    run = Path(run)
    if not run.is_dir():
        raise ValueError(f"run directory does not exist: {run.name}")
    path = run / "manifest.json"
    if not path.is_file():
        raise ValueError(f"run manifest does not exist: {run.name}")
    return _json_object(path.read_bytes(), "run manifest")


def _verified_artifact(
    run: Path,
    manifest: dict[str, Any],
    artifact: str,
) -> tuple[bytes, str]:
    declarations = manifest.get("artifacts")
    if not isinstance(declarations, dict) or artifact not in declarations:
        raise ValueError(f"manifest does not declare artifact: {artifact}")
    declaration = declarations[artifact]
    expected = declaration.get("sha256") if isinstance(declaration, dict) else declaration
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"manifest has invalid hash for artifact: {artifact}")
    path = Path(run) / artifact
    if not path.is_file():
        raise ValueError(f"declared artifact does not exist: {artifact}")
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise ValueError(
            f"artifact hash mismatch for {artifact}: expected {expected}, got {actual}"
        )
    return content, actual


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _validate_evaluation_source(
    manifest: dict[str, Any],
    summary: dict[str, Any],
    *,
    mode: str,
    split: str,
) -> None:
    _validate_run_id(manifest, summary)
    for label, source in [("manifest", manifest), ("summary", summary)]:
        if source.get("mode") != mode or source.get("split") != split:
            raise ValueError(f"{label} must describe {mode}/{split}")


def _validate_run_id(
    manifest: dict[str, Any],
    artifact: dict[str, Any] | None,
) -> None:
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str):
        raise ValueError("manifest run_id must be a string")
    if artifact is not None and artifact.get("run_id") != run_id:
        raise ValueError("manifest and artifact run_id mismatch")


def _evidence_ref(
    label: str,
    manifest: dict[str, Any],
    artifact: str,
    digest: str,
) -> EvidenceRef:
    return EvidenceRef(
        label=label,
        run_id=manifest["run_id"],
        artifact=artifact,
        sha256=digest,
    )


def _outcome(summary: dict[str, Any]) -> OutcomeSummary:
    overall = summary["summary"]["overall_case_pass"]
    cases = int(overall["total"])
    passed = int(overall["passed"])
    return OutcomeSummary(
        mode=summary["mode"],
        split=summary["split"],
        cases=cases,
        passed=passed,
        failed=cases - passed,
        rate=float(overall["rate"]),
    )


def _quality_snapshot(
    deterministic: dict[str, Any],
    live: dict[str, Any],
) -> QualitySnapshot:
    layers = [
        LayerComparison(
            layer=public_layer,
            deterministic_rate=_layer_rate(deterministic, source_layer),
            live_rate=_layer_rate(live, source_layer),
        )
        for source_layer, public_layer in _LAYER_MAP
    ]
    metrics = [
        MetricComparison(
            key=public_key,
            label=label,
            layer=public_layer,
            deterministic=_metric_value(
                deterministic,
                source_layer,
                source_metric,
            ),
            live=_metric_value(live, source_layer, source_metric),
        )
        for source_layer, source_metric, public_key, label, public_layer in _METRIC_MAP
    ]
    return QualitySnapshot(
        deterministic=_outcome(deterministic),
        live=_outcome(live),
        layers=layers,
        metrics=metrics,
    )


def _layer_rate(summary: dict[str, Any], layer: str) -> float:
    return float(summary["summary"]["layers"][layer]["pass_rate"]["rate"])


def _metric_value(
    summary: dict[str, Any],
    layer: str,
    metric: str,
) -> float | None:
    payload = summary["summary"]["layers"][layer]["metrics"].get(metric)
    if not isinstance(payload, dict):
        return None
    value = payload.get("mean", payload.get("rate"))
    return None if value is None else float(value)


def _security_snapshot(summary: dict[str, Any]) -> SecuritySnapshot:
    result = summary["summary"]
    probes = result["security_probes"]
    probe_checks = int(probes["probe_count"])
    probe_failures = max(
        int(probes["failure_count"]),
        int(probes["prompt_injection_success_count"]),
    )
    security_metrics = result["layers"]["security"]["metrics"]
    trace = security_metrics["trace_redacted"]
    trace_checks = int(trace["total"])
    trace_failures = trace_checks - int(trace["passed"])
    acl = security_metrics["unauthorized_document_exposure_count"]
    acl_checks = int(acl.get("n", _outcome(summary).cases))
    acl_failures = min(acl_checks, round(float(acl["mean"]) * acl_checks))
    return SecuritySnapshot(
        direct_prompt_injection=_executed_check(
            probe_checks,
            probe_failures,
            "Direct override probes were evaluated before retrieval.",
        ),
        acl_isolation=_executed_check(
            acl_checks,
            acl_failures,
            "Visible retrieval results were checked for unauthorized exposure.",
        ),
        trace_redaction=_executed_check(
            trace_checks,
            trace_failures,
            "Agent traces were checked for sensitive field disclosure.",
        ),
        indirect_document_injection=SecurityCheck(
            status="not_run",
            checks=0,
            failures=0,
            success_rate=None,
            note="No retrieved-content injection fixture exists in this corpus version.",
        ),
    )


def _executed_check(checks: int, failures: int, note: str) -> SecurityCheck:
    if checks <= 0:
        raise ValueError("executed security check requires observations")
    return SecurityCheck(
        status="passed" if failures == 0 else "failed",
        checks=checks,
        failures=failures,
        success_rate=(checks - failures) / checks,
        note=note,
    )


def _ablation_results(content: bytes) -> list[AblationResult]:
    try:
        rows = list(csv.DictReader(content.decode("utf-8-sig").splitlines()))
    except UnicodeDecodeError as exc:
        raise ValueError("ablation.csv is not valid UTF-8") from exc
    results: list[AblationResult] = []
    for row in rows:
        try:
            metrics = json.loads(row["metrics"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("ablation metrics must be a JSON object") from exc
        if not isinstance(metrics, dict):
            raise ValueError("ablation metrics must be a JSON object")
        results.append(
            AblationResult(
                variant=row["variant"],
                family=row["family"],
                status=row["status"],
                reason=row.get("reason") or None,
                cases=_int_field(row, "case_count"),
                case_pass_rate=_optional_metric(metrics, "case_pass_rate"),
                document_recall_at_5=_optional_metric(
                    metrics,
                    "document_recall@5",
                ),
                ndcg_at_5=_optional_metric(metrics, "ndcg@5"),
                precision_at_5=_optional_metric(metrics, "precision@5"),
                acl_leakage_count=_optional_metric(
                    metrics,
                    "acl_leakage_count",
                ),
                outcome_accuracy=_optional_metric(metrics, "outcome_accuracy"),
                latency_ms_avg=_optional_float(row.get("latency_ms_avg")),
                model_calls=_int_field(row, "model_calls"),
                tool_calls=_int_field(row, "tool_calls"),
                context_chars=_int_field(row, "context_chars"),
            )
        )
    if not results:
        raise ValueError("ablation.csv must contain at least one row")
    return results


def _optional_metric(metrics: dict[str, Any], name: str) -> float | None:
    value = metrics.get(name)
    return None if value is None else float(value)


def _optional_float(value: Any) -> float | None:
    return None if value in {None, ""} else float(value)


def _int_field(row: dict[str, Any], name: str) -> int:
    try:
        return int(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"ablation field must be an integer: {name}") from exc


def _load_snapshot(
    manifest: dict[str, Any],
    summary: dict[str, Any],
) -> LoadSnapshot:
    totals = summary["totals"]
    before = manifest["metrics"]["before"]
    after = manifest["metrics"]["after"]
    index = manifest["readiness"]["index"]
    warm = [
        WarmLoadLevel(
            concurrency=int(row["concurrency"]),
            requests=int(row["requests"]),
            successful=int(row["successful"]),
            failed=int(row["failed"]),
            p50_ms=float(row["latency_ms"]["p50"]),
            p95_ms=float(row["latency_ms"]["p95"]),
        )
        for row in summary["warm"]
    ]
    return LoadSnapshot(
        profile=str(summary["profile"]),
        total_requests=int(totals["requests"]),
        successful=int(totals["successful"]),
        failed=int(totals["failed"]),
        cold_p95_ms=float(summary["cold"]["latency_ms"]["p95"]),
        warm=sorted(warm, key=lambda row: row.concurrency),
        model_calls_delta=int(after["models"]["calls"])
        - int(before["models"]["calls"]),
        rss_delta_bytes=int(after["process"]["rss_bytes"])
        - int(before["process"]["rss_bytes"]),
        index=IndexSummary(
            embedding_model=str(index["embedding_model"]),
            embedding_dimension=int(index["embedding_dimension"]),
            chunk_count=int(index["chunk_count"]),
        ),
    )


def _completed_at(manifest: dict[str, Any]) -> datetime:
    value = manifest.get("completed_at_utc")
    if not isinstance(value, str):
        raise ValueError("manifest completed_at_utc must be a string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("manifest completed_at_utc must be ISO-8601") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_public_payload(serialized: str) -> None:
    for pattern in _FORBIDDEN_PUBLIC_TEXT:
        if pattern.search(serialized):
            raise ValueError("public snapshot contains a forbidden field or path")


__all__ = [
    "EvidenceRef",
    "OutcomeSummary",
    "PublicDemoSnapshot",
    "SnapshotInputs",
    "build_public_snapshot",
    "export_public_snapshot",
]
