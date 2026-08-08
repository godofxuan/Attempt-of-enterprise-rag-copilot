from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.external_datasets.wixqa import (
    WIXQA_REVISION,
    load_wixqa_articles,
    load_wixqa_manifest,
    load_wixqa_questions,
    question_ids_sha256,
    validate_wixqa_references,
)


ROOT = Path(__file__).resolve().parents[2]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> Path:
    _write_jsonl(
        tmp_path / "wix_kb_corpus" / "wix_kb_corpus.jsonl",
        [
            {
                "id": "a-1",
                "url": "https://example.test/a-1",
                "contents": "First article contents.",
                "title": "First article",
                "html_content": "<h2>First article</h2><ol><li>Step</li></ol>",
                "article_type": "article",
            },
            {
                "id": "a-2",
                "url": "https://example.test/a-2",
                "contents": "Second article contents.",
                "title": "Second article",
                "html_content": "<h2>Second article</h2>",
                "article_type": "known_issue",
            },
        ],
    )
    _write_jsonl(
        tmp_path / "wixqa_simulated" / "test.jsonl",
        [
            {
                "question": "How do I do both things?",
                "answer": "Use both articles.",
                "article_ids": ["a-1", "a-2"],
            }
        ],
    )
    return tmp_path


def test_public_manifest_is_pinned_and_content_addressed() -> None:
    manifest = load_wixqa_manifest(ROOT / "data_manifests" / "WIXQA_MANIFEST.json")
    assert manifest.source_commit == WIXQA_REVISION
    assert manifest.number_of_documents == 6221
    assert manifest.number_of_questions["expertwritten"] == 200
    assert {item.role for item in manifest.files} == {
        "corpus",
        "development",
        "validation",
        "fixed_external",
    }


def test_adapter_preserves_native_identity_and_derives_stable_question_id(
    tmp_path: Path,
) -> None:
    source = _fixture(tmp_path)
    articles = load_wixqa_articles(source)
    first = load_wixqa_questions("simulated", source)
    second = load_wixqa_questions("simulated", source)
    assert [item.question_id for item in first] == [item.question_id for item in second]
    assert first[0].id_origin == "derived_from_canonical_source_row_v1"
    assert articles[0].source_native_id == "a-1"
    assert articles[0].raw_provenance.source_revision == WIXQA_REVISION
    assert articles[0].source_metadata["article_type"] == "article"
    validate_wixqa_references(articles, first)
    assert question_ids_sha256(first) == question_ids_sha256(second)


def test_unknown_gold_article_is_rejected(tmp_path: Path) -> None:
    source = _fixture(tmp_path)
    questions = load_wixqa_questions("simulated", source)
    questions[0] = questions[0].model_copy(update={"article_ids": ["missing"]})
    with pytest.raises(ValueError, match="unknown articles"):
        validate_wixqa_references(load_wixqa_articles(source), questions)


def test_derived_id_is_not_a_source_row_number(tmp_path: Path) -> None:
    source = _fixture(tmp_path)
    question = load_wixqa_questions("simulated", source)[0]
    expected_hash = hashlib.sha256(
        (json.dumps(
            {
                "answer": "Use both articles.",
                "article_ids": ["a-1", "a-2"],
                "question": "How do I do both things?",
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n").encode("utf-8")
    ).hexdigest()
    assert question.question_id == f"wixqa:simulated:{expected_hash[:24]}"
