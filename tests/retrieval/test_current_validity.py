from datetime import UTC, date, datetime

import pytest

from app.domain.queries import QueryFilters
from app.retrieval import pipeline as module
from tests.retrieval.test_pipeline_ranking import search_request


class FixedUTC(datetime):
    @classmethod
    def now(cls, tz=None):
        assert tz is UTC
        return cls(2026, 9, 7, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(module, "datetime", FixedUTC, raising=False)


@pytest.mark.parametrize(
    "start,end,status,expected",
    [
        (date(2026, 9, 8), None, "active", False),
        (date(2026, 9, 7), None, "active", True),
        (date(2026, 1, 1), date(2026, 9, 7), "active", False),
        (date(2026, 1, 1), date(2026, 9, 6), "active", False),
        (date(2026, 1, 1), date(2026, 9, 8), "active", True),
        (date(2026, 1, 1), None, "retired", False),
    ],
)
def test_current_validity_before_ranking(
    chunk_factory, snapshot_factory, start, end, status, expected
):
    chunk = chunk_factory(effective_from=start, effective_to=end, status=status)
    pipeline = module.HybridRetrievalPipeline(snapshot_factory([chunk]))
    result = pipeline.search(search_request(query=chunk.text))
    assert bool(result.hits) is expected


@pytest.mark.parametrize("scope", ["all", "historical", "as_of"])
def test_explicit_temporal_scopes_unchanged(chunk_factory, scope):
    chunk = chunk_factory(
        effective_from=date(2027, 1, 1),
        effective_to=date(2027, 2, 1),
        status="retired",
    )
    filters = QueryFilters(
        temporal_scope=scope,
        **({"as_of": date(2027, 1, 1)} if scope == "as_of" else {}),
    )
    assert module._matches_filters(chunk, filters)


def test_as_of_end_remains_exclusive(chunk_factory):
    chunk = chunk_factory(effective_from=date(2026, 1, 1), effective_to=date(2027, 1, 1))
    assert not module._matches_filters(
        chunk, QueryFilters(temporal_scope="as_of", as_of=date(2027, 1, 1))
    )
