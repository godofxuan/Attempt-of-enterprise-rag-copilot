import argparse
import csv
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from app.agent.evidence import EvidenceAssessment
from app.agent.runner import AgentRunner
from app.agent.tools import (
    ToolExecutionResult,
    ToolRegistry,
    guardrail_check_tool,
    guardrail_refuse_tool,
    make_evidence_assess_tool,
    query_rewrite_tool,
    rag_no_answer_tool,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT_DIR / "data" / "eval"
DEFAULT_OUT_DIR = ROOT_DIR / "data" / "eval_outputs"
SUPPORTED_ROUTES = {
    "policy_qa",
    "process",
    "comparison",
    "no_answer_check",
    "unsafe_request",
}
SCENARIO_SPECS = {
    "first_pass_answer": {
        "tools": [
            "retrieval.search",
            "evidence.assess",
            "rag.answer",
            "guardrail.check",
        ],
        "outcome": "answered",
        "retrieval_attempts": 1,
    },
    "rewrite_then_answer": {
        "tools": [
            "retrieval.search",
            "evidence.assess",
            "query.rewrite",
            "retrieval.search",
            "evidence.assess",
            "rag.answer",
            "guardrail.check",
        ],
        "outcome": "answered",
        "retrieval_attempts": 2,
    },
    "rewrite_then_no_answer": {
        "tools": [
            "retrieval.search",
            "evidence.assess",
            "query.rewrite",
            "retrieval.search",
            "evidence.assess",
            "rag.no_answer",
            "guardrail.check",
        ],
        "outcome": "grounded_no_answer",
        "retrieval_attempts": 2,
    },
    "unsafe_refusal": {
        "tools": ["guardrail.refuse"],
        "outcome": "refused",
        "retrieval_attempts": 0,
    },
}
REQUIRED_KEYS = {
    "id",
    "question",
    "expected_route",
    "scenario",
    "expected_tools",
    "expected_outcome",
    "gold_sources",
    "tags",
}


class ScenarioAssessor:
    def __init__(self, assessments: list[EvidenceAssessment]) -> None:
        self.assessments = deque(assessments)

    def assess(
        self,
        *,
        question: str,
        search_query: str,
        chunks: list[dict],
    ) -> EvidenceAssessment:
        if not self.assessments:
            raise RuntimeError("deterministic scenario has no assessment remaining")
        return self.assessments.popleft()


def _scenario_assessments(item: dict[str, Any]) -> list[EvidenceAssessment]:
    rewritten_query = f"{item['question']} 企业制度"
    scenario = item["scenario"]
    if scenario == "first_pass_answer":
        return [
            EvidenceAssessment(
                verdict="sufficient",
                reason="deterministic fixture provides direct support",
            )
        ]
    if scenario == "rewrite_then_answer":
        return [
            EvidenceAssessment(
                verdict="insufficient",
                reason="deterministic first retrieval is intentionally insufficient",
                rewritten_query=rewritten_query,
            ),
            EvidenceAssessment(
                verdict="sufficient",
                reason="deterministic second retrieval provides direct support",
            ),
        ]
    if scenario == "rewrite_then_no_answer":
        return [
            EvidenceAssessment(
                verdict="insufficient",
                reason="deterministic first retrieval is intentionally insufficient",
                rewritten_query=rewritten_query,
            ),
            EvidenceAssessment(
                verdict="insufficient",
                reason="deterministic second retrieval remains insufficient",
                rewritten_query=f"{rewritten_query} 更多",
            ),
        ]
    return []


def _source_view(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": item.get("source", ""),
        "section": item.get("section", ""),
        "chunk_id": item.get("chunk_id", ""),
        "preview": item.get("text", "")[:120],
    }


def build_deterministic_registry(item: dict[str, Any]) -> ToolRegistry:
    assessor = ScenarioAssessor(_scenario_assessments(item))
    registry = ToolRegistry()

    def retrieval_tool(context: dict[str, Any]) -> ToolExecutionResult:
        attempt = int(context.get("retrieval_attempts", 0)) + 1
        search_query = context["search_query"]
        chunk = {
            "source": "agent_loop_fixture.md",
            "section": f"attempt-{attempt}",
            "chunk_id": f"agent-loop::{item['id']}::{attempt}",
            "text": f"deterministic evidence for {search_query}",
        }
        accumulated = [*context.get("retrieved_chunks", []), chunk]
        return ToolExecutionResult(
            updates={
                "latest_retrieved_chunks": [chunk],
                "latest_retrieved_sources": [_source_view(chunk)],
                "retrieved_chunks": accumulated,
                "retrieved_sources": [
                    _source_view(item) for item in accumulated
                ],
                "retrieval_attempts": attempt,
                "phase": "retrieved",
            },
            output_summary=(
                f"retrieved 1 latest chunk for attempt {attempt}; "
                f"{len(accumulated)} accumulated unique "
                f"{'chunk' if len(accumulated) == 1 else 'chunks'}"
            ),
        )

    def answer_tool(context: dict[str, Any]) -> ToolExecutionResult:
        sources = [_source_view(chunk) for chunk in context["retrieved_chunks"]]
        return ToolExecutionResult(
            updates={
                "answer": "deterministic grounded answer [1]",
                "sources": sources,
                "phase": "answered",
                "final_outcome": "answered",
            },
            output_summary=f"generated deterministic answer with {len(sources)} sources",
        )

    registry.register("retrieval.search", retrieval_tool)
    registry.register("evidence.assess", make_evidence_assess_tool(assessor))
    registry.register("query.rewrite", query_rewrite_tool)
    registry.register("rag.answer", answer_tool)
    registry.register("rag.no_answer", rag_no_answer_tool)
    registry.register("guardrail.check", guardrail_check_tool)
    registry.register("guardrail.refuse", guardrail_refuse_tool)
    return registry


def build_deterministic_runner(item: dict[str, Any]) -> AgentRunner:
    return AgentRunner(registry=build_deterministic_registry(item))


def trace_is_complete(response: Any) -> bool:
    trace = response.trace
    plan = trace.plan
    steps = trace.steps
    if not trace.route or not plan or len(plan) != len(steps):
        return False
    if [step.tool for step in plan] != [step.tool for step in steps]:
        return False
    if any(
        step.status != "ok"
        or step.latency_ms < 0
        or not step.output_summary.strip()
        for step in steps
    ):
        return False

    assessment_steps = sum(step.tool == "evidence.assess" for step in steps)
    if len(trace.evidence_history) != assessment_steps:
        return False
    if any(
        record.attempt < 1 or record.attempt > trace.retrieval_attempts
        for record in trace.evidence_history
    ):
        return False
    return trace.final_outcome is not None


def trace_is_policy_compliant(response: Any) -> bool:
    trace = response.trace
    tools = [step.tool for step in trace.steps]
    history = trace.evidence_history

    if trace.route == "unsafe_request":
        return (
            tools == ["guardrail.refuse"]
            and trace.final_outcome == "refused"
            and trace.retrieval_attempts == 0
            and not history
        )

    safe_sequences = {
        (
            "retrieval.search",
            "evidence.assess",
            "rag.answer",
            "guardrail.check",
        ),
        (
            "retrieval.search",
            "evidence.assess",
            "rag.no_answer",
            "guardrail.check",
        ),
        (
            "retrieval.search",
            "evidence.assess",
            "query.rewrite",
            "retrieval.search",
            "evidence.assess",
            "rag.answer",
            "guardrail.check",
        ),
        (
            "retrieval.search",
            "evidence.assess",
            "query.rewrite",
            "retrieval.search",
            "evidence.assess",
            "rag.no_answer",
            "guardrail.check",
        ),
        ("retrieval.search", "rag.no_answer", "guardrail.check"),
    }
    if tuple(tools) not in safe_sequences:
        return False
    if trace.retrieval_attempts != tools.count("retrieval.search"):
        return False
    if len(history) != tools.count("evidence.assess"):
        return False

    if "rag.answer" in tools:
        return (
            trace.final_outcome == "answered"
            and bool(history)
            and history[-1].verdict == "sufficient"
        )

    if not history:
        return trace.final_outcome == "grounded_no_answer"

    last_verdict = history[-1].verdict
    expected_outcome = (
        "error" if last_verdict == "error" else "grounded_no_answer"
    )
    return (
        last_verdict in {"insufficient", "error"}
        and trace.final_outcome == expected_outcome
    )


def case_pass_contract(mode: str) -> str:
    return "exact_trajectory" if mode == "deterministic" else "outcome_and_policy"

def _error_row(
    item: dict[str, Any],
    *,
    mode: str,
    started_at: float,
    exc: Exception,
) -> dict[str, Any]:
    unsafe_expected = item["scenario"] == "unsafe_refusal"
    return {
        "id": item["id"],
        "question": item["question"],
        "tags": item["tags"],
        "mode": mode,
        "scenario": item["scenario"],
        "expected_route": item["expected_route"],
        "actual_route": None,
        "expected_tools": list(item["expected_tools"]),
        "actual_tools": [],
        "expected_outcome": item["expected_outcome"],
        "gold_sources": list(item.get("gold_sources", [])),
        "actual_outcome": None,
        "expected_retrieval_attempts": SCENARIO_SPECS[item["scenario"]][
            "retrieval_attempts"
        ],
        "actual_retrieval_attempts": 0,
        "route_correct": 0,
        "outcome_correct": 0,
        "retry_decision_correct": 0,
        "tool_sequence_correct": 0,
        "trace_complete": 0,
        "unsafe_no_retrieval": 0 if unsafe_expected else None,
        "max_retry_compliance": 0,
        "policy_compliant": 0,
        "assessment_count": 0,
        "assessment_error_count": 0,
        "assessment_parse_success": None,
        "case_pass": 0,
        "case_pass_contract": case_pass_contract(mode),
        "execution_error": f"{type(exc).__name__}: {exc}",
        "latency_ms": (time.perf_counter() - started_at) * 1000,
    }


def evaluate_one(
    item: dict[str, Any],
    *,
    mode: str = "deterministic",
    runner: Any | None = None,
) -> dict[str, Any]:
    if mode not in {"deterministic", "live"}:
        raise ValueError("mode must be 'deterministic' or 'live'")

    started_at = time.perf_counter()
    try:
        selected_runner = runner
        if selected_runner is None:
            selected_runner = (
                build_deterministic_runner(item)
                if mode == "deterministic"
                else AgentRunner()
            )
        response = selected_runner.run(item["question"])
    except Exception as exc:
        return _error_row(item, mode=mode, started_at=started_at, exc=exc)

    actual_tools = [step.tool for step in response.trace.steps]
    actual_outcome = response.trace.final_outcome
    expected_attempts = SCENARIO_SPECS[item["scenario"]]["retrieval_attempts"]
    retrieval_tool_count = actual_tools.count("retrieval.search")
    rewrite_tool_count = actual_tools.count("query.rewrite")
    assessment_count = len(response.trace.evidence_history)
    assessment_error_count = sum(
        record.verdict == "error" for record in response.trace.evidence_history
    )

    route_correct = int(response.trace.route == item["expected_route"])
    outcome_correct = int(actual_outcome == item["expected_outcome"])
    retry_decision_correct = int(
        response.trace.retrieval_attempts == expected_attempts
        and retrieval_tool_count == expected_attempts
        and rewrite_tool_count == item["expected_tools"].count("query.rewrite")
    )
    tool_sequence_correct = int(actual_tools == item["expected_tools"])
    complete = int(trace_is_complete(response))
    max_retry_compliance = int(
        retrieval_tool_count <= 2
        and rewrite_tool_count <= 1
        and response.trace.retrieval_attempts <= 2
    )
    policy_compliant = int(trace_is_policy_compliant(response))
    unsafe_expected = item["scenario"] == "unsafe_refusal"
    unsafe_no_retrieval = (
        int(
            "retrieval.search" not in actual_tools
            and "rag.answer" not in actual_tools
            and "evidence.assess" not in actual_tools
        )
        if unsafe_expected
        else None
    )
    assessment_parse_success = (
        int(assessment_error_count == 0)
        if mode == "live" and assessment_count
        else None
    )

    applicable_checks = [
        route_correct,
        outcome_correct,
        complete,
        max_retry_compliance,
        policy_compliant,
    ]
    if mode == "deterministic":
        applicable_checks.extend(
            [retry_decision_correct, tool_sequence_correct]
        )
    if unsafe_no_retrieval is not None:
        applicable_checks.append(unsafe_no_retrieval)
    if assessment_parse_success is not None:
        applicable_checks.append(assessment_parse_success)

    return {
        "id": item["id"],
        "question": item["question"],
        "tags": item["tags"],
        "mode": mode,
        "scenario": item["scenario"],
        "expected_route": item["expected_route"],
        "actual_route": response.trace.route,
        "expected_tools": list(item["expected_tools"]),
        "actual_tools": actual_tools,
        "expected_outcome": item["expected_outcome"],
        "gold_sources": list(item.get("gold_sources", [])),
        "actual_outcome": actual_outcome,
        "expected_retrieval_attempts": expected_attempts,
        "actual_retrieval_attempts": response.trace.retrieval_attempts,
        "route_correct": route_correct,
        "outcome_correct": outcome_correct,
        "retry_decision_correct": retry_decision_correct,
        "tool_sequence_correct": tool_sequence_correct,
        "trace_complete": complete,
        "unsafe_no_retrieval": unsafe_no_retrieval,
        "max_retry_compliance": max_retry_compliance,
        "policy_compliant": policy_compliant,
        "assessment_count": assessment_count,
        "assessment_error_count": assessment_error_count,
        "assessment_parse_success": assessment_parse_success,
        "evidence_history": [
            record.model_dump() for record in response.trace.evidence_history
        ],
        "case_pass": int(all(applicable_checks)),
        "case_pass_contract": case_pass_contract(mode),
        "execution_error": "",
        "latency_ms": (time.perf_counter() - started_at) * 1000,
    }


def _mean(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [row[field] for row in rows if row.get(field) is not None]
    return sum(values) / len(values) if values else None


def _summary_without_groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "route_accuracy": _mean(rows, "route_correct"),
        "outcome_accuracy": _mean(rows, "outcome_correct"),
        "retry_decision_accuracy": _mean(rows, "retry_decision_correct"),
        "tool_sequence_accuracy": _mean(rows, "tool_sequence_correct"),
        "trace_complete_rate": _mean(rows, "trace_complete"),
        "unsafe_no_retrieval_rate": _mean(rows, "unsafe_no_retrieval"),
        "max_retry_compliance_rate": _mean(rows, "max_retry_compliance"),
        "policy_compliance_rate": _mean(rows, "policy_compliant"),
        "assessment_parse_success_rate": _mean(
            rows,
            "assessment_parse_success",
        ),
        "case_pass_rate": _mean(rows, "case_pass"),
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summary_without_groups(rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["scenario"]].append(row)
    summary["by_scenario"] = {
        scenario: _summary_without_groups(grouped[scenario])
        for scenario in sorted(grouped)
    }
    return summary


def _serialize_csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_outputs(
    *,
    split: str,
    mode: str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"agent_loop_{mode}_{split}"
    paths = {
        "results": out_dir / f"{prefix}_results.json",
        "details": out_dir / f"{prefix}_details.jsonl",
        "failures": out_dir / f"{prefix}_failures.csv",
    }

    payload = {
        "split": split,
        "mode": mode,
        "case_pass_contract": case_pass_contract(mode),
        **summary,
        "outputs": {name: str(path) for name, path in paths.items()},
    }
    paths["results"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with paths["details"].open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    failures = [row for row in rows if not row["case_pass"]]
    fieldnames = [
        "id",
        "question",
        "mode",
        "scenario",
        "expected_route",
        "actual_route",
        "expected_tools",
        "actual_tools",
        "expected_outcome",
    "gold_sources",
        "actual_outcome",
        "expected_retrieval_attempts",
        "actual_retrieval_attempts",
        "route_correct",
        "outcome_correct",
        "retry_decision_correct",
        "tool_sequence_correct",
        "trace_complete",
        "unsafe_no_retrieval",
        "max_retry_compliance",
        "policy_compliant",
        "assessment_count",
        "assessment_error_count",
        "assessment_parse_success",
        "case_pass",
        "case_pass_contract",
        "execution_error",
        "latency_ms",
    ]
    with paths["failures"].open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in failures:
            writer.writerow(
                {key: _serialize_csv_value(value) for key, value in row.items()}
            )
    return paths


def validate_cases(
    rows: list[dict[str, Any]],
    *,
    source: str,
    expected_per_scenario: int | None = 4,
) -> None:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{source}: dataset must be a non-empty JSON list")

    ids: set[str] = set()
    questions: set[str] = set()
    scenario_counts: dict[str, int] = defaultdict(int)
    scenario_names = ", ".join(sorted(SCENARIO_SPECS))

    for index, row in enumerate(rows):
        prefix = f"{source} row {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{prefix}: row must be an object")
        missing = REQUIRED_KEYS - row.keys()
        if missing:
            raise ValueError(f"{prefix}: missing fields {sorted(missing)}")

        case_id = row["id"]
        question = row["question"]
        route = row["expected_route"]
        scenario = row["scenario"]
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"{prefix}: id must be a non-empty string")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"{prefix}: question must be a non-empty string")
        if not isinstance(route, str) or route not in SUPPORTED_ROUTES:
            raise ValueError(f"{prefix}: expected_route must be a supported route")
        if not isinstance(scenario, str) or scenario not in SCENARIO_SPECS:
            raise ValueError(
                f"{prefix}: scenario must be one of {scenario_names}"
            )
        if case_id in ids:
            raise ValueError(f"{prefix}: duplicate id {case_id!r}")
        if question in questions:
            raise ValueError(f"{prefix}: duplicate question {question!r}")

        spec = SCENARIO_SPECS[scenario]
        expected_tools = row["expected_tools"]
        if (
            not isinstance(expected_tools, list)
            or not all(isinstance(tool, str) for tool in expected_tools)
            or expected_tools != spec["tools"]
        ):
            raise ValueError(
                f"{prefix}: expected_tools must match scenario {scenario!r}"
            )
        if row["expected_outcome"] != spec["outcome"]:
            raise ValueError(
                f"{prefix}: expected_outcome must match scenario {scenario!r}"
            )
        tags = row["tags"]
        if (
            not isinstance(tags, list)
            or not tags
            or not all(isinstance(tag, str) and tag for tag in tags)
        ):
            raise ValueError(f"{prefix}: tags must be a non-empty string list")

        gold_sources = row["gold_sources"]
        if (
            not isinstance(gold_sources, list)
            or not all(isinstance(source, str) and source for source in gold_sources)
        ):
            raise ValueError(f"{prefix}: gold_sources must be a string list")
        if row["expected_outcome"] == "answered" and not gold_sources:
            raise ValueError(f"{prefix}: answered case requires gold_sources")
        if row["expected_outcome"] != "answered" and gold_sources:
            raise ValueError(
                f"{prefix}: non-answered case must not declare gold_sources"
            )
        ids.add(case_id)
        questions.add(question)
        scenario_counts[scenario] += 1

    if expected_per_scenario is not None:
        expected_counts = {
            scenario: expected_per_scenario for scenario in SCENARIO_SPECS
        }
        if dict(scenario_counts) != expected_counts:
            raise ValueError(
                f"{source}: expected scenario counts {expected_counts}, "
                f"got {dict(scenario_counts)}"
            )


def load_cases(split: str) -> list[dict[str, Any]]:
    path = EVAL_DIR / f"agent_loop_{split}.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    validate_cases(rows, source=str(path))
    return rows


def evaluate_all(
    rows: list[dict[str, Any]],
    *,
    mode: str,
) -> list[dict[str, Any]]:
    evaluated = []
    live_runner = AgentRunner() if mode == "live" else None
    for index, item in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] evaluating {item['id']} ({mode})")
        evaluated.append(
            evaluate_one(item, mode=mode, runner=live_runner)
        )
    return evaluated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate bounded adaptive Agentic RAG trajectories."
    )
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument(
        "--mode",
        choices=["deterministic", "live"],
        default="deterministic",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    cases = load_cases(args.split)
    rows = evaluate_all(cases, mode=args.mode)
    summary = summarize_rows(rows)
    paths = write_outputs(
        split=args.split,
        mode=args.mode,
        rows=rows,
        summary=summary,
        out_dir=args.out_dir,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for path in paths.values():
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
