import pytest

from app.ingestion.chunking import ChunkerConfig
from scripts.check_document_quality import check_corpus
from tests.indexing.test_builder import build_corpus


def test_preflight_reports_every_document_and_does_not_publish(tmp_path):
    corpus = build_corpus(tmp_path / "corpus")
    report = check_corpus(corpus, tmp_path / "reports", ChunkerConfig(mode="structure"))
    assert report["status"] == "PREFLIGHT_PASS"
    assert report["document_count"] == report["accepted"] == 72
    assert report["published"] is False
    assert not list(tmp_path.rglob("active.json"))
    with pytest.raises(FileExistsError):
        check_corpus(corpus, tmp_path / "reports", ChunkerConfig(mode="structure"))


def test_tampered_source_is_rejected_without_hiding_other_documents(tmp_path):
    import json

    corpus = build_corpus(tmp_path / "corpus")
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    (corpus / manifest["documents"][0]["path"]).write_text("changed", encoding="utf-8")
    report = check_corpus(corpus, tmp_path / "reports", ChunkerConfig(mode="structure"))
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["accepted"] == 71
    assert report["reports"][0]["status"] == "REJECT"
