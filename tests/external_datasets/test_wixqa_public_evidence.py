from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.publish_wixqa_retrieval_eval import (
    EXPECTED_ARMS,
    SUMMARY_FIELDS,
    build_public_evidence,
)
from scripts.reproduce_wixqa_retrieval import (
    _verify_clean_roots,
    build_parser,
    command_plan,
)
from scripts.verify_wixqa_clean_reproduction import compare_reproduction


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "enterprise_eval" / "evidence"


def _protocol() -> dict:
    return json.loads(
        (EVIDENCE / "WIXQA_RETRIEVAL_PROTOCOL_V1.json").read_text(
            encoding="utf-8"
        )
    )


def _summary(cohort: str) -> dict:
    protocol = _protocol()
    base = {
        "schema_version": "wixqa_retrieval_run_v1",
        "cohort": cohort,
        "case_count": protocol["cohorts"][cohort]["case_count"],
        "question_ids_sha256": protocol["cohorts"][cohort][
            "question_ids_sha256"
        ],
        "dataset_manifest_sha256": protocol["dataset_manifest_sha256"],
        "index_manifest_sha256": "a" * 64,
        "embedding_model": "bge-m3",
        "embedding_model_sha256": protocol["embedding"]["ollama_model_sha256"],
        "code_revision": "b" * 40,
        "consumption": "DEVELOPMENT",
        "details_sha256": "c" * 64,
    }
    summaries = []
    for arm in EXPECTED_ARMS:
        item = {
            "arm": arm,
            "multi_article_case_count": 1,
            **{field: 0.5 for field in SUMMARY_FIELDS},
        }
        item["multi_article_completeness_at_5"] = 0.5
        summaries.append(item)
    return {**base, "summaries": summaries}


def test_public_evidence_arms_exactly_match_protocol() -> None:
    payload = json.loads(
        (EVIDENCE / "wixqa_retrieval_baseline_public_v2.json").read_text(
            encoding="utf-8"
        )
    )
    assert tuple(payload["protocol_arms"]) == tuple(_protocol()["arms"])
    assert payload["protocol_sha256"] == (
        "4229a558d637fd4449bdb70887c480fb01c50621f0ae96c9db1562e3ebfeb531"
    )
    for cohort in payload["results"].values():
        assert set(cohort["arms"]) == {"bm25", "dense", "equal_rrf"}
        for arm in cohort["arms"].values():
            assert set(arm) == set(SUMMARY_FIELDS)


def test_publisher_rejects_missing_protocol_arm() -> None:
    runs = {cohort: _summary(cohort) for cohort in ("synthetic", "simulated", "expertwritten")}
    runs["simulated"]["summaries"].pop()
    with pytest.raises(ValueError, match="arms do not match"):
        build_public_evidence(
            protocol=_protocol(),
            runs=runs,
            private_summary_hashes={cohort: "d" * 64 for cohort in runs},
        )


def test_publisher_rejects_dataset_manifest_drift() -> None:
    runs = {
        cohort: _summary(cohort)
        for cohort in ("synthetic", "simulated", "expertwritten")
    }
    runs["expertwritten"]["dataset_manifest_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="dataset manifest"):
        build_public_evidence(
            protocol=_protocol(),
            runs=runs,
            private_summary_hashes={cohort: "d" * 64 for cohort in runs},
        )


def test_reproduction_plan_freezes_all_three_cohorts_and_fixed_replay_label() -> None:
    args = build_parser().parse_args(
        [
            "--run-prefix",
            "repro-v1",
            "--embedding-cache",
            ".private/repro-v1/cache",
        ]
    )
    plan = command_plan(args)
    eval_commands = [command for command in plan if "scripts.eval_wixqa_retrieval" in command]
    assert len(eval_commands) == 3
    expert = next(command for command in eval_commands if "expertwritten" in command)
    assert "--consume-fixed-external" in expert
    assert plan[-1][plan[-1].index("--reproduction-metadata") + 1].endswith(
        "repro-v1-machine.json"
    )
    build = next(command for command in plan if "scripts.build_wixqa_index" in command)
    assert Path(build[build.index("--embedding-cache") + 1]) == Path(
        ".private/repro-v1/cache"
    )
    assert "--manifest" in build


def test_resume_safe_metrics_points_to_complete_v2_evidence() -> None:
    text = (ROOT / "docs" / "enterprise_eval" / "RESUME_SAFE_METRICS.md").read_text(
        encoding="utf-8"
    )
    assert "evidence/wixqa_retrieval_baseline_public_v2.json" in text
    assert "evidence/wixqa_retrieval_baseline_public_v1.json" not in text


def test_clean_root_preflight_rejects_existing_input(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    args = build_parser().parse_args(
        [
            "--run-prefix",
            "repro-v1",
            "--source-root",
            str(source),
            "--index-root",
            str(tmp_path / "index"),
            "--embedding-cache",
            str(tmp_path / "cache"),
            "--output-root",
            str(tmp_path / "runs"),
            "--require-clean-roots",
        ]
    )
    with pytest.raises(FileExistsError, match="source_root"):
        _verify_clean_roots(args)


def test_clean_reproduction_comparison_requires_exact_quality_and_clean_roots() -> None:
    historical = json.loads(
        (EVIDENCE / "wixqa_retrieval_baseline_public_v2.json").read_text(
            encoding="utf-8"
        )
    )
    candidate = json.loads(json.dumps(historical))
    candidate["reproduction_metadata"] = {
        "clean_reproduction": {
            "required": True,
            "historical_private_artifacts_used_as_input": False,
        }
    }
    result = compare_reproduction(
        historical,
        candidate,
        {"quality_absolute_tolerance": 0.0},
    )
    assert result["status"] == "VERIFIED"

    candidate["results"]["expertwritten_fixed_external"]["arms"]["dense"][
        "article_recall_at_5"
    ] -= 0.001
    result = compare_reproduction(
        historical,
        candidate,
        {"quality_absolute_tolerance": 0.0},
    )
    assert result["status"] == "REPRODUCTION_GAP"
    assert result["quality_difference_count"] == 1


def test_transport_corrected_protocol_keeps_zero_quality_tolerance() -> None:
    contract = json.loads(
        (
            ROOT
            / "docs"
            / "reproduction"
            / "evidence"
            / "WIXQA_CLEAN_REPRODUCTION_PROTOCOL_V2.json"
        ).read_text(encoding="utf-8")
    )
    equivalence = json.loads(
        (
            ROOT
            / "docs"
            / "reproduction"
            / "evidence"
            / "WIXQA_SOURCE_TRANSPORT_EQUIVALENCE_V1.json"
        ).read_text(encoding="utf-8")
    )

    assert contract["quality_absolute_tolerance"] == 0.0
    assert contract["source_transport_boundary"][
        "official_raw_manifest_sha256"
    ] == "d325412340c110d3f76b832080c702978643d517e296c97bba1abc088ec65b1f"
    assert equivalence["canonical_equivalence"] is True
    assert all(item["canonical_rows_equal"] for item in equivalence["files"])
