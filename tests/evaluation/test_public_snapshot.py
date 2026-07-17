from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

import app.evaluation.public_snapshot as public_snapshot_module
from app.evaluation.public_snapshot import (
    PublicDemoSnapshot,
    SnapshotInputs,
    build_public_snapshot,
    export_public_snapshot,
)
from scripts.export_public_demo_snapshot import main


def _json_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: dict) -> str:
    content = _json_bytes(payload)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _write_ablation(path: Path) -> str:
    fields = [
        "variant",
        "family",
        "status",
        "reason",
        "case_count",
        "metrics",
        "latency_ms_avg",
        "model_calls",
        "tool_calls",
        "context_chars",
    ]
    def retrieval_row(
        variant: str,
        *,
        recall: float,
        pass_rate: float,
    ) -> dict:
        return {
            "variant": variant,
            "family": "retrieval",
            "status": "completed",
            "reason": "",
            "case_count": 28,
            "metrics": json.dumps(
                {
                    "case_pass_rate": pass_rate,
                    "document_recall@5": recall,
                    "ndcg@5": recall,
                    "precision@5": 0.2,
                    "acl_leakage_count": 0,
                }
            ),
            "latency_ms_avg": 0.5,
            "model_calls": 0,
            "tool_calls": 28,
            "context_chars": 10000,
        }

    rows = [
        retrieval_row("bm25", recall=0.8, pass_rate=0.8),
        retrieval_row("dense", recall=0.82, pass_rate=0.82),
        retrieval_row("hybrid_rrf", recall=0.9, pass_rate=0.9),
        {
            "variant": "hybrid_metadata_temporal",
            "family": "retrieval",
            "status": "completed",
            "reason": "",
            "case_count": 28,
            "metrics": json.dumps(
                {
                    "case_pass_rate": 1.0,
                    "document_recall@5": 1.0,
                    "ndcg@5": 1.0,
                    "precision@5": 0.2380952380952381,
                    "acl_leakage_count": 0,
                    "private_metric": 99,
                }
            ),
            "latency_ms_avg": 0.78,
            "model_calls": 0,
            "tool_calls": 28,
            "context_chars": 11551,
        },
        retrieval_row(
            "hybrid_diversity_parent",
            recall=1.0,
            pass_rate=1.0,
        ),
        {
            "variant": "hybrid_optional_reranker",
            "family": "retrieval",
            "status": "not_run",
            "reason": "no_admitted_reranker",
            "case_count": 0,
            "metrics": "{}",
            "latency_ms_avg": "",
            "model_calls": 0,
            "tool_calls": 0,
            "context_chars": 0,
        },
        {
            "variant": "fixed_rag",
            "family": "workflow",
            "status": "completed",
            "reason": "",
            "case_count": 28,
            "metrics": json.dumps({"outcome_accuracy": 0.8571428571428571}),
            "latency_ms_avg": 1.0,
            "model_calls": 0,
            "tool_calls": 28,
            "context_chars": 11551,
        },
        {
            "variant": "bounded_agentic_retrieval",
            "family": "workflow",
            "status": "completed",
            "reason": "",
            "case_count": 28,
            "metrics": json.dumps({"outcome_accuracy": 1.0}),
            "latency_ms_avg": 4.97,
            "model_calls": 0,
            "tool_calls": 47,
            "context_chars": 15732,
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evaluation_summary(
    *,
    run_id: str,
    mode: str,
    split: str,
    cases: int,
    passed: int,
) -> dict:
    rate = passed / cases
    layers = {}
    for layer in ["retrieval", "answer", "agent", "security"]:
        layer_passed = cases if layer in {"retrieval", "security"} else passed
        layers[layer] = {
            "pass_rate": {
                "passed": layer_passed,
                "total": cases,
                "rate": layer_passed / cases,
            },
            "metrics": {},
        }
    layers["retrieval"]["metrics"] = {
        "document_recall@5": {"mean": 1.0},
        "ndcg@5": {"mean": 1.0},
        "precision@5": {"mean": 0.24},
        "mrr": {"mean": 1.0},
        "authority_accuracy": {"mean": 1.0},
        "acl_leakage_count": {"mean": 0.0},
    }
    layers["answer"]["metrics"] = {
        "atomic_fact_completeness": {"mean": rate},
        "citation_correctness": {"mean": 1.0},
        "unsupported_claim_rate": {"mean": 0.0},
    }
    layers["agent"]["metrics"] = {
        "final_outcome_correct": {
            "passed": passed,
            "total": cases,
            "rate": rate,
        },
        "tool_choice_correct": {
            "passed": cases,
            "total": cases,
            "rate": 1.0,
        },
        "trace_complete": {
            "passed": cases,
            "total": cases,
            "rate": 1.0,
        },
        "exact_trajectory_contract": {
            "passed": passed,
            "total": cases,
            "rate": rate,
        },
    }
    layers["security"]["metrics"] = {
        "trace_redacted": {
            "passed": cases,
            "total": cases,
            "rate": 1.0,
        },
        "unauthorized_document_exposure_count": {
            "mean": 0.0,
            "n": cases,
        },
    }
    return {
        "schema_version": "enterprise_evaluation_result_v1",
        "run_id": run_id,
        "mode": mode,
        "split": split,
        "case_count": cases,
        "summary": {
            "failed_case_count": cases - passed,
            "overall_case_pass": {
                "passed": passed,
                "total": cases,
                "rate": rate,
            },
            "layers": layers,
            "security_probes": {
                "failure_count": 0,
                "passed": True,
                "probe_count": 4,
                "probe_trace_redaction_rate": 1.0,
                "prompt_injection_success_count": 0,
                "prompt_injection_success_rate": 0.0,
                "unsafe_pre_retrieval_refusal_rate": 1.0,
            },
        },
    }


def _evaluation_run(
    root: Path,
    *,
    run_id: str,
    mode: str,
    split: str,
    cases: int,
    passed: int,
    ablation: bool = False,
) -> Path:
    run = root / run_id
    run.mkdir()
    artifacts = {
        "summary.json": _write_json(
            run / "summary.json",
            _evaluation_summary(
                run_id=run_id,
                mode=mode,
                split=split,
                cases=cases,
                passed=passed,
            ),
        )
    }
    if ablation:
        artifacts["ablation.csv"] = _write_ablation(run / "ablation.csv")
    _write_json(
        run / "manifest.json",
        {
            "schema_version": "enterprise_evaluation_run_manifest_v1",
            "run_id": run_id,
            "mode": mode,
            "split": split,
            "completed_at_utc": "2026-07-16T15:01:09Z",
            "artifacts": artifacts,
        },
    )
    return run


def _load_run(root: Path) -> Path:
    run_id = "load-demo-r2"
    run = root / run_id
    run.mkdir()
    summary_hash = _write_json(
        run / "summary.json",
        {
            "schema_version": "load-summary-v1",
            "run_id": run_id,
            "profile": "demo",
            "totals": {"requests": 31, "successful": 31, "failed": 0},
            "cold": {"latency_ms": {"p95": 1667.68}},
            "warm": [
                {
                    "concurrency": 1,
                    "requests": 10,
                    "successful": 10,
                    "failed": 0,
                    "latency_ms": {"p50": 1090.97, "p95": 1136.18},
                },
                {
                    "concurrency": 5,
                    "requests": 10,
                    "successful": 10,
                    "failed": 0,
                    "latency_ms": {"p50": 3901.96, "p95": 4406.29},
                },
                {
                    "concurrency": 10,
                    "requests": 10,
                    "successful": 10,
                    "failed": 0,
                    "latency_ms": {"p50": 4827.4, "p95": 8632.73},
                },
            ],
        },
    )
    _write_json(
        run / "manifest.json",
        {
            "schema_version": "load-manifest-v1",
            "run_id": run_id,
            "profile": "demo",
            "completed_at_utc": "2026-07-16T17:48:26Z",
            "artifacts": {
                "summary.json": {"bytes": 1, "sha256": summary_hash}
            },
            "metrics": {
                "before": {
                    "models": {"calls": 0},
                    "process": {"rss_bytes": 92_991_488},
                },
                "after": {
                    "models": {"calls": 62},
                    "process": {"rss_bytes": 159_088_640},
                },
            },
            "readiness": {
                "index": {
                    "chunk_count": 64,
                    "embedding_dimension": 1024,
                    "embedding_model": "bge-m3",
                }
            },
        },
    )
    return run


@pytest.fixture
def snapshot_inputs(tmp_path: Path) -> SnapshotInputs:
    return SnapshotInputs(
        deterministic_run=_evaluation_run(
            tmp_path,
            run_id="deterministic-test",
            mode="deterministic",
            split="test",
            cases=28,
            passed=28,
        ),
        live_run=_evaluation_run(
            tmp_path,
            run_id="live-dev-r01",
            mode="live",
            split="dev",
            cases=24,
            passed=23,
        ),
        ablation_run=_evaluation_run(
            tmp_path,
            run_id="deterministic-ablation",
            mode="deterministic",
            split="test",
            cases=28,
            passed=28,
            ablation=True,
        ),
        load_run=_load_run(tmp_path),
    )


def test_builds_allowlisted_hash_traceable_snapshot(
    snapshot_inputs: SnapshotInputs,
) -> None:
    snapshot = build_public_snapshot(snapshot_inputs)

    assert snapshot.quality.deterministic.passed == 28
    assert snapshot.quality.live.failed == 1
    assert snapshot.security.direct_prompt_injection.status == "passed"
    assert snapshot.security.indirect_document_injection.status == "not_run"
    assert snapshot.load.total_requests == 31
    assert snapshot.load.model_calls_delta == 62
    assert snapshot.load.rss_delta_bytes == 66_097_152
    assert len(snapshot.evidence) == 5
    assert all(len(item.sha256) == 64 for item in snapshot.evidence)

    serialized = snapshot.model_dump_json()
    for forbidden in ["C:\\Users", "D:\\", "question", "answer", "tenant_id"]:
        assert forbidden not in serialized
    assert "private_metric" not in serialized
    PublicDemoSnapshot.model_validate_json(serialized)


def test_snapshot_rejects_type_coercion_and_duplicate_semantic_roles(
    snapshot_inputs: SnapshotInputs,
) -> None:
    snapshot = build_public_snapshot(snapshot_inputs)

    coerced = snapshot.model_dump()
    coerced["quality"]["deterministic"]["cases"] = "28"
    with pytest.raises(ValueError):
        PublicDemoSnapshot.model_validate(coerced)

    duplicate_layer = snapshot.model_dump()
    duplicate_layer["quality"]["layers"][1] = dict(
        duplicate_layer["quality"]["layers"][0]
    )
    with pytest.raises(ValueError, match="layers"):
        PublicDemoSnapshot.model_validate(duplicate_layer)

    duplicate_ablation = snapshot.model_dump()
    duplicate_ablation["ablation"][1] = dict(duplicate_ablation["ablation"][0])
    with pytest.raises(ValueError, match="ablation"):
        PublicDemoSnapshot.model_validate(duplicate_ablation)

    duplicate_evidence = snapshot.model_dump()
    duplicate_evidence["evidence"][1] = dict(duplicate_evidence["evidence"][0])
    with pytest.raises(ValueError, match="evidence"):
        PublicDemoSnapshot.model_validate(duplicate_evidence)


def test_snapshot_id_must_be_derived_from_evidence_hashes(
    snapshot_inputs: SnapshotInputs,
) -> None:
    payload = build_public_snapshot(snapshot_inputs).model_dump()
    payload["snapshot_id"] = "public-demo-000000000000"

    with pytest.raises(ValueError, match="snapshot_id"):
        PublicDemoSnapshot.model_validate(payload)


def test_rejects_manifest_declared_hash_mismatch(
    snapshot_inputs: SnapshotInputs,
) -> None:
    summary = snapshot_inputs.live_run / "summary.json"
    summary.write_text(summary.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        build_public_snapshot(snapshot_inputs)


def test_export_is_deterministic_and_refuses_existing_output(
    snapshot_inputs: SnapshotInputs,
    tmp_path: Path,
) -> None:
    first = tmp_path / "public" / "first.json"
    second = tmp_path / "public" / "second.json"
    kwargs = {
        "deterministic_run": snapshot_inputs.deterministic_run,
        "live_run": snapshot_inputs.live_run,
        "ablation_run": snapshot_inputs.ablation_run,
        "load_run": snapshot_inputs.load_run,
    }

    export_public_snapshot(**kwargs, output=first)
    export_public_snapshot(**kwargs, output=second)

    assert first.read_bytes() == second.read_bytes()
    with pytest.raises(FileExistsError, match="already exists"):
        export_public_snapshot(**kwargs, output=first)


def test_export_cleans_staging_after_promotion_failure(
    snapshot_inputs: SnapshotInputs,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "public" / "demo.json"

    def fail_promotion(stage: Path, target: Path) -> None:
        raise OSError("synthetic promotion failure")

    monkeypatch.setattr(
        public_snapshot_module,
        "_promote_no_replace",
        fail_promotion,
        raising=False,
    )
    with pytest.raises(OSError, match="synthetic promotion"):
        export_public_snapshot(
            deterministic_run=snapshot_inputs.deterministic_run,
            live_run=snapshot_inputs.live_run,
            ablation_run=snapshot_inputs.ablation_run,
            load_run=snapshot_inputs.load_run,
            output=output,
        )

    assert not output.exists()
    assert list(output.parent.glob(f".{output.name}.staging-*")) == []


def test_atomic_promotion_never_replaces_a_competing_target(
    tmp_path: Path,
) -> None:
    stage = tmp_path / ".demo.staging"
    target = tmp_path / "demo.json"
    stage.write_text("candidate", encoding="utf-8")
    target.write_text("competing-writer", encoding="utf-8")

    with pytest.raises(FileExistsError):
        public_snapshot_module._promote_no_replace(stage, target)

    assert target.read_text(encoding="utf-8") == "competing-writer"


def test_cli_help_creates_no_output(tmp_path: Path) -> None:
    output = tmp_path / "demo.json"

    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert not output.exists()
