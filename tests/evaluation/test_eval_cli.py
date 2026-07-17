from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.contracts import EvaluationRunResult
from scripts import eval_enterprise_v2


def case_payload() -> dict:
    return {
        "case_id": "case-one",
        "question": "Policy A 的规则是什么？",
        "task_type": "fact_lookup",
        "answer_mode": "answered",
        "user_context": {
            "user_id": "employee-one",
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
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    payload = json.dumps([case_payload()], ensure_ascii=False).encode("utf-8")
    (eval_dir / "dev.json").write_bytes(payload)
    (eval_dir / "test.json").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (eval_dir / "test_manifest.sha256").write_text(
        f"{digest}  test.json\n",
        encoding="utf-8",
    )
    return corpus, eval_dir


def test_help_has_no_filesystem_side_effect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        eval_enterprise_v2.main(["--help"])

    assert exc.value.code == 0
    assert list(tmp_path.iterdir()) == []


def test_frozen_hash_parser_accepts_standard_manifest_and_detects_change(
    tmp_path: Path,
) -> None:
    _, eval_dir = write_inputs(tmp_path)
    expected, actual = eval_enterprise_v2.verify_frozen_test_hash(eval_dir)
    assert expected == actual

    (eval_dir / "test.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen test hash mismatch"):
        eval_enterprise_v2.verify_frozen_test_hash(eval_dir)


def test_test_hash_mismatch_fails_before_runtime_construction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    corpus, eval_dir = write_inputs(tmp_path)
    (eval_dir / "test.json").write_text("[]", encoding="utf-8")
    called = False

    def should_not_build(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("runtime must not be constructed")

    monkeypatch.setattr(
        eval_enterprise_v2,
        "build_deterministic_runtime",
        should_not_build,
    )
    with pytest.raises(ValueError, match="frozen test hash mismatch"):
        eval_enterprise_v2.main(
            [
                "--suite",
                "all",
                "--split",
                "test",
                "--run-id",
                "run-test",
                "--corpus-dir",
                str(corpus),
                "--eval-dir",
                str(eval_dir),
                "--out-dir",
                str(tmp_path / "runs"),
            ]
        )
    assert called is False


def test_dev_cli_publishes_once_and_refuses_existing_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    corpus, eval_dir = write_inputs(tmp_path)
    calls = 0
    runtime = SimpleNamespace(
        mode="deterministic",
        variant="fake-runtime",
        index_root=tmp_path / "missing-index",
        metadata=lambda: {"variant": "fake-runtime", "model_calls": 0},
    )

    def build_runtime(*args, **kwargs):
        nonlocal calls
        calls += 1
        return runtime

    def fake_evaluate(cases, active_runtime, **kwargs):
        return EvaluationRunResult(
            run_id=kwargs["run_id"],
            suite=kwargs["suite"],
            split=kwargs["split"],
            mode=active_runtime.mode,
            case_count=0,
            summary={"overall_case_pass": {"passed": 0, "total": 0, "rate": None}},
            details=[],
            config={"top_k": kwargs["top_k"]},
        )

    monkeypatch.setattr(
        eval_enterprise_v2,
        "build_deterministic_runtime",
        build_runtime,
    )
    monkeypatch.setattr(eval_enterprise_v2, "evaluate_suite", fake_evaluate)
    args = [
        "--suite",
        "all",
        "--split",
        "dev",
        "--run-id",
        "run-dev",
        "--corpus-dir",
        str(corpus),
        "--eval-dir",
        str(eval_dir),
        "--out-dir",
        str(tmp_path / "runs"),
    ]

    assert eval_enterprise_v2.main(args) == 0
    output = tmp_path / "runs" / "run-dev"
    assert (output / "manifest.json").is_file()
    assert (output / "summary.json").is_file()
    assert calls == 1

    with pytest.raises(FileExistsError, match="already exists"):
        eval_enterprise_v2.main(args)
    assert calls == 1


def test_parser_does_not_expose_force_flag() -> None:
    parser = eval_enterprise_v2.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}
    assert "--force" not in options
