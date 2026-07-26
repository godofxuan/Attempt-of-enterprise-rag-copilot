from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.eval_agent_v2_dev as evaluator
from app import filesystem as filesystem_module
from app.corpus.schemas import EvalCase
from app.domain.agent import AgentBudget
from app.domain.evidence import (
    AnswerResponse,
    AnswerSource,
    Claim,
    ClaimCitation,
)


def eval_case(
    *,
    case_id: str,
    task_type: str,
    answer_mode: str,
    gold_doc_ids: list[str] | None = None,
    forbidden_doc_ids: list[str] | None = None,
) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        question=f"question for {case_id}",
        task_type=task_type,
        answer_mode=answer_mode,
        user_context={
            "user_id": "employee-one",
            "tenant": "tenant-one",
            "region": "cn",
            "groups": ["employees"],
        },
        required_fact_ids=[],
        gold_doc_ids=gold_doc_ids or [],
        forbidden_doc_ids=forbidden_doc_ids or [],
        tags=["test"],
    )


def complete_trace(*, tools: list[str], steps: int) -> dict:
    budget = {
        "search_calls": sum(tool == "search" for tool in tools),
        "find_calls": sum(tool == "find" for tool in tools),
        "open_calls": sum(tool == "open" for tool in tools),
        "steps": steps,
        "context_chars": 100 if steps else 0,
    }
    return {
        "intent": "comparison" if len(tools) > 1 else "fact",
        "analysis_source": "rules",
        "required_aspect_count": max(1, len(tools)),
        "steps": [
            {
                "sequence": index,
                "tool": tool,
                "status": "ok" if tool in {"search", "find", "open"} else "terminal",
                "latency_ms": 1.0,
                "visible_count": 1 if tool == "search" else 0,
                "context_chars_added": 10 if tool == "search" else 0,
                "error_code": None,
                "budget": budget,
            }
            for index, tool in enumerate(tools, start=1)
        ],
        "stop_reason": "completed",
        "budget": budget,
    }


def answered_response(doc_ids: list[str]) -> AnswerResponse:
    claims = []
    citations = []
    sources = []
    for index, doc_id in enumerate(doc_ids, start=1):
        chunk_id = f"{doc_id}::chunk"
        claims.append(
            Claim(
                claim_id=f"claim-{index}",
                text=f"Supported fact for {doc_id}",
                cited_chunk_ids=[chunk_id],
            )
        )
        citations.append(
            ClaimCitation(
                claim_id=f"claim-{index}",
                cited_chunk_ids=[chunk_id],
                citation_present=True,
                references_visible_evidence=True,
                lexical_support=1.0,
                supported=True,
            )
        )
        sources.append(
            AnswerSource(
                doc_id=doc_id,
                source_path=f"documents/{doc_id}.md",
                section_path=["Policy"],
                chunk_id=chunk_id,
                preview="Visible supported preview",
            )
        )
    return AnswerResponse(
        mode="answered",
        answer="Grounded answer",
        claims=claims,
        citations=citations,
        sources=sources,
        stop_reason="completed",
        trace=complete_trace(tools=["search", "search", "answer"], steps=2),
    )


def source_free_response(mode: str) -> AnswerResponse:
    stop_reasons = {
        "permission": "permission",
        "not_found": "not_found",
        "unsafe": "unsafe",
    }
    tools = ["refuse"] if mode == "unsafe" else ["search", "stop"]
    trace = complete_trace(tools=tools, steps=0 if mode == "unsafe" else 1)
    trace["stop_reason"] = stop_reasons[mode]
    if mode == "unsafe":
        trace["budget"] = {
            "search_calls": 0,
            "find_calls": 0,
            "open_calls": 0,
            "steps": 0,
            "context_chars": 0,
        }
    return AnswerResponse(
        mode=mode,
        answer=f"{mode} response",
        stop_reason=stop_reasons[mode],
        trace=trace,
    )


def test_behavior_metrics_keep_denominators_and_safe_details() -> None:
    cases = [
        eval_case(
            case_id="comparison-one",
            task_type="comparison",
            answer_mode="answered",
            gold_doc_ids=["doc-a", "doc-b"],
        ),
        eval_case(
            case_id="permission-one",
            task_type="permission",
            answer_mode="permission",
            forbidden_doc_ids=["forbidden-secret-doc"],
        ),
        eval_case(
            case_id="missing-one",
            task_type="no_answer",
            answer_mode="not_found",
        ),
    ]
    responses = {
        "comparison-one": answered_response(["doc-a", "doc-b"]),
        "permission-one": source_free_response("permission"),
        "missing-one": source_free_response("not_found"),
        evaluator.UNSAFE_PROBE_ID: source_free_response("unsafe"),
    }

    result = evaluator.evaluate_cases(
        cases,
        run_case=lambda case: responses[case.case_id],
        run_unsafe_probe=lambda user: responses[evaluator.UNSAFE_PROBE_ID],
        budget=AgentBudget(),
    )

    metrics = result["metrics"]
    assert metrics["outcome_accuracy"] == {"passed": 3, "total": 3, "rate": 1.0}
    assert metrics["comparison_full_coverage_rate"] == {
        "passed": 1,
        "total": 1,
        "rate": 1.0,
    }
    assert metrics["permission_zero_source_rate"]["rate"] == 1.0
    assert metrics["unsafe_zero_tool_rate"] == {"passed": 1, "total": 1, "rate": 1.0}
    assert metrics["budget_compliance_rate"]["rate"] == 1.0
    assert metrics["trace_complete_rate"]["rate"] == 1.0
    assert metrics["citation_presence_rate"]["total"] == 2
    assert metrics["citation_visible_correctness_rate"]["rate"] == 1.0
    assert result["failure_count"] == 0
    serialized_details = json.dumps(result["details"])
    assert "question for" not in serialized_details
    assert "Visible supported preview" not in serialized_details
    assert "forbidden-secret-doc" not in serialized_details


def test_failure_details_explain_outcome_coverage_and_permission_leak() -> None:
    cases = [
        eval_case(
            case_id="comparison-bad",
            task_type="comparison",
            answer_mode="answered",
            gold_doc_ids=["doc-a", "doc-b"],
        ),
        eval_case(
            case_id="permission-bad",
            task_type="permission",
            answer_mode="permission",
            forbidden_doc_ids=["doc-a"],
        ),
    ]
    bad_answer = answered_response(["doc-a"])
    responses = {
        "comparison-bad": bad_answer,
        "permission-bad": bad_answer,
        evaluator.UNSAFE_PROBE_ID: source_free_response("unsafe"),
    }

    result = evaluator.evaluate_cases(
        cases,
        run_case=lambda case: responses[case.case_id],
        run_unsafe_probe=lambda user: responses[evaluator.UNSAFE_PROBE_ID],
        budget=AgentBudget(),
    )

    failures = {row["case_id"]: row["failure_reasons"] for row in result["failures"]}
    assert "comparison_gold_not_fully_covered" in failures["comparison-bad"]
    assert "wrong_answer_mode" in failures["permission-bad"]
    assert "permission_returned_sources" in failures["permission-bad"]
    assert "forbidden_source_exposed" in failures["permission-bad"]


def sample_result() -> dict:
    return {
        "schema_version": "agent_v2_dev_eval_v1",
        "producer": "enterprise_agentic_rag_v2",
        "config": {"split": "dev", "mode": "deterministic"},
        "metrics": {"outcome_accuracy": {"passed": 1, "total": 1, "rate": 1.0}},
        "case_count": 1,
        "failure_count": 0,
        "failures": [],
        "details": [{"case_id": "one", "failure_reasons": []}],
        "security_probes": [],
    }


def test_writer_creates_new_run_directory_and_refuses_overwrite(tmp_path: Path) -> None:
    output_dir = tmp_path / "agent-run"

    paths = evaluator.write_results(output_dir, sample_result())

    assert set(paths) == {"summary", "details", "run_manifest"}
    assert json.loads(paths["summary"].read_text(encoding="utf-8"))["case_count"] == 1
    assert json.loads(paths["details"].read_text(encoding="utf-8"))["details"][0]["case_id"] == "one"
    manifest = json.loads(paths["run_manifest"].read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "agent_v2_eval_run_manifest_v1"
    assert set(manifest["artifacts"]) == {"summary.json", "details.json"}

    with pytest.raises(FileExistsError, match="already exists"):
        evaluator.write_results(output_dir, sample_result())


def test_writer_retries_transient_windows_directory_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "retry-run"
    original_move = filesystem_module._move_once
    calls = 0

    def flaky_rename(
        path: Path,
        target: Path,
        *,
        replace: bool,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            error = PermissionError(13, "transient access denied")
            error.winerror = 5
            raise error
        return original_move(path, target, replace=replace)

    monkeypatch.setattr(filesystem_module, "_move_once", flaky_rename)
    monkeypatch.setattr(filesystem_module.time, "sleep", lambda _: None)

    paths = evaluator.write_results(output_dir, sample_result())

    assert 2 <= calls <= filesystem_module._WINDOWS_DIRECTORY_MOVE_ATTEMPTS
    assert paths["summary"].is_file()


def test_cli_defaults_to_deterministic_stdout_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured_args = {}

    def fake_evaluate(input_dir, **kwargs):
        captured_args.update(input_dir=input_dir, **kwargs)
        return sample_result()

    monkeypatch.setattr(evaluator, "evaluate_dev", fake_evaluate)

    code = evaluator.main(["--input-dir", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 0
    assert json.loads(captured.out) == sample_result()
    assert captured.err == ""
    assert captured_args["mode"] == "deterministic"
    assert list(tmp_path.iterdir()) == []


def test_load_dev_cases_uses_dev_json_array(tmp_path: Path) -> None:
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    case = eval_case(
        case_id="dev-only",
        task_type="fact_lookup",
        answer_mode="answered",
        gold_doc_ids=["doc-a"],
    )
    (eval_dir / "dev.json").write_text(
        json.dumps([case.model_dump(mode="json")]),
        encoding="utf-8",
    )
    (eval_dir / "test.json").write_text("not valid json", encoding="utf-8")

    path, loaded = evaluator.load_dev_cases(tmp_path)

    assert path.name == "dev.json"
    assert [item.case_id for item in loaded] == ["dev-only"]
