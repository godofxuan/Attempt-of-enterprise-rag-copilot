"""Load retrieval dependencies only for tests that request retrieval fixtures."""

import pytest


@pytest.fixture
def chunk_factory():
    from tests.retrieval.conftest import chunk_factory as implementation

    return implementation.__wrapped__()


@pytest.fixture
def document_factory():
    from tests.retrieval.conftest import document_factory as implementation

    return implementation.__wrapped__()


@pytest.fixture
def snapshot_factory(tmp_path):
    from tests.retrieval.conftest import snapshot_factory as implementation

    return implementation.__wrapped__(tmp_path)


__all__ = ["chunk_factory", "document_factory", "snapshot_factory"]
