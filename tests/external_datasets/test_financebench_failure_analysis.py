from types import SimpleNamespace

from app.domain.documents import SourceLocator
from app.external_datasets.financebench import FinanceBenchPreparedEvidence
from app.external_datasets.financebench_failure_analysis import (
    analyze_financebench_page_failures,
)
from app.external_datasets.financebench_page_eval import (
    FinanceBenchPageCaseResult,
)
from app.evaluation.page_retrieval import PageReference, score_page_retrieval

from .test_financebench_page_eval import _case, _evidence_case, _hit


def _detail(*, hits, ranked_doc_ids) -> FinanceBenchPageCaseResult:
    score = score_page_retrieval(
        case_id="fb-1",
        hits=hits,
        gold_pages=[PageReference(doc_id="doc-a", page_number=2)],
    )
    return FinanceBenchPageCaseResult(
        case_id="fb-1",
        ranked_doc_ids=ranked_doc_ids,
        document_recall_at_5=1.0 if "doc-a" in ranked_doc_ids else 0.0,
        page_score=score,
        passed=False,
        latency_ms=1.0,
    )


def _chunk(page: int, text: str):
    return SimpleNamespace(
        doc_id="doc-a",
        text=text,
        locator=SourceLocator(kind="page", start=page, end=page),
    )


def test_failure_analysis_separates_page_ranking_from_parser_quality() -> None:
    evidence = _evidence_case().model_copy(
        update={"answer": "$1.00", "question_type": "metrics-generated"}
    )

    summary, rows = analyze_financebench_page_failures(
        details=[
            _detail(
                hits=[_hit(1, doc_id="doc-a", page_number=90)],
                ranked_doc_ids=["doc-a"],
            )
        ],
        evidence_cases=[evidence],
        chunks=[_chunk(2, "Revenue was $1.00 in FY2022.")],
    )

    assert rows[0].primary_failure == "page_ranking_miss"
    assert rows[0].numeric_or_table_question is True
    assert rows[0].table_extraction_risk is False
    assert summary.low_extraction_recall_case_count == 0
    assert summary.parser_ablation_recommended is False


def test_failure_analysis_marks_missing_numeric_gold_page_as_table_risk() -> None:
    summary, rows = analyze_financebench_page_failures(
        details=[
            _detail(
                hits=[_hit(1, doc_id="doc-b", page_number=1)],
                ranked_doc_ids=["doc-b"],
            )
        ],
        evidence_cases=[_evidence_case()],
        chunks=[],
    )

    assert rows[0].primary_failure == "document_miss_top5"
    assert rows[0].extraction_signals[0].missing_from_index is True
    assert rows[0].table_extraction_risk is True
    assert summary.parser_ablation_recommended is True


def test_failure_analysis_detects_evidence_split_across_chunks() -> None:
    evidence = _evidence_case().model_copy(
        update={
            "evidence": [
                FinanceBenchPreparedEvidence(
                    doc_id="doc-a",
                    page_number=2,
                    evidence_text="alpha beta gamma delta epsilon zeta eta theta",
                    evidence_text_full_page=(
                        "alpha beta gamma delta epsilon zeta eta theta"
                    ),
                )
            ]
        }
    )

    summary, rows = analyze_financebench_page_failures(
        details=[
            _detail(
                hits=[_hit(1, doc_id="doc-a", page_number=90)],
                ranked_doc_ids=["doc-a"],
            )
        ],
        evidence_cases=[evidence],
        chunks=[
            _chunk(2, "alpha beta gamma delta"),
            _chunk(2, "epsilon zeta eta theta"),
        ],
    )

    assert rows[0].extraction_signals[0].chunk_boundary_risk is True
    assert summary.chunk_boundary_risk_case_count == 1
