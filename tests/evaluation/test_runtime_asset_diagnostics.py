import hashlib
import json

import faiss
import numpy as np
import pytest

from scripts import diagnose_runtime_assets as diagnostics
from scripts.diagnose_runtime_assets import (
    MIB,
    budget,
    coverage,
    full_reference,
    read_index,
    records,
    subset,
    tie_probe,
)


def test_budget_rejects_oom_and_caps_storage():
    assert budget(100000, 1024, 8 * 1024 * MIB)["allowed"]
    assert not budget(100000, 1024, 500 * MIB)["allowed"]
    assert not budget(140000, 1024, 8 * 1024 * MIB)["allowed"]
    with pytest.raises(ValueError):
        budget(100, 2048, 8 * 1024 * MIB)


@pytest.mark.parametrize("visible", [[], [0], [2, 3], [0, 1, 2, 3]])
@pytest.mark.parametrize("k", [2, 20])
def test_exact_subset_matches_full_including_ties_and_empty(visible, k):
    index = faiss.IndexFlatIP(2)
    index.add(np.array([[1, 0], [0, 1], [1, 0], [-1, 0]], dtype=np.float32))
    query = np.array([[1, 0]], dtype=np.float32)
    ids = np.array(visible, dtype=np.int64)
    assert subset(index, query, ids, k) == full_reference(index, query, ids, k)


def test_top_one_tie_is_a_known_negative_not_semantic_equivalence():
    index = faiss.IndexFlatIP(2)
    index.add(np.array([[1, 0], [0, 1], [1, 0], [-1, 0]], dtype=np.float32))
    query = np.array([[1, 0]], dtype=np.float32)
    ids = np.arange(4, dtype=np.int64)
    assert full_reference(index, query, ids, 1) == [(2, 1.0)]
    assert subset(index, query, ids, 1) == [(0, 1.0)]


def test_top_twenty_boundary_tie_rejects_drop_in():
    result = tie_probe()
    assert result["ordered_equal"] is False
    assert result["decision"] == "REJECTED_AS_DROP_IN"
    assert result["full"][0][0] == 31
    assert result["subset"][0][0] == 19


def test_unicode_index_read_without_copy(tmp_path):
    path = tmp_path / "\u7d22\u5f15.index"
    index = faiss.IndexFlatIP(2)
    index.add(np.array([[1, 0]], dtype=np.float32))
    path.write_bytes(faiss.serialize_index(index).tobytes())
    loaded = read_index(path)
    assert loaded.ntotal == 1
    np.testing.assert_array_equal(loaded.reconstruct(0), [1, 0])


def test_fresh_index_object_does_not_reuse_previous_version():
    query = np.array([[1, 0]], dtype=np.float32)
    ids = np.array([0, 1], dtype=np.int64)
    first, second = faiss.IndexFlatIP(2), faiss.IndexFlatIP(2)
    first.add(np.array([[1, 0], [0, 1]], dtype=np.float32))
    second.add(np.array([[0, 1], [1, 0]], dtype=np.float32))
    assert subset(first, query, ids, 1)[0][0] == 0
    assert subset(second, query, ids, 1)[0][0] == 1


def test_coverage_does_not_emit_text_or_assume_ocr():
    rows = [
        {
            "text": "PRIVATE_DOCUMENT",
            "format": "pdf",
            "parser_name": "SECRET_PARSER",
            "parse_warnings": [{"code": "empty_page", "message": "PRIVATE_WARNING"}],
            "sections": [{"text": "ok", "locator": {"kind": "page", "start": 1}}],
            "tables": [{"headers": ["PRIVATE_HEADER"]}],
        }
    ]
    result = coverage(rows, "documents")
    assert result["counts"]["documents_with_warnings"] == 1
    assert result["counts"]["tables"] == 1
    assert result["counts"]["nonempty_page_sections"] == 1
    assert result["warning_codes"] == {"empty_page": 1}
    assert "scan_and_ocr_coverage" in result["unknown"]
    assert "PRIVATE" not in json.dumps(result)
    assert "SECRET" not in json.dumps(result)


def test_missing_fields_remain_unknown():
    result = coverage([{"text": "body"}], "chunks")
    assert result["locators"] == {"unknown": 1}
    assert result["formats"] == {"unknown": 1}


def test_production_coverage_checks_manifest_and_never_searches(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "ROOT", tmp_path)
    monkeypatch.setattr(diagnostics, "compare", lambda *args: pytest.fail("Unexpected search"))
    base = tmp_path / "data/indexes_v2"
    version = base / "versions/fixture"
    version.mkdir(parents=True)
    artifacts = []
    for name in ("documents.json", "chunks.json"):
        path = version / name
        path.write_text('[{"format":"jsonl","text":"private"}]', encoding="utf-8")
        artifacts.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = version / "manifest.json"
    manifest.write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
    active = base / "active.json"
    active.write_text(
        json.dumps(
            {
                "run_id": "fixture",
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    result = diagnostics.production_coverage()
    assert result["coverage"]["documents.json"]["formats"] == {"jsonl": 1}
    assert "private" not in json.dumps(result)
    (version / "chunks.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="record hash mismatch"):
        diagnostics.production_coverage()


def test_recorded_page_union_is_not_raw_pdf_denominator():
    row = {
        "format": "pdf",
        "text": "body",
        "sections": [
            {"text": "heading\nbody\nfooter", "locator": {"kind": "page", "start": n}}
            for n in (1, 2, 3)
        ],
        "parse_warnings": [{"code": "empty_page", "locator": {"kind": "page", "start": 5}}],
    }
    result = coverage([row], "documents")
    assert result["counts"]["recorded_distinct_pages"] == 4
    assert result["counts"]["recorded_distinct_text_pages"] == 3
    assert result["counts"]["recorded_distinct_empty_warning_pages"] == 1
    assert result["counts"]["recorded_page_number_gaps"] == 1
    assert result["counts"]["documents_with_repeated_boundary_candidates"] == 1
    assert result["counts"]["repeated_boundary_candidate_occurrences"] == 6
    assert "raw_page_denominator" in result["unknown"]


@pytest.mark.parametrize("suffix", [".json", ".jsonl"])
def test_bounded_reader(tmp_path, suffix):
    expected = [{"text": "x" * 70000}, {"text": "two"}]
    path = tmp_path / ("documents" + suffix)
    data = json.dumps(expected) if suffix == ".json" else "\n".join(map(json.dumps, expected))
    path.write_text(data, encoding="utf-8")
    assert list(records(path)) == expected


@pytest.mark.parametrize("data", ['[{"text":1}', "[{},]", "[{}] trailing", "{}"])
def test_invalid_array_fails_closed(tmp_path, data):
    path = tmp_path / "documents.json"
    path.write_text(data, encoding="utf-8")
    with pytest.raises(ValueError):
        list(records(path))
