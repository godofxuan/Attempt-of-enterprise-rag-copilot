from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.ablation import AblationEvaluation
from app.evaluation.contracts import AblationRow, EvaluationRunResult
from scripts import eval_ablation_v2_enterprise


def write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text(
        json.dumps(
            {
                "profile_id": "demo",
                "generator_version": "test",
                "document_count": 1,
            }
        ),
        encoding="utf-8",
    )
    case = {
        "case_id": "case-one",
        "question": "Policy A?",
        "task_type": "fact_lookup",
        "answer_mode": "answered",
        "user_context": {
            "user_id": "employee",
            "tenant": "tenant-one",
            "region": "cn",
            "groups": ["employees"],
        },
        "required_fact_ids": ["fact-a"],
        "gold_doc_ids": ["doc-a"],
        "distractor_doc_ids": [],
        "forbidden_doc_ids": [],
        "expected_answer": "3 days",
        "expected_filters": {},
        "expected_authority_doc_ids": ["doc-a"],
        "tags": ["current"],
    }
    payload = json.dumps([case]).encode("utf-8")
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    (eval_dir / "dev.json").write_bytes(payload)
    (eval_dir / "test.json").write_bytes(payload)
    (eval_dir / "test_manifest.sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  test.json\n",
        encoding="utf-8",
    )
    return corpus, eval_dir


def test_ablation_help_has_no_side_effect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        eval_ablation_v2_enterprise.main(["--help"])
    assert exc.value.code == 0
    assert list(tmp_path.iterdir()) == []


def test_ablation_cli_publishes_rows_and_refuses_existing_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    corpus, eval_dir = write_inputs(tmp_path)
    builds = 0
    runtime = SimpleNamespace(
        mode="deterministic",
        variant="fake-runtime",
        index_root=tmp_path / "missing-index",
        metadata=lambda: {"variant": "fake-runtime", "model_calls": 0},
    )

    def build_runtime(*args, **kwargs):
        nonlocal builds
        builds += 1
        return runtime

    row = AblationRow(
        variant="bm25",
        family="retrieval",
        status="completed",
        case_count=1,
        metrics={"document_recall@5": 1.0},
        latency_ms_avg=1.0,
        model_calls=0,
        tool_calls=1,
        context_chars=100,
    )
    monkeypatch.setattr(
        eval_ablation_v2_enterprise,
        "build_deterministic_runtime",
        build_runtime,
    )
    monkeypatch.setattr(
        eval_ablation_v2_enterprise,
        "run_ablation",
        lambda *args, **kwargs: AblationEvaluation(
            rows=[row],
            failure_case_ids={"bm25": []},
            answer_by_case={"case-one": "answer"},
        ),
    )
    monkeypatch.setattr(
        eval_ablation_v2_enterprise,
        "evaluate_suite",
        lambda *args, **kwargs: EvaluationRunResult(
            run_id=kwargs["run_id"],
            suite="retrieval",
            split=kwargs["split"],
            mode="deterministic",
            case_count=0,
            summary={},
            details=[],
        ),
    )
    args = [
        "--split",
        "dev",
        "--run-id",
        "ablation-one",
        "--corpus-dir",
        str(corpus),
        "--eval-dir",
        str(eval_dir),
        "--out-dir",
        str(tmp_path / "runs"),
    ]

    assert eval_ablation_v2_enterprise.main(args) == 0
    output = tmp_path / "runs" / "ablation-one"
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["suite"] == "ablation"
    assert "bm25" in (output / "ablation.csv").read_text(encoding="utf-8-sig")
    assert builds == 1

    with pytest.raises(FileExistsError, match="already exists"):
        eval_ablation_v2_enterprise.main(args)
    assert builds == 1


def test_ablation_parser_has_no_force_flag() -> None:
    parser = eval_ablation_v2_enterprise.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}
    assert "--force" not in options
