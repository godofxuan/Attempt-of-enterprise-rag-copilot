from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.contracts import (
    EvaluationCaseResult,
    EvaluationRunResult,
    LayerResult,
)
from app.evaluation.human_review import HUMAN_JUDGEMENT_FIELDS
from scripts import generate_human_review_v2


def case_payload(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "question": f"Question for {case_id}",
        "task_type": "fact_lookup",
        "answer_mode": "answered",
        "user_context": {
            "user_id": "employee",
            "tenant": "tenant-one",
            "region": "cn",
            "groups": ["employees"],
        },
        "required_fact_ids": [f"fact-{case_id}"],
        "gold_doc_ids": [f"doc-{case_id}"],
        "distractor_doc_ids": [],
        "forbidden_doc_ids": [],
        "expected_answer": "answer",
        "expected_filters": {},
        "expected_authority_doc_ids": [f"doc-{case_id}"],
        "tags": ["current"],
    }


def write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text(
        json.dumps(
            {
                "profile_id": "demo",
                "generator_version": "test",
                "document_count": 2,
            }
        ),
        encoding="utf-8",
    )
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    dev = json.dumps([case_payload("dev-one")]).encode("utf-8")
    test = json.dumps([case_payload("test-one")]).encode("utf-8")
    (eval_dir / "dev.json").write_bytes(dev)
    (eval_dir / "test.json").write_bytes(test)
    (eval_dir / "test_manifest.sha256").write_text(
        f"{hashlib.sha256(test).hexdigest()}  test.json\n",
        encoding="utf-8",
    )
    return corpus, eval_dir


def test_human_review_cli_writes_one_blank_combined_sheet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    corpus, eval_dir = write_inputs(tmp_path)
    runtime = SimpleNamespace(
        mode="deterministic",
        variant="fake-runtime",
        index_root=tmp_path / "missing-index",
        metadata=lambda: {"variant": "fake-runtime", "model_calls": 0},
    )
    monkeypatch.setattr(
        generate_human_review_v2,
        "build_deterministic_runtime",
        lambda *args, **kwargs: runtime,
    )

    def fake_evaluate(cases, active_runtime, **kwargs):
        sink = kwargs["response_sink"]
        details = []
        for case in cases:
            sink[case.case_id] = f"System answer for {case.case_id}"
            details.append(
                EvaluationCaseResult(
                    case_id=case.case_id,
                    task_type=case.task_type,
                    expected_mode=case.answer_mode,
                    actual_mode="answered",
                    passed=True,
                    visible_doc_ids=case.gold_doc_ids,
                    layers=[
                        LayerResult(
                            layer="answer",
                            applicable=True,
                            passed=True,
                            metrics={"correctness": True},
                        )
                    ],
                    latency_ms=1.0,
                    model_calls=0,
                    tool_calls=1,
                    context_chars=100,
                )
            )
        return EvaluationRunResult(
            run_id=kwargs["run_id"],
            suite="all",
            split="regression",
            mode=active_runtime.mode,
            case_count=len(details),
            summary={},
            details=details,
        )

    monkeypatch.setattr(generate_human_review_v2, "evaluate_suite", fake_evaluate)
    args = [
        "--run-id",
        "human-review-one",
        "--corpus-dir",
        str(corpus),
        "--eval-dir",
        str(eval_dir),
        "--out-dir",
        str(tmp_path / "runs"),
    ]

    assert generate_human_review_v2.main(args) == 0
    output = tmp_path / "runs" / "human-review-one"
    with (output / "human_review.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {row["case_id"] for row in rows} == {"dev-one", "test-one"}
    assert all(row[field] == "" for row in rows for field in HUMAN_JUDGEMENT_FIELDS)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["suite"] == "human_review"
    assert manifest["split"] == "regression"


def test_human_review_help_has_no_side_effect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        generate_human_review_v2.main(["--help"])
    assert exc.value.code == 0
    assert list(tmp_path.iterdir()) == []
