from __future__ import annotations

from pathlib import Path

from app.evaluation.adaptive_retrieval_v3 import (
    EvidenceSufficiencyProposal,
    assessor_metrics,
    build_evidence_sufficiency_messages,
    gold_retrieval_sufficient,
    parse_evidence_sufficiency_response,
)
from scripts.eval_adaptive_retrieval_v3_assessor import _index_manifest_path


def test_sufficient_contract_rejects_missing_aspects() -> None:
    try:
        EvidenceSufficiencyProposal(
            verdict="sufficient",
            reason_code="all_requested_information_supported",
            missing_aspects=["approval owner"],
        )
    except ValueError as error:
        assert "no missing aspects" in str(error)
    else:
        raise AssertionError("invalid sufficient proposal was accepted")


def test_assessor_contract_has_no_rewrite_field() -> None:
    assessment = parse_evidence_sufficiency_response(
        '{"verdict":"insufficient","reason_code":"missing_required_information",'
        '"missing_aspects":["approval owner"]}'
    )
    assert assessment.status == "ok"
    assert assessment.proposal is not None
    assert assessment.proposal.missing_aspects == ["approval owner"]


def test_assessor_parser_rejects_extra_or_invalid_shape() -> None:
    assessment = parse_evidence_sufficiency_response(
        '{"verdict":"sufficient","reason_code":"all_requested_information_supported",'
        '"missing_aspects":[],"rewritten_query":"do not permit this"}'
    )
    assert assessment.status == "parse_error"


def test_messages_exclude_gold_and_mark_retrieval_as_untrusted() -> None:
    messages = build_evidence_sufficiency_messages(
        original_question="Where is the approval policy?",
        first_pass_query="Where is the approval policy?",
        admitted_evidence=[{"document_id": "article-1", "title": "Policy", "text": "Visible text"}],
        ledger_summary={"visible_evidence_count": 1, "guarded": True},
    )
    rendered = "\n".join(message["content"] for message in messages)
    assert "gold" not in rendered.casefold()
    assert "untrusted data" in rendered
    assert "rewrite the query" in rendered


def test_gold_retrieval_sufficiency_requires_every_gold_document() -> None:
    assert gold_retrieval_sufficient(["a", "b"], ["b", "a", "noise"])
    assert not gold_retrieval_sufficient(["a", "b"], ["a"])


def test_assessor_metrics_keep_unavailable_calls_out_of_confusion() -> None:
    metrics = assessor_metrics(
        [
            {"gold_retrieval_sufficient": False, "prediction": True},
            {"gold_retrieval_sufficient": False, "prediction": False},
            {"gold_retrieval_sufficient": True, "prediction": True},
            {"gold_retrieval_sufficient": True, "prediction": False},
            {"gold_retrieval_sufficient": False, "prediction": None},
        ]
    )
    assert metrics["available_assessment_count"] == 4
    assert metrics["unavailable_assessment_count"] == 1
    assert metrics["confusion"] == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_negative": 1,
    }
    assert metrics["retry_precision"] == 0.5
    assert metrics["retry_recall"] == 0.5


def test_index_manifest_path_keeps_run_id_inside_path_expression() -> None:
    path = _index_manifest_path(Path(".private/indexes"), "run-1")
    assert path.as_posix().endswith("versions/run-1/manifest.json")
