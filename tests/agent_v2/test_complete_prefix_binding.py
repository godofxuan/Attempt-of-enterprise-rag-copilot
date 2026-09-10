import pytest

from app.agent.citation_verifier import verify_claims
from app.domain.evidence import Claim
from tests.v2_test_support import admitted_search_hit

SOURCE = (
    "销售折扣审批制度\n版本号：2026.1。状态：当前生效。"
    "折扣超过8%需要销售经理审批。折扣超过15%需要总经理审批。"
)


@pytest.mark.parametrize(
    "quote",
    [
        "销售折扣审批制度\n版本号：2026.1。状态：当前生效。折扣超过8%需要销售经理审批。",
        SOURCE,
        "折扣超过8%需要销售经理审批。",
    ],
)
def test_complete_contiguous_prefix_has_bound_source_offsets(quote):
    evidence = admitted_search_hit(matched_text=SOURCE, context_text=SOURCE)
    claim = Claim(claim_id="c", text=quote, cited_chunk_ids=[evidence.hit.chunk_id])
    citation = verify_claims([claim], [evidence])[0]
    assert citation.supported
    assert citation.support_kind == "exact_span"
    span = citation.supporting_spans[0]
    assert SOURCE[span.start : span.end] == quote


@pytest.mark.parametrize(
    "quote",
    [
        "折扣需要销售经理审批。",
        "销售折扣审批制度\n版本号：2026.1。折扣超过8%需要销售经理审批。",
        "销售折扣审批制度\n版本号：2026.1。状态：当前生效。折扣超过8%",
    ],
)
def test_prefix_binding_never_skips_or_truncates_source_units(quote):
    evidence = admitted_search_hit(matched_text=SOURCE, context_text=SOURCE)
    citation = verify_claims(
        [Claim(claim_id="c", text=quote, cited_chunk_ids=[evidence.hit.chunk_id])], [evidence]
    )[0]
    assert not citation.supported
