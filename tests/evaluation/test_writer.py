from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app import filesystem as filesystem_module
from app.evaluation import writer as writer_module
from app.evaluation.contracts import (
    AblationRow,
    EvaluationCaseResult,
    EvaluationRunResult,
    FailureSignal,
    LayerResult,
)
from app.evaluation.run_manifest import build_run_manifest
from app.evaluation.writer import publish_run


def _result(run_id: str) -> EvaluationRunResult:
    failure = FailureSignal(
        stage="retrieval",
        code="gold_document_missing",
        message="Gold document was not visible in top-k.",
    )
    detail = EvaluationCaseResult(
        case_id="case-1",
        task_type="fact_lookup",
        expected_mode="answered",
        actual_mode="not_found",
        passed=False,
        visible_doc_ids=[],
        layers=[
            LayerResult(
                layer="retrieval",
                applicable=True,
                passed=False,
                metrics={"hit@5": 0.0},
                failures=[failure],
            )
        ],
        primary_failure="retrieval",
        latency_ms=1.25,
        model_calls=0,
        tool_calls=1,
        context_chars=0,
    )
    return EvaluationRunResult(
        run_id=run_id,
        suite="retrieval",
        split="dev",
        mode="deterministic",
        case_count=1,
        summary={"retrieval": {"hit@5": 0.0}},
        metrics_by_category=[
            {"category_type": "task_type", "category": "fact_lookup", "count": 1}
        ],
        details=[detail],
        config={"top_k": 5},
    )


def _manifest(tmp_path: Path, run_id: str):
    dataset = tmp_path / "dev.json"
    dataset.write_text('[{"case_id":"case-1"}]', encoding="utf-8")
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    (corpus_dir / "manifest.json").write_text(
        json.dumps(
            {
                "profile_id": "demo",
                "generator_version": "test",
                "document_count": 1,
            }
        ),
        encoding="utf-8",
    )
    return build_run_manifest(
        run_id=run_id,
        suite="retrieval",
        split="dev",
        mode="deterministic",
        dataset_path=dataset,
        corpus_dir=corpus_dir,
        index_root=None,
        config={"top_k": 5},
        runtime={"variant": "test"},
        repository_root=Path.cwd(),
    )


def test_writer_publishes_required_artifacts_with_hashes(tmp_path: Path) -> None:
    run_id = "run-001"
    output = publish_run(
        tmp_path / "eval_runs",
        _manifest(tmp_path, run_id),
        _result(run_id),
        ablation_rows=[
            AblationRow(
                variant="bm25",
                family="retrieval",
                status="completed",
                case_count=1,
                metrics={"hit@5": 0.0},
                latency_ms_avg=1.25,
                model_calls=0,
                tool_calls=1,
                context_chars=0,
            )
        ],
    )

    assert output == (tmp_path / "eval_runs" / run_id).resolve()
    expected = {
        "manifest.json",
        "summary.json",
        "details.jsonl",
        "failures.csv",
        "metrics_by_category.csv",
        "ablation.csv",
    }
    assert {path.name for path in output.iterdir()} == expected
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["artifacts"]) == expected - {"manifest.json"}
    assert all(len(value) == 64 for value in manifest["artifacts"].values())
    detail = json.loads((output / "details.jsonl").read_text(encoding="utf-8"))
    assert detail["case_id"] == "case-1"
    assert "forbidden_doc_ids" not in detail
    with (output / "failures.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["primary_failure"] == "retrieval"


def test_writer_refuses_existing_or_unsafe_target(tmp_path: Path) -> None:
    run_id = "run-001"
    root = tmp_path / "eval_runs"
    root.mkdir()
    (root / run_id).mkdir()

    with pytest.raises(FileExistsError, match="already exists"):
        publish_run(root, _manifest(tmp_path, run_id), _result(run_id))
    with pytest.raises(ValueError, match="run ID"):
        publish_run(root, _manifest(tmp_path, ".."), _result(".."))


def test_writer_cleans_staging_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run-001"
    root = tmp_path / "eval_runs"

    def fail_rename(source: Path, target: Path):
        del source, target
        raise OSError("synthetic permanent rename failure")

    monkeypatch.setattr(writer_module, "atomic_directory_move", fail_rename)
    with pytest.raises(OSError, match="synthetic permanent"):
        publish_run(root, _manifest(tmp_path, run_id), _result(run_id))

    assert not (root / run_id).exists()
    assert list(root.glob(f".{run_id}.staging-*")) == []


def test_writer_retries_one_transient_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run-001"
    root = tmp_path / "eval_runs"
    original = filesystem_module._move_once
    calls = 0

    def flaky_rename(
        source: Path,
        target: Path,
        *,
        replace: bool,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            error = PermissionError(13, "synthetic transient denial")
            error.winerror = 5
            raise error
        return original(source, target, replace=replace)

    monkeypatch.setattr(filesystem_module, "_move_once", flaky_rename)
    monkeypatch.setattr(filesystem_module.time, "sleep", lambda _: None)
    output = publish_run(root, _manifest(tmp_path, run_id), _result(run_id))

    assert 2 <= calls <= filesystem_module._WINDOWS_DIRECTORY_MOVE_ATTEMPTS
    assert output.exists()
