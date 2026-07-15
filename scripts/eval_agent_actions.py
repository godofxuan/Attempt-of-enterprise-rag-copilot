try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.agent.controller import FixedPlanController
from app.agent.runner import AgentRunner
from app.agent.tools import ToolExecutionResult, ToolRegistry


BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BASE_DIR / "data" / "eval"
OUT_DIR = BASE_DIR / "data" / "eval_outputs"
SPLIT_TO_FILE = {
    "dev": "agent_action_dev.json",
    "test": "agent_action_test.json",
}
ROUTES = {
    "policy_qa",
    "process",
    "comparison",
    "no_answer_check",
    "unsafe_request",
}
SAFE_PLAN = ["retrieval.search", "rag.answer", "guardrail.check"]
UNSAFE_PLAN = ["guardrail.refuse"]
REQUIRED_KEYS = {"id", "question", "expected_route", "expected_plan", "tags"}
METRIC_TO_RATE = {
    "route_correct": "route_accuracy",
    "plan_exact_match": "plan_exact_match_rate",
    "tool_sequence_correct": "tool_sequence_accuracy",
    "trace_complete": "trace_complete_rate",
    "case_pass": "case_pass_rate",
}
FAILURE_FIELDS = [
    "id",
    "expected_route",
    "actual_route",
    "question",
    "expected_plan",
    "actual_plan",
    "actual_tools",
    "route_correct",
    "plan_exact_match",
    "tool_sequence_correct",
    "trace_complete",
    "unsafe_no_retrieval",
    "case_pass",
    "execution_error",
    "latency_ms",
    "tags",
]


def build_eval_registry() -> ToolRegistry:
    registry = ToolRegistry()

    def retrieval_tool(context: dict[str, Any]) -> ToolExecutionResult:
        chunk = {
            "source": "eval_fixture.md",
            "section": "Fixture",
            "chunk_id": "eval_fixture::0",
            "text": "Deterministic evidence for Agent action evaluation.",
        }
        source = {**chunk, "preview": chunk["text"]}
        return ToolExecutionResult(
            updates={
                "retrieved_chunks": [chunk],
                "retrieved_sources": [source],
            },
            output_summary="retrieved 1 deterministic chunk",
        )

    def answer_tool(context: dict[str, Any]) -> ToolExecutionResult:
        chunks = context["retrieved_chunks"]
        source = {
            "source": chunks[0]["source"],
            "section": chunks[0]["section"],
            "chunk_id": chunks[0]["chunk_id"],
            "preview": chunks[0]["text"],
        }
        return ToolExecutionResult(
            updates={
                "answer": "deterministic grounded answer",
                "sources": [source],
            },
            output_summary="generated deterministic answer",
        )

    registry.register("retrieval.search", retrieval_tool)
    registry.register("rag.answer", answer_tool)
    registry.register(
        "guardrail.check",
        lambda context: ToolExecutionResult(
            updates={"guardrail_blocked": False},
            output_summary="deterministic answer allowed",
        ),
    )
    registry.register(
        "guardrail.refuse",
        lambda context: ToolExecutionResult(
            updates={
                "answer": "deterministic refusal",
                "sources": [],
                "guardrail_blocked": True,
            },
            output_summary="deterministic unsafe refusal",
        ),
    )
    return registry


def trace_is_complete(response: Any) -> bool:
    plan = response.trace.plan
    steps = response.trace.steps
    if not response.trace.route or not plan or len(plan) != len(steps):
        return False

    return all(
        plan_step.tool == trace_step.tool
        and trace_step.status == "ok"
        and trace_step.latency_ms >= 0
        and bool(trace_step.output_summary.strip())
        for plan_step, trace_step in zip(plan, steps)
    )


def evaluate_one(
    item: dict[str, Any],
    runner: AgentRunner | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    expected_route = item["expected_route"]
    expected_plan = list(item["expected_plan"])
    try:
        response = (
            runner
            or AgentRunner(
                registry=build_eval_registry(),
                controller=FixedPlanController(),
            )
        ).run(item["question"])
    except Exception as exc:
        return {
            "id": item["id"],
            "question": item["question"],
            "tags": item.get("tags", []),
            "expected_route": expected_route,
            "actual_route": None,
            "expected_plan": expected_plan,
            "actual_plan": [],
            "actual_tools": [],
            "route_correct": 0,
            "plan_exact_match": 0,
            "tool_sequence_correct": 0,
            "trace_complete": 0,
            "unsafe_no_retrieval": (
                0 if expected_route == "unsafe_request" else None
            ),
            "case_pass": 0,
            "execution_error": f"{type(exc).__name__}: {exc}",
            "latency_ms": (time.perf_counter() - started_at) * 1000,
        }

    actual_route = response.trace.route
    actual_plan = [step.tool for step in response.trace.plan]
    actual_tools = [step.tool for step in response.trace.steps]
    route_correct = int(actual_route == expected_route)
    plan_exact_match = int(actual_plan == expected_plan)
    tool_sequence_correct = int(actual_tools == expected_plan)
    trace_complete = int(trace_is_complete(response))
    unsafe_no_retrieval = None
    if expected_route == "unsafe_request":
        unsafe_no_retrieval = int(
            "retrieval.search" not in actual_tools
            and "rag.answer" not in actual_tools
        )
    applicable_checks = [
        route_correct,
        plan_exact_match,
        tool_sequence_correct,
        trace_complete,
    ]
    if unsafe_no_retrieval is not None:
        applicable_checks.append(unsafe_no_retrieval)
    case_pass = int(all(applicable_checks))

    return {
        "id": item["id"],
        "question": item["question"],
        "tags": item.get("tags", []),
        "expected_route": expected_route,
        "actual_route": actual_route,
        "expected_plan": expected_plan,
        "actual_plan": actual_plan,
        "actual_tools": actual_tools,
        "route_correct": route_correct,
        "plan_exact_match": plan_exact_match,
        "tool_sequence_correct": tool_sequence_correct,
        "trace_complete": trace_complete,
        "unsafe_no_retrieval": unsafe_no_retrieval,
        "case_pass": case_pass,
        "execution_error": "",
        "latency_ms": (time.perf_counter() - started_at) * 1000,
    }


def validate_cases(
    rows: list[dict[str, Any]],
    *,
    source: str,
    expected_per_route: int | None,
) -> None:
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    route_counts: Counter[str] = Counter()

    for index, row in enumerate(rows):
        location = f"{source} row {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{location}: row must be an object")

        missing = REQUIRED_KEYS - row.keys()
        if missing:
            raise ValueError(f"{location}: missing fields {sorted(missing)}")

        case_id = row["id"]
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"{location}: id must be a non-empty string")
        if case_id in seen_ids:
            raise ValueError(f"{source}: duplicate id {case_id!r}")
        seen_ids.add(case_id)

        question = row["question"]
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"{location}: question must be a non-empty string")
        if question in seen_questions:
            raise ValueError(f"{source}: duplicate question {question!r}")
        seen_questions.add(question)

        route = row["expected_route"]
        if not isinstance(route, str) or route not in ROUTES:
            raise ValueError(
                f"{location}: expected_route must be a supported route, got {route!r}"
            )
        route_counts[route] += 1

        expected_plan = UNSAFE_PLAN if route == "unsafe_request" else SAFE_PLAN
        if row["expected_plan"] != expected_plan:
            raise ValueError(
                f"{location}: expected_plan must be {expected_plan!r} for {route!r}"
            )

        tags = row["tags"]
        if (
            not isinstance(tags, list)
            or not tags
            or not all(isinstance(tag, str) and tag.strip() for tag in tags)
        ):
            raise ValueError(f"{location}: tags must be a non-empty string list")

    if expected_per_route is not None:
        expected_counts = Counter({route: expected_per_route for route in ROUTES})
        if route_counts != expected_counts:
            raise ValueError(
                f"{source}: route coverage must be {dict(expected_counts)}, "
                f"got {dict(route_counts)}"
            )


def _load_split_file(split: str) -> list[dict[str, Any]]:
    path = EVAL_DIR / SPLIT_TO_FILE[split]
    with path.open("r", encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError(f"{path}: top-level JSON value must be a list")
    validate_cases(rows, source=str(path), expected_per_route=4)
    return rows


def load_cases(split: str) -> list[dict[str, Any]]:
    if split == "all":
        rows = _load_split_file("dev") + _load_split_file("test")
        validate_cases(rows, source="combined agent action splits", expected_per_route=8)
        return rows
    return _load_split_file(split)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _summary_without_groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"count": len(rows)}
    for metric_name, rate_name in METRIC_TO_RATE.items():
        summary[rate_name] = _mean(
            [float(row[metric_name]) for row in rows]
        )

    unsafe_values = [
        float(row["unsafe_no_retrieval"])
        for row in rows
        if row.get("unsafe_no_retrieval") is not None
    ]
    summary["unsafe_no_retrieval_rate"] = (
        _mean(unsafe_values) if unsafe_values else None
    )
    return summary


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summary_without_groups(rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["expected_route"])].append(row)
    summary["by_expected_route"] = {
        route: _summary_without_groups(route_rows)
        for route, route_rows in sorted(grouped.items())
    }
    return summary


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_outputs(
    split: str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    out_dir: Path = OUT_DIR,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "results": out_dir / f"agent_action_{split}_results.json",
        "details": out_dir / f"agent_action_{split}_details.jsonl",
        "failures": out_dir / f"agent_action_{split}_failures.csv",
    }

    with paths["results"].open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "summary": summary,
                "config": {
                    "split": split,
                    "case_count": len(rows),
                    "uses_external_services": False,
                },
                "output_files": {name: str(path) for name, path in paths.items()},
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    with paths["details"].open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    failures = sorted(
        (row for row in rows if not row["case_pass"]),
        key=lambda row: (str(row["expected_route"]), str(row["id"])),
    )
    with paths["failures"].open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=FAILURE_FIELDS)
        writer.writeheader()
        for row in failures:
            writer.writerow({field: _csv_value(row.get(field)) for field in FAILURE_FIELDS})

    return paths


def evaluate_all(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evaluated: list[dict[str, Any]] = []
    runner = AgentRunner(
        registry=build_eval_registry(),
        controller=FixedPlanController(),
    )
    total = len(rows)
    for index, item in enumerate(rows, start=1):
        print(
            f"[{index}/{total}] evaluating {item['id']}",
            file=sys.stderr,
            flush=True,
        )
        evaluated.append(evaluate_one(item, runner=runner))
    return evaluated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic routing, planning, tool order, and Agent trace behavior."
    )
    parser.add_argument(
        "--split",
        choices=["dev", "test", "all"],
        default="test",
    )
    args = parser.parse_args()

    cases = load_cases(args.split)
    rows = evaluate_all(cases)
    summary = summarize_rows(rows)
    paths = write_outputs(args.split, rows, summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for path in paths.values():
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
