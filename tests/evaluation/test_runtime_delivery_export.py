import json
from pathlib import Path

import pytest

from scripts.export_runtime_delivery import digest, load_run, paired, percentile, public_row


def test_public_row_excludes_prompt_answer_sources_and_server_text():
    sentinel = "PRIVATE_SENTINEL_NEVER_EXPORT"
    checks = {
        key: 0
        for key in (
            "fact_count",
            "matched_facts",
            "citation_references",
            "invalid_references",
            "forbidden_publication_count",
            "unsafe_tool_calls",
            "unauthorized_sources",
        )
    }
    checks.update(
        contract_complete=True, mode_ok=True, source_complete=True, known_security_failure=False
    )
    row = dict(
        case_id="case-a",
        category="fact",
        kind="main",
        profile="hybrid_default",
        repeat=0,
        http_status=200,
        client_ms=10,
        score=checks,
        response={
            "mode": "answered",
            "answer": sentinel,
            "sources": [{"preview": sentinel}],
            "trace": {"raw": sentinel},
        },
        server_trace={"raw": sentinel},
    )
    exported = public_row(row, "run-a")
    assert sentinel not in json.dumps(exported)
    assert exported["source_count"] == 1
    assert exported["checks"]["contract_complete"] is True


def test_empty_latency_is_unknown_not_zero():
    assert percentile([], 0.95) is None
    assert percentile([10, 20], 0.95) == 19.5


def test_repair_pair_requires_the_same_case_repeat_keys():
    def row(run, case):
        return dict(
            run_id=run,
            profile="hybrid_default",
            kind="main",
            case_id=case,
            repeat=0,
            checks={"contract_complete": True},
        )

    with pytest.raises(ValueError, match="cohort mismatch"):
        paired([row("before", "a"), row("after", "b")])


def test_tampered_private_rows_cannot_be_exported(tmp_path):
    (tmp_path / "completion.json").write_text(
        json.dumps(
            {
                "status": "COMPLETE",
                "source_unchanged": True,
                "rows_sha256": "0" * 64,
            }
        )
    )
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "rows.jsonl").write_text("tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_run(tmp_path)


def test_public_service_packet_hashes_counts_and_comparison_are_consistent():
    root = Path(__file__).resolve().parents[2] / "docs/review/runtime_delivery_20260905"
    manifest = json.loads((root / "manifest.json").read_bytes())
    for name, expected in manifest["artifacts"].items():
        assert digest(root / name) == expected
    rows = json.loads((root / "service_cases.json").read_bytes())["rows"]
    assert len(rows) == 775
    assert sum(row["kind"] == "main" for row in rows) == 680
    assert sum(row["kind"] == "warmup" for row in rows) == 35
    assert sum(row["kind"].startswith("resource") for row in rows) == 60
    assert all("answer" not in row and "sources" not in row for row in rows)
    pair_rows = [r for r in rows if r["run_id"] != "service_C_readiness_v1"]
    assert paired(pair_rows) == json.loads((root / "service_comparison.json").read_bytes())


def test_public_retrieval_arithmetic_uses_all_800_rows():
    root = Path(__file__).resolve().parents[2] / "docs/review/runtime_delivery_20260905"
    evidence = json.loads((root / "retrieval_evidence.json").read_bytes())
    assert len(evidence["rows"]) == 800
    assert len({(r["question_id"], r["profile"]) for r in evidence["rows"]}) == 800
    for profile, summary in evidence["summary"].items():
        rows = [r for r in evidence["rows"] if r["profile"] == profile]
        assert len(rows) == 200
        for key in rows[0]["metrics"]:
            assert sum(r["metrics"][key] for r in rows) / 200 == pytest.approx(summary[key])
        assert not any("question" in r or "text" in r for r in rows)
