from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.corpus.schemas import EvalCase
from scripts import eval_chunking_ablation as ablation


ROOT = Path(__file__).resolve().parents[2]
DEMO_CORPUS = ROOT / "data" / "generated" / "demo"


def eval_case(
    case_id: str,
    *,
    task_type: str = "fact_lookup",
    answer_mode: str = "answered",
    gold_doc_ids: list[str] | None = None,
) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        question=f"question for {case_id}",
        task_type=task_type,
        answer_mode=answer_mode,
        user_context={
            "user_id": "user-one",
            "tenant": "tenant-one",
            "region": "cn",
            "groups": ["all_employees"],
        },
        gold_doc_ids=gold_doc_ids or [],
        tags=["test"],
    )


def sample_result() -> dict[str, object]:
    return {
        "schema_version": "chunking_ablation_v1",
        "producer": "enterprise_agentic_rag_v2",
        "config": {"split": "dev", "top_k": 5},
        "scored_case_count": 1,
        "modes": {
            "fixed": {
                "chunk_counts": {"total": 1, "indexable": 1},
                "metrics": {
                    "case_count": 1,
                    "hit_at_k": 1.0,
                    "recall_at_k": 1.0,
                    "mrr": 1.0,
                },
                "by_task": {},
                "failure_count": 0,
                "failures": [],
                "details": [],
            }
        },
    }


def test_only_answered_cases_with_gold_docs_are_scored() -> None:
    cases = [
        eval_case("answered", gold_doc_ids=["doc-a"]),
        eval_case("permission", answer_mode="permission"),
        eval_case("not-found", answer_mode="not_found"),
        eval_case("answered-without-gold"),
    ]

    selected = ablation.select_scored_cases(cases)

    assert [case.case_id for case in selected] == ["answered"]


def test_partial_multidoc_recall_is_a_failure_even_when_hit_is_one() -> None:
    metrics = ablation.score_retrieved_documents(
        gold_doc_ids=["doc-a", "doc-b"],
        retrieved_doc_ids=["doc-b", "doc-c", "doc-d"],
        top_k=3,
    )

    assert metrics == {
        "hit_at_k": 1.0,
        "recall_at_k": 0.5,
        "reciprocal_rank": 1.0,
        "full_recall": 0.0,
        "missed_gold_doc_ids": ["doc-a"],
    }


def test_summary_reports_metrics_and_failures_per_task() -> None:
    rows = [
        {
            "case_id": "fact-ok",
            "task_type": "fact_lookup",
            "hit_at_k": 1.0,
            "recall_at_k": 1.0,
            "reciprocal_rank": 1.0,
            "full_recall": 1.0,
            "missed_gold_doc_ids": [],
        },
        {
            "case_id": "compare-partial",
            "task_type": "comparison",
            "hit_at_k": 1.0,
            "recall_at_k": 0.5,
            "reciprocal_rank": 0.5,
            "full_recall": 0.0,
            "missed_gold_doc_ids": ["doc-b"],
        },
    ]

    summary = ablation.summarize_rows(rows)
    by_task = ablation.summarize_by_task(rows)

    assert summary["case_count"] == 2
    assert summary["hit_at_k"] == 1.0
    assert summary["recall_at_k"] == 0.75
    assert summary["mrr"] == 0.75
    assert summary["full_recall_rate"] == 0.5
    assert summary["failure_count"] == 1
    assert by_task["fact_lookup"]["failure_count"] == 0
    assert by_task["comparison"]["failure_count"] == 1


def test_real_demo_ablation_uses_same_dev_scope_and_reports_all_modes() -> None:
    result = ablation.evaluate_ablation(DEMO_CORPUS, top_k=5)

    assert result["config"]["split"] == "dev"
    assert result["config"]["top_k"] == 5
    assert result["config"]["tokenizer"] == "jieba"
    assert result["scored_case_count"] == 18
    assert set(result["modes"]) == {"fixed", "heading", "parent_child"}
    assert result["source_document_count"] == 72
    assert result["canonical_document_count"] == 64
    assert result["modes"]["fixed"]["chunk_counts"]["indexable"] == 64
    for mode in result["modes"].values():
        assert mode["metrics"]["case_count"] == 18
        assert len(mode["details"]) == 18
        assert set(mode["by_task"]) == {
            "comparison",
            "completeness",
            "fact_lookup",
            "version_conflict",
        }
    json.dumps(result, ensure_ascii=False)


def test_result_writer_creates_new_directory_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "ablation-run"
    result = sample_result()

    paths = ablation.write_ablation_results(output_dir, result)

    assert paths == {
        "summary": output_dir / "summary.json",
        "details": output_dir / "details.json",
    }
    assert json.loads(paths["summary"].read_text(encoding="utf-8"))[
        "scored_case_count"
    ] == 1
    assert json.loads(paths["details"].read_text(encoding="utf-8"))["modes"][
        "fixed"
    ]["details"] == []

    with pytest.raises(FileExistsError, match="already exists"):
        ablation.write_ablation_results(output_dir, result)


def test_cli_without_output_prints_json_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = sample_result()
    monkeypatch.setattr(ablation, "evaluate_ablation", lambda *args, **kwargs: result)

    exit_code = ablation.main(["--input-dir", str(tmp_path), "--top-k", "5"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == result
    assert captured.err == ""
    assert list(tmp_path.iterdir()) == []


def test_cli_explicit_output_refuses_second_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = sample_result()
    output_dir = tmp_path / "run-one"
    monkeypatch.setattr(ablation, "evaluate_ablation", lambda *args, **kwargs: result)
    args = [
        "--input-dir",
        str(tmp_path),
        "--output-dir",
        str(output_dir),
    ]

    first_code = ablation.main(args)
    first = capsys.readouterr()
    second_code = ablation.main(args)
    second = capsys.readouterr()

    assert first_code == 0, first.err
    assert json.loads(first.out)["written"] is True
    assert second_code == 2
    assert "already exists" in second.err
    assert (output_dir / "summary.json").is_file()
