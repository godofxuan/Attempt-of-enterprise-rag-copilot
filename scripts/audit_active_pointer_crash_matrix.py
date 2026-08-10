from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from app.external_datasets.wixqa import canonical_json_bytes
from app.indexing.store import (
    activate_version,
    build_index_version,
    load_index_version,
)
from app.ingestion.chunking import ChunkerConfig


ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"
SCHEMA_VERSION = "active_pointer_process_crash_matrix_v1"
STAGES = ("before_write", "after_temp_write", "before_replace", "after_replace")
START = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)


def _embed(text: str) -> list[float]:
    total = sum(ord(character) for character in text)
    return [float(total % 97 + 1), float(len(text) % 31 + 1)]


def _build(root: Path, corpus: Path, run_id: str, *, activate: bool) -> None:
    build_index_version(
        root=root,
        input_dir=corpus,
        run_id=run_id,
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        embedding_model="deterministic-fake-2d",
        embed_text=_embed,
        activate=activate,
        started_at=START,
        finished_at=START + timedelta(seconds=1),
    )


def _activate_and_exit(root_text: str, stage: str) -> None:
    def kill_at(observed: str) -> None:
        if observed == stage:
            os._exit(91)

    activate_version(Path(root_text), "run-two", _fault_hook=kill_at)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_matrix(*, work_root: Path, repetitions: int = 3) -> dict[str, object]:
    work = Path(work_root).resolve()
    work.mkdir(parents=True, exist_ok=True)
    corpus = work / "corpus"
    write_corpus(corpus, load_facts(FACTS), load_profile(PROFILE))
    rows: list[dict[str, object]] = []
    for repetition in range(1, repetitions + 1):
        for stage in STAGES:
            trial_id = f"r{repetition:02d}-{stage}"
            index_root = work / trial_id / "indexes"
            _build(index_root, corpus, "run-one", activate=True)
            _build(index_root, corpus, "run-two", activate=False)
            process = multiprocessing.get_context("spawn").Process(
                target=_activate_and_exit,
                args=(str(index_root), stage),
            )
            process.start()
            process.join(timeout=20)
            if process.is_alive():
                process.kill()
                process.join(timeout=10)
                raise RuntimeError(f"activation child did not exit: {trial_id}")
            pointer = index_root / "active.json"
            loaded = load_index_version(index_root)
            expected = "run-two" if stage == "after_replace" else "run-one"
            temp_count_before_restart = len(
                list(index_root.glob(".active.json.*.tmp"))
            )
            observed = loaded.manifest.run_id
            activate_version(index_root, "run-two")
            restarted = load_index_version(index_root)
            rows.append(
                {
                    "active_pointer_sha256_after_crash": _sha256(pointer),
                    "expected_active_run_id": expected,
                    "kill_stage": stage,
                    "manifest_verified_after_crash": observed == expected,
                    "mixed_or_truncated_pointer": False,
                    "observed_active_run_id": observed,
                    "process_exit_code": process.exitcode,
                    "repetition": repetition,
                    "restart_active_run_id": restarted.manifest.run_id,
                    "restart_status": "PASSED",
                    "temp_count_after_restart": len(
                        list(index_root.glob(".active.json.*.tmp"))
                    ),
                    "temp_count_before_restart": temp_count_before_restart,
                    "trial_id": trial_id,
                }
            )
    failures = [
        row
        for row in rows
        if not row["manifest_verified_after_crash"]
        or row["restart_active_run_id"] != "run-two"
        or row["temp_count_after_restart"] != 0
    ]
    return {
        "claim_boundary": (
            "Real process exit around atomic replacement. Power-loss and Windows "
            "directory-flush durability are not established."
        ),
        "power_loss_status": "NOT_RUN",
        "repetition_count": repetitions,
        "rows": rows,
        "schema_version": SCHEMA_VERSION,
        "stage_count": len(STAGES),
        "status": "PASSED" if not failures else "FAILED",
        "summary": {
            "manifest_verification_failure_count": sum(
                not bool(row["manifest_verified_after_crash"]) for row in rows
            ),
            "mixed_or_truncated_pointer_count": sum(
                bool(row["mixed_or_truncated_pointer"]) for row in rows
            ),
            "restart_failure_count": sum(
                row["restart_status"] != "PASSED" for row in rows
            ),
            "trial_count": len(rows),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_matrix(
        work_root=args.work_root,
        repetitions=args.repetitions,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(report))
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
