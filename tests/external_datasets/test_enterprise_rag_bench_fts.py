from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from threading import Event, Lock
import time

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import app.external_datasets.enterprise_rag_bench_fts as fts_module

from app.external_datasets.enterprise_rag_bench import EnterpriseRAGBenchQuestion
from app.external_datasets.enterprise_rag_bench_eval import (
    score_enterprise_rag_bench_ranking,
    summarize_enterprise_rag_bench_retrieval,
)
from app.external_datasets.enterprise_rag_bench_fts import (
    build_enterprise_rag_bench_fts,
    compile_fts_query,
    load_enterprise_rag_bench_fts,
    verify_enterprise_rag_bench_fts,
)
from scripts.publish_enterprise_rag_bench_fts_eval import build_public_evidence
from scripts.analyze_enterprise_rag_bench_failures import classify_failure


def _write_documents(path: Path) -> None:
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "doc_id": "dsid_alpha",
                    "source_type": "slack",
                    "title": "Canary rollout",
                    "content": "The SDK canary starts on Tuesday.",
                },
                {
                    "doc_id": "dsid_reused",
                    "source_type": "jira",
                    "title": "Cleanup approval request",
                    "content": "An infra manager approval was requested.",
                },
                {
                    "doc_id": "dsid_reused",
                    "source_type": "jira",
                    "title": "Cleanup approval decision",
                    "content": "Cost ops approval is sufficient after the grace window.",
                },
            ]
        ),
        path,
    )


def _hold_build_lock_until_killed(root_text: str, ready_text: str) -> None:
    root = Path(root_text)
    root.mkdir(parents=True, exist_ok=True)
    with fts_module._single_writer_build_lock(root, run_id="crash-owner"):
        Path(ready_text).write_text("ready", encoding="ascii")
        time.sleep(60)


def test_query_compiler_removes_operators_and_common_question_words() -> None:
    compiled = compile_fts_query('Who approves "cleanup" OR cost-ops?')
    assert compiled == '"approves" OR "cleanup" OR "cost" OR "ops"'
    assert "Who" not in compiled


def test_build_rejects_run_id_path_traversal_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid FTS run_id"):
        build_enterprise_rag_bench_fts(
            documents_path=tmp_path / "missing.parquet",
            output_root=tmp_path / "index",
            run_id="../escape",
            corpus_sha256="a" * 64,
            dataset_manifest_sha256="b" * 64,
            expected_document_count=1,
        )
    assert not (tmp_path / "index").exists()


def test_build_resumes_after_committed_interruption_and_preserves_reused_ids(
    tmp_path: Path,
) -> None:
    documents = tmp_path / "documents.parquet"
    output = tmp_path / "index"
    _write_documents(documents)
    arguments = {
        "documents_path": documents,
        "output_root": output,
        "run_id": "fixture-v1",
        "corpus_sha256": "a" * 64,
        "dataset_manifest_sha256": "b" * 64,
        "expected_document_count": 3,
        "commit_interval": 2,
    }
    with pytest.raises(InterruptedError, match="source row 2"):
        build_enterprise_rag_bench_fts(
            **arguments,
            interrupt_after_documents=2,
        )

    manifest = build_enterprise_rag_bench_fts(**arguments)
    assert manifest.document_row_count == 3
    assert manifest.unique_source_id_count == 2
    assert manifest.resumed_from_document == 2
    assert manifest.source_counts == {"jira": 2, "slack": 1}
    assert verify_enterprise_rag_bench_fts(
        output / "versions" / "fixture-v1"
    ) == manifest

    with load_enterprise_rag_bench_fts(output) as index:
        hits = index.search("Which group approves cleanup after the grace window?")
    assert hits[0].source_native_id == "dsid_reused"
    assert hits[0].record_id.endswith(hits[0].raw_record_sha256[:16])


def test_resume_rejects_a_different_corpus_contract(tmp_path: Path) -> None:
    documents = tmp_path / "documents.parquet"
    output = tmp_path / "index"
    _write_documents(documents)
    with pytest.raises(InterruptedError):
        build_enterprise_rag_bench_fts(
            documents_path=documents,
            output_root=output,
            run_id="fixture-v1",
            corpus_sha256="a" * 64,
            dataset_manifest_sha256="b" * 64,
            expected_document_count=3,
            commit_interval=1,
            interrupt_after_documents=1,
        )
    with pytest.raises(ValueError, match="metadata mismatch: corpus_sha256"):
        build_enterprise_rag_bench_fts(
            documents_path=documents,
            output_root=output,
            run_id="fixture-v1",
            corpus_sha256="c" * 64,
            dataset_manifest_sha256="b" * 64,
            expected_document_count=3,
            commit_interval=1,
        )


def test_interrupted_build_does_not_replace_active_index(tmp_path: Path) -> None:
    documents = tmp_path / "documents.parquet"
    output = tmp_path / "index"
    _write_documents(documents)
    base = {
        "documents_path": documents,
        "output_root": output,
        "corpus_sha256": "a" * 64,
        "dataset_manifest_sha256": "b" * 64,
        "expected_document_count": 3,
        "commit_interval": 1,
    }
    build_enterprise_rag_bench_fts(**base, run_id="active-v1")
    active_before = (output / "active.json").read_bytes()

    with pytest.raises(InterruptedError):
        build_enterprise_rag_bench_fts(
            **base,
            run_id="candidate-v2",
            interrupt_after_documents=1,
        )

    assert (output / "active.json").read_bytes() == active_before
    with load_enterprise_rag_bench_fts(output) as loaded:
        assert loaded.manifest.run_id == "active-v1"
    assert not (output / "versions" / "candidate-v2").exists()


def test_failed_verification_does_not_replace_active_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = tmp_path / "documents.parquet"
    output = tmp_path / "index"
    _write_documents(documents)
    base = {
        "documents_path": documents,
        "output_root": output,
        "corpus_sha256": "a" * 64,
        "dataset_manifest_sha256": "b" * 64,
        "expected_document_count": 3,
        "commit_interval": 1,
    }
    build_enterprise_rag_bench_fts(**base, run_id="active-v1")
    active_before = (output / "active.json").read_bytes()
    original_verify = fts_module.verify_enterprise_rag_bench_fts

    def fail_candidate(path: Path):
        if Path(path).name == ".candidate-v2.building":
            raise ValueError("injected verification failure")
        return original_verify(path)

    monkeypatch.setattr(
        fts_module,
        "verify_enterprise_rag_bench_fts",
        fail_candidate,
    )
    with pytest.raises(ValueError, match="injected verification failure"):
        build_enterprise_rag_bench_fts(**base, run_id="candidate-v2")

    assert (output / "active.json").read_bytes() == active_before
    assert not (output / "versions" / "candidate-v2").exists()
    with load_enterprise_rag_bench_fts(output) as loaded:
        assert loaded.manifest.run_id == "active-v1"


def test_second_concurrent_builder_fails_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = tmp_path / "documents.parquet"
    output = tmp_path / "index"
    _write_documents(documents)
    entered = Event()
    release = Event()
    calls_lock = Lock()
    calls = 0
    original_iter = fts_module.iter_enterprise_rag_bench_documents

    def blocking_iter(*args, **kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
            ordinal = calls
        if ordinal == 1:
            entered.set()
            assert release.wait(timeout=10)
        yield from original_iter(*args, **kwargs)

    monkeypatch.setattr(
        fts_module,
        "iter_enterprise_rag_bench_documents",
        blocking_iter,
    )
    arguments = {
        "documents_path": documents,
        "output_root": output,
        "run_id": "fixture-v1",
        "corpus_sha256": "a" * 64,
        "dataset_manifest_sha256": "b" * 64,
        "expected_document_count": 3,
        "commit_interval": 1,
    }
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(build_enterprise_rag_bench_fts, **arguments)
        assert entered.wait(timeout=10)
        try:
            with pytest.raises(RuntimeError, match="single-writer"):
                build_enterprise_rag_bench_fts(**arguments)
        finally:
            release.set()
        assert first.result(timeout=10).run_id == "fixture-v1"


def test_single_writer_lock_recovers_after_hard_process_termination(
    tmp_path: Path,
) -> None:
    output = (tmp_path / "hard-crash-lock").absolute()
    ready = tmp_path / "lock-ready"
    process = get_context("spawn").Process(
        target=_hold_build_lock_until_killed,
        args=(str(output), str(ready)),
    )
    process.start()
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()

    process.terminate()
    process.join(timeout=10)
    assert not process.is_alive()

    with fts_module._single_writer_build_lock(
        output,
        run_id="recovery-owner",
    ):
        assert (output / ".single-writer-build.lock").is_file()


def test_retrieval_metrics_use_unique_gold_and_report_completeness() -> None:
    question = EnterpriseRAGBenchQuestion(
        question_id="qst_fixture",
        question_type="conflicting_info",
        source_types=["jira"],
        question="What conflicts?",
        expected_doc_ids=["dsid_a", "dsid_a", "dsid_b"],
        gold_answer="Two records conflict.",
        answer_facts=["conflict"],
    )
    score = score_enterprise_rag_bench_ranking(
        question,
        ranked_source_ids=["dsid_a", "dsid_other", "dsid_b"],
        latency_ms=4.0,
    )
    assert score.gold_document_count == 2
    assert score.recall_at_1 == 0.5
    assert score.recall_at_3 == 1.0
    assert score.complete_at_5 == 1.0
    summary = summarize_enterprise_rag_bench_retrieval([score], group="fixture")
    assert summary.multi_document_completeness_at_5 == 1.0
    assert summary.latency_ms_p95 == 4.0


def test_public_eval_rejects_debug_or_oracle_filtered_runs() -> None:
    summary = {
        "mode": "PIPELINE_DEBUG",
        "case_count": 470,
        "source_type_filter_used": False,
        "answer_labels_used": False,
    }
    with pytest.raises(ValueError, match="formal full-corpus"):
        build_public_evidence(
            summary,
            {"document_row_count": 511_962},
            private_summary_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {"recall_at_5": 0.0, "gold_document_count": 1, "hit_at_1": 0.0},
            "RETRIEVAL_MISS",
        ),
        (
            {"recall_at_5": 0.5, "gold_document_count": 2, "hit_at_1": 1.0},
            "MULTI_DOC_INCOMPLETE",
        ),
        (
            {"recall_at_5": 1.0, "gold_document_count": 1, "hit_at_1": 0.0},
            "WRONG_DOCUMENT",
        ),
        (
            {"recall_at_5": 1.0, "gold_document_count": 1, "hit_at_1": 1.0},
            "OK",
        ),
    ],
)
def test_failure_classification_priority(row: dict, expected: str) -> None:
    assert classify_failure(row) == expected
