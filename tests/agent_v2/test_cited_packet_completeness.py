"""Packet completeness unit boundary; full raw replay separately covers delivery."""

from types import SimpleNamespace
import pytest
from app.agent.answer_publication import packet_incomplete_for_publication


@pytest.mark.parametrize(
    "cited_cut,explicit_read_cut,semantic,expected",
    [
        (False, False, True, False),
        (True, False, True, True),
        (False, True, True, True),
        (False, False, False, True),
    ],
)
def test_packet_omission_is_bound_to_actual_answer_dependencies(
    cited_cut, explicit_read_cut, semantic, expected
):
    source = SimpleNamespace(
        delivered=SimpleNamespace(citation_id="actually-cited"), packet_truncated=cited_cut
    )
    unused = SimpleNamespace(
        delivered=SimpleNamespace(citation_id="uncited-candidate"), packet_truncated=True
    )
    claim = SimpleNamespace(cited_chunk_ids=["actually-cited"])
    state = SimpleNamespace(
        analysis=SimpleNamespace(intent="process"),
        open_results=[SimpleNamespace(result=SimpleNamespace(truncated=True))]
        if explicit_read_cut
        else [],
    )
    trace = {
        "packet_drop_reasons": {"packet_budget": 1},
        "packet_truncation_reasons": {"packet_budget": 1},
        "packed_aspect_coverage": {"covered": 1, "required": 1},
        "generation_wire_protocol": "selected_source_units_only"
        if semantic
        else "legacy_answer_and_claims",
    }
    actual = packet_incomplete_for_publication(state, trace, [source, unused], [claim], semantic)
    assert actual == expected
    if semantic:
        assert trace["publication_packet_coverage"]["cited_source_count"] == 1
        assert trace["publication_packet_coverage"]["cited_truncated_count"] == int(cited_cut)
        assert trace["publication_packet_coverage"]["blocking_incomplete"] == expected
