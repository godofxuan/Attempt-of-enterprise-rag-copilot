import json

import pytest

from scripts.export_runtime_delivery import load_run, paired, percentile, public_row


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
