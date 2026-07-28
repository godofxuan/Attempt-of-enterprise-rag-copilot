import pytest

from app.domain.documents import SourceLocator
from app.domain.queries import SearchHit
from app.evaluation.page_retrieval import PageReference, score_page_retrieval


def _hit(
    rank: int,
    *,
    doc_id: str = "doc-a",
    page_number: int | None = 1,
    locator_kind: str = "page",
) -> SearchHit:
    locator = (
        None
        if page_number is None
        else SourceLocator(
            kind=locator_kind,
            start=page_number,
            end=page_number,
            label=f"{locator_kind} {page_number}",
        )
    )
    return SearchHit(
        index_run_id="index-v1",
        chunk_id=f"chunk-{rank}",
        doc_id=doc_id,
        source_path=f"{doc_id}.pdf",
        section_path=[f"Page {page_number or 1}"],
        locator=locator,
        matched_text=f"matched text {rank}",
        context_text=f"context text {rank}",
        tenant_id="financebench-public",
        region="global",
        acl_groups=["public_benchmark"],
        version_id=f"{doc_id}-version",
        version="2022",
        status="active",
        authority_level=100,
        variant="authoritative",
        fused_score=1.0 / rank,
    )


def test_page_retrieval_scores_unique_doc_page_pairs_at_each_cutoff() -> None:
    score = score_page_retrieval(
        case_id="fb-1",
        hits=[
            _hit(1, page_number=2),
            _hit(2, page_number=9),
            _hit(3, page_number=4),
            _hit(4, page_number=2),
            _hit(5, doc_id="doc-b", page_number=1),
        ],
        gold_pages=[
            PageReference(doc_id="doc-a", page_number=2),
            PageReference(doc_id="doc-a", page_number=4),
        ],
    )

    assert score.passed_at_max_cutoff is True
    assert score.failure_codes == []
    assert [(item.doc_id, item.page_number) for item in score.ranked_pages] == [
        ("doc-a", 2),
        ("doc-a", 9),
        ("doc-a", 4),
        ("doc-b", 1),
    ]
    assert score.ranked_pages[0].chunk_ids == ["chunk-1", "chunk-4"]
    assert score.cutoffs[0].page_recall == 0.5
    assert score.cutoffs[0].page_precision == 1.0
    assert score.cutoffs[1].page_recall == 1.0
    assert score.cutoffs[1].page_precision == pytest.approx(2 / 3)
    assert score.cutoffs[2].page_recall == 1.0
    assert score.cutoffs[2].page_precision == 0.5
    assert score.cutoffs[2].page_locator_coverage == 1.0


def test_page_retrieval_fails_closed_for_unscorable_locator() -> None:
    score = score_page_retrieval(
        case_id="fb-2",
        hits=[
            _hit(1, page_number=2),
            _hit(2, page_number=10, locator_kind="character"),
        ],
        gold_pages=[PageReference(doc_id="doc-a", page_number=2)],
        cutoffs=(1, 2),
    )

    assert score.cutoffs[-1].page_recall == 1.0
    assert score.cutoffs[-1].page_locator_coverage == 0.5
    assert score.passed_at_max_cutoff is False
    assert score.failure_codes == ["unscorable_page_locator"]


def test_page_retrieval_reports_no_hits_and_missing_gold_page() -> None:
    score = score_page_retrieval(
        case_id="fb-3",
        hits=[],
        gold_pages=[PageReference(doc_id="doc-a", page_number=2)],
    )

    assert score.passed_at_max_cutoff is False
    assert score.failure_codes == [
        "no_retrieval_hits",
        "unscorable_page_locator",
        "gold_pages_missing",
    ]
    assert score.cutoffs[-1].page_precision == 0.0
    assert score.cutoffs[-1].page_locator_coverage == 0.0


@pytest.mark.parametrize(
    "cutoffs",
    [
        (),
        (3, 1),
        (1, 1),
        (0, 1),
        (True, 3),
    ],
)
def test_page_retrieval_rejects_invalid_cutoffs(cutoffs) -> None:
    with pytest.raises(ValueError, match="cutoffs"):
        score_page_retrieval(
            case_id="fb-4",
            hits=[_hit(1)],
            gold_pages=[PageReference(doc_id="doc-a", page_number=1)],
            cutoffs=cutoffs,
        )
