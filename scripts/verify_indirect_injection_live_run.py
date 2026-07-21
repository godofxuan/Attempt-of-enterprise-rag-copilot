from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from app.evaluation.indirect_injection_live_writer import (
    LiveSecurityRunManifestV2,
    verify_live_security_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute and verify an existing private indirect-injection live "
            "run without invoking retrieval or model services."
        )
    )
    parser.add_argument("run_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = args.run_dir
    manifest = verify_live_security_run(run_dir)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    report = {
        "verified": True,
        "run_id": manifest.run_id,
        "schema_version": manifest.schema_version,
        "status": manifest.status,
        "protocol_complete": manifest.observation.protocol_complete,
        "pair_input_consistent": manifest.observation.pair_input_consistent,
        "deterministic_threshold_diagnostic_passed": (
            manifest.observation.deterministic_threshold_diagnostic_passed
        ),
        "manifest_sha256": hashlib.sha256(
            (run_dir / "manifest.json").read_bytes()
        ).hexdigest(),
        "guard_off": _mode_report(summary, "guard_off"),
        "guard_on": _mode_report(summary, "guard_on"),
    }
    if isinstance(manifest, LiveSecurityRunManifestV2):
        report["arm_execution"] = {
            "case_count": manifest.arm_order.case_count,
            "event_count": manifest.arm_order.case_count * 2,
            "off_then_on_count": manifest.arm_order.off_then_on_count,
            "on_then_off_count": manifest.arm_order.on_then_off_count,
            "protocol_id": manifest.arm_order.protocol_id,
        }
        report["arm_position_strata"] = _arm_position_strata(run_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _mode_report(summary: dict[str, object], prefix: str) -> dict[str, object]:
    security = summary[f"{prefix}_security"]
    live = summary[f"{prefix}_live"]
    return {
        "attack_success": security["attack_success"],
        "clean_task_success": security["clean_task_success"],
        "mixed_recoverable_success": security["mixed_recoverable_success"],
        "quarantine_recall_all_labeled_units": security["quarantine_recall"],
        "attack_unit_reached_guard": live["attack_unit_reached_guard"],
        "quarantine_recall_given_guard_exposure": live[
            "quarantine_recall_given_guard_exposure"
        ],
        "attack_unit_unreached_count": live["attack_unit_unreached_count"],
        "attack_unit_missed_by_guard_count": live[
            "attack_unit_missed_by_guard_count"
        ],
        "model_error_count": live["model_error_count"],
        "blocked_egress_attempt_count": live["blocked_egress_attempt_count"],
        "model_call_count": live["model_call_count"],
        "model_latency_p50_ms": live["model_latency_p50_ms"],
        "model_latency_p95_ms": live["model_latency_p95_ms"],
    }


def _arm_position_strata(run_dir: Path) -> dict[str, dict[str, object]]:
    rows = [
        json.loads(line)
        for line in (run_dir / "per_case.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    result: dict[str, dict[str, object]] = {}
    for position in (1, 2):
        result[str(position)] = {}
        for guard_mode in ("off", "on"):
            selected = [
                row
                for row in rows
                if row["arm_execution"]["arm_position"] == position
                and row["live"]["guard_mode"] == guard_mode
            ]
            attack = [row for row in selected if row["security"]["label"] == "attack"]
            benign = [row for row in selected if row["security"]["label"] == "benign"]
            latencies = [
                row["live"]["model_latency_ms"]
                for row in selected
                if row["live"]["model_call_count"] > 0
            ]
            result[str(position)][guard_mode] = {
                "case_count": len(selected),
                "attack_case_count": len(attack),
                "benign_case_count": len(benign),
                "attack_success": _count_rate(
                    sum(row["security"]["attack_success"] for row in attack),
                    len(attack),
                ),
                "raw_canary_or_forbidden_action_follow": _count_rate(
                    sum(row["live"]["model_attack_followed"] for row in attack),
                    len(attack),
                ),
                "clean_task_success": _count_rate(
                    sum(row["security"]["task_success"] for row in benign),
                    len(benign),
                ),
                "attack_unit_reached_guard_count": sum(
                    row["live"]["attack_unit_reached_guard_count"]
                    for row in attack
                ),
                "attack_unit_quarantined_count": sum(
                    row["live"]["attack_unit_quarantined_count"]
                    for row in attack
                ),
                "attack_unit_missed_by_guard_count": sum(
                    row["live"]["attack_unit_reached_guard_count"]
                    - row["live"]["attack_unit_quarantined_count"]
                    for row in attack
                ),
                "attack_unit_unreached_count": sum(
                    row["live"]["attack_unit_count"]
                    - row["live"]["attack_unit_reached_guard_count"]
                    for row in attack
                ),
                "model_call_count": sum(
                    row["live"]["model_call_count"] for row in selected
                ),
                "model_error_count": sum(
                    len(row["live"]["model_error_codes"]) for row in selected
                ),
                "blocked_egress_attempt_count": sum(
                    row["live"]["blocked_egress_attempt_count"]
                    for row in selected
                ),
                "model_latency_p50_ms": (
                    statistics.median(latencies) if latencies else None
                ),
                "model_latency_p95_ms": _nearest_rank(latencies, 0.95),
            }
    return result


def _count_rate(numerator: int, denominator: int) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


if __name__ == "__main__":
    raise SystemExit(main())
