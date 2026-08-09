from __future__ import annotations

from app.external_datasets.enterprise_rag_bench import EnterpriseRAGBenchQuestion
from scripts.analyze_enterprise_reused_source_ids import build_sensitivity


def test_record_aware_sensitivity_counts_duplicate_gold_records() -> None:
    reused = {
        "dsid_reused": [
            {"source_row": 1, "raw_record_sha256": "a" * 64},
            {"source_row": 2, "raw_record_sha256": "b" * 64},
        ]
    }
    question = EnterpriseRAGBenchQuestion(
        question_id="qst_fixture",
        question_type="conflicting_info",
        source_types=["jira"],
        question="Which approvals conflict?",
        expected_doc_ids=["dsid_reused", "dsid_reused"],
        gold_answer="Two records conflict.",
        answer_facts=["conflict"],
    )
    details = {
        "qst_fixture": {
            "question_id": "qst_fixture",
            "gold_document_count": 1,
            "recall_at_5": 1.0,
        }
    }
    hits = {
        "qst_fixture": [
            {
                "record_id": "record-a",
                "source_native_id": "dsid_reused",
            }
        ]
    }

    payload = build_sensitivity(
        reused_groups=reused,
        questions=[question],
        details_by_question=details,
        strict_hits_by_question=hits,
    )

    assert payload["affected_question_count"] == 1
    assert payload["affected_questions"][0]["record_aware_gold_count"] == 2
    assert payload["affected_questions"][0]["record_aware_recall_at_5"] == 0.5
    assert payload["record_aware_macro_recall_at_5"] == 0.5
