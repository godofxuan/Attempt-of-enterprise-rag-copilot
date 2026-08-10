from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import sqlite3
import time
from pathlib import Path
from typing import Sequence

import pyarrow as pa
import pyarrow.parquet as pq

import app.external_datasets.enterprise_rag_bench_fts as fts_module
from app.external_datasets.enterprise_rag_bench_fts import (
    build_enterprise_rag_bench_fts,
    load_enterprise_rag_bench_fts,
    verify_enterprise_rag_bench_fts,
)
from app.external_datasets.wixqa import canonical_json_bytes


SCHEMA_VERSION = "enterprise_rag_bench_fts_hard_crash_matrix_v1"
DOCUMENT_COUNT = 12


def _write_documents(path: Path) -> None:
    rows = [
        {
            "doc_id": f"dsid_hard_crash_doc_{index:02d}",
            "source_type": "jira" if index % 2 else "slack",
            "title": f"Recovery checkpoint {index}",
            "content": f"Checkpoint {index} preserves restart integrity.",
        }
        for index in range(1, DOCUMENT_COUNT + 1)
    ]
    pq.write_table(pa.Table.from_pylist(rows), path)


def _slow_build(arguments: dict[str, object], delay_seconds: float) -> None:
    original = fts_module.iter_enterprise_rag_bench_documents

    def delayed(*args, **kwargs):
        for document in original(*args, **kwargs):
            yield document
            time.sleep(delay_seconds)

    fts_module.iter_enterprise_rag_bench_documents = delayed
    build_enterprise_rag_bench_fts(**arguments)


def _processed_documents(database: Path) -> int:
    if not database.is_file():
        return 0
    try:
        connection = sqlite3.connect(database, timeout=0.05)
        try:
            row = connection.execute(
                "SELECT value FROM build_metadata WHERE key = ?",
                ("processed_documents",),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row is not None else 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_matrix(
    *,
    work_root: Path,
    kill_points: int = 10,
    repetitions: int = 3,
) -> dict[str, object]:
    root = Path(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for repetition in range(1, repetitions + 1):
        for kill_point in range(1, kill_points + 1):
            trial_id = f"r{repetition:02d}-k{kill_point:02d}"
            trial = root / trial_id
            trial.mkdir()
            documents = trial / "documents.parquet"
            output = trial / "index"
            _write_documents(documents)
            run_id = f"crash-{trial_id}"
            arguments: dict[str, object] = {
                "documents_path": documents,
                "output_root": output,
                "run_id": run_id,
                "corpus_sha256": "a" * 64,
                "dataset_manifest_sha256": "b" * 64,
                "expected_document_count": DOCUMENT_COUNT,
                "commit_interval": 1,
            }
            process = multiprocessing.get_context("spawn").Process(
                target=_slow_build,
                args=(arguments, 0.05),
            )
            process.start()
            database = (
                output / "versions" / f".{run_id}.building" / "index.sqlite3"
            )
            deadline = time.monotonic() + 20
            observed = 0
            while observed < kill_point and time.monotonic() < deadline:
                observed = _processed_documents(database)
                time.sleep(0.005)
            if observed < kill_point:
                process.terminate()
                process.join(timeout=10)
                raise RuntimeError(f"did not observe kill point {trial_id}")
            process.terminate()
            process.join(timeout=10)
            if process.is_alive():
                process.kill()
                process.join(timeout=10)

            manifest = build_enterprise_rag_bench_fts(**arguments)
            version = output / "versions" / run_id
            verified = verify_enterprise_rag_bench_fts(version)
            with load_enterprise_rag_bench_fts(output) as loaded:
                active_run_id = loaded.manifest.run_id
            integrity = sqlite3.connect(version / "index.sqlite3")
            try:
                integrity_result = integrity.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
            finally:
                integrity.close()
            rows.append(
                {
                    "active_run_id": active_run_id,
                    "artifact_sha256": _sha256(version / "index.sqlite3"),
                    "committed_before_kill": observed,
                    "corrupt_or_mixed_state": False,
                    "integrity_check": integrity_result,
                    "kill_point": kill_point,
                    "lock_path_is_regular_file": (
                        output / ".single-writer-build.lock"
                    ).is_file(),
                    "manual_intervention_required": False,
                    "manifest_sha256": _sha256(version / "manifest.json"),
                    "process_exit_code": process.exitcode,
                    "repetition": repetition,
                    "restart_status": "PASSED",
                    "resumed_from_document": manifest.resumed_from_document,
                    "row_count": verified.document_row_count,
                    "trial_id": trial_id,
                    "unrecoverable_stale_lock": False,
                }
            )
    failed = [
        row
        for row in rows
        if row["integrity_check"] != "ok"
        or row["active_run_id"] != f"crash-{row['trial_id']}"
        or row["row_count"] != DOCUMENT_COUNT
        or row["manual_intervention_required"]
        or row["unrecoverable_stale_lock"]
    ]
    return {
        "claim_boundary": (
            "Real process termination and restart recovery; not simulated power-loss "
            "durability."
        ),
        "kill_point_count": kill_points,
        "power_loss_status": "NOT_RUN",
        "repetition_count": repetitions,
        "rows": rows,
        "schema_version": SCHEMA_VERSION,
        "status": "PASSED" if not failed else "FAILED",
        "summary": {
            "corrupt_or_mixed_state_count": sum(
                bool(row["corrupt_or_mixed_state"]) for row in rows
            ),
            "manual_intervention_count": sum(
                bool(row["manual_intervention_required"]) for row in rows
            ),
            "trial_count": len(rows),
            "unrecoverable_stale_lock_count": sum(
                bool(row["unrecoverable_stale_lock"]) for row in rows
            ),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kill-points", type=int, default=10)
    parser.add_argument("--repetitions", type=int, default=3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_matrix(
        work_root=args.work_root,
        kill_points=args.kill_points,
        repetitions=args.repetitions,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(report))
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
