from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from app.evaluation.quality_review import verify_quality_review_packet
from scripts import build_quality_review_packet


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_builds_reviewer_packet_and_separate_private_control_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_dir = tmp_path / "corpus"
    documents_dir = corpus_dir / "documents"
    documents_dir.mkdir(parents=True)
    document = documents_dir / "remote.md"
    document.write_text(
        "# Remote work\n\nEmployees may work remotely three days.\n",
        encoding="utf-8",
    )
    corpus_manifest = corpus_dir / "manifest.json"
    corpus_manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "doc_id": "auth_remote_2026",
                        "path": "documents/remote.md",
                        "sha256": sha256(document),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    dataset = tmp_path / "dev.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "case_id": "source-case-secret",
                    "question": "What is the current remote-work limit?",
                    "task_type": "fact_lookup",
                    "answer_mode": "answered",
                    "user_context": {
                        "user_id": "employee",
                        "tenant": "tenant-one",
                        "region": "cn",
                        "groups": ["employees"],
                    },
                    "required_fact_ids": ["remote-days"],
                    "gold_doc_ids": ["auth_remote_2026"],
                    "distractor_doc_ids": [],
                    "forbidden_doc_ids": [],
                    "expected_answer": "Three days.",
                    "expected_filters": {},
                    "expected_authority_doc_ids": ["auth_remote_2026"],
                    "tags": ["current"],
                }
            ]
        ),
        encoding="utf-8",
    )

    source_run = tmp_path / "source-run"
    source_run.mkdir()
    review_csv = source_run / "human_review.csv"
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "task_type",
                "question",
                "expected_mode",
                "actual_mode",
                "system_answer",
                "visible_source_doc_ids",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "source-case-secret",
                "task_type": "fact_lookup",
                "question": "What is the current remote-work limit?",
                "expected_mode": "answered",
                "actual_mode": "answered",
                "system_answer": "The limit is three days [auth_remote_2026].",
                "visible_source_doc_ids": "auth_remote_2026",
            }
        )
    source_manifest = source_run / "manifest.json"
    source_manifest.write_text(
        json.dumps(
            {
                "run_id": "source-run-001",
                "git": {"head": "1" * 40},
                "dataset": {"sha256": sha256(dataset)},
                "corpus": {"manifest_sha256": sha256(corpus_manifest)},
                "artifacts": {"human_review.csv": sha256(review_csv)},
            }
        ),
        encoding="utf-8",
    )
    blinding_key = tmp_path / "review.key"
    blinding_key.write_bytes(b"\0" * 32)

    arguments = [
        "--packet-id",
        "calibration-cli-001",
        "--source-run-dir",
        str(source_run),
        "--dataset-path",
        str(dataset),
        "--dataset-split",
        "dev",
        "--corpus-dir",
        str(corpus_dir),
        "--out-dir",
        str(tmp_path / "packets"),
        "--control-out-dir",
        str(tmp_path / "private-control"),
        "--blinding-key-file",
        str(blinding_key),
        "--sampling-strategy",
        "all_cases",
    ]
    with pytest.raises(ValueError, match="weak"):
        build_quality_review_packet.main(arguments)
    assert not (tmp_path / "packets" / "calibration-cli-001").exists()

    blinding_key.write_bytes(bytes(range(32)))
    publish_control = build_quality_review_packet._publish_control_map

    def fail_control_publication(*args, **kwargs):
        raise RuntimeError("injected control publication failure")

    monkeypatch.setattr(
        build_quality_review_packet,
        "_publish_control_map",
        fail_control_publication,
    )
    with pytest.raises(RuntimeError, match="injected"):
        build_quality_review_packet.main(arguments)
    assert (tmp_path / "packets" / "calibration-cli-001").is_dir()
    assert not (
        tmp_path / "private-control" / "calibration-cli-001"
    ).exists()

    monkeypatch.setattr(
        build_quality_review_packet,
        "_publish_control_map",
        publish_control,
    )
    result = build_quality_review_packet.main(arguments)

    assert result == 0
    packet_dir = tmp_path / "packets" / "calibration-cli-001"
    verified = verify_quality_review_packet(packet_dir)
    assert verified.item_count == 1
    reviewer_text = (packet_dir / "review_items.jsonl").read_text(encoding="utf-8")
    assert "source-case-secret" not in reviewer_text
    assert "machine_passed" not in reviewer_text

    control_map = (
        tmp_path
        / "private-control"
        / "calibration-cli-001"
        / "item_map.jsonl"
    ).read_text(encoding="utf-8")
    assert "source-case-secret" in control_map
    assert verified.claim_status == "NOT_RUN"
    assert build_quality_review_packet.main(arguments) == 0
