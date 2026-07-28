import json
import hashlib
from pathlib import Path

import pytest

from app.external_datasets import finqa
from app.external_datasets.finqa import (
    build_finqa_evidence_units,
    download_finqa_split,
    load_finqa_split,
    stable_sample_finqa_cases,
    table_row_to_text,
)


def _case(case_id: str = "report.pdf-1") -> dict:
    return {
        "pre_text": ["Revenue increased during the year."],
        "post_text": ["The company expects continued growth."],
        "filename": "report.pdf",
        "table_ori": [
            ["", "2023", "2022"],
            ["Revenue", "120", "100"],
        ],
        "table": [
            ["", "2023", "2022"],
            ["Revenue", "120", "100"],
        ],
        "qa": {
            "question": "What was the revenue growth rate?",
            "answer": "20%",
            "explanation": "",
            "ann_table_rows": [1],
            "ann_text_rows": [],
            "steps": [],
            "program": "divide(20, 100)",
            "gold_inds": {
                "table_1": (
                    "the Revenue of 2023 is 120 ; "
                    "the Revenue of 2022 is 100 ;"
                )
            },
            "exe_ans": 0.2,
            "tfidftopn": {},
            "program_re": "divide(20, 100)",
            "model_input": [],
        },
        "id": case_id,
        "table_retrieved": [],
        "text_retrieved": [],
        "table_retrieved_all": [],
        "text_retrieved_all": [],
    }


def _write(path: Path, payload: object) -> str:
    content = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    path.write_bytes(content)

    return hashlib.sha256(content).hexdigest()


def test_finqa_loader_validates_hash_schema_and_gold_alignment(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dev.json"
    digest = _write(path, [_case()])

    cases, actual_digest = load_finqa_split(path, expected_sha256=digest)

    assert actual_digest == digest
    assert cases[0].qa.exe_ans == 0.2
    assert [unit.unit_id for unit in build_finqa_evidence_units(cases[0])] == [
        "text_0",
        "text_1",
        "table_0",
        "table_1",
    ]


def test_finqa_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "dev.json"
    path.write_text('[{"id":"one","id":"two"}]', encoding="utf-8")

    with pytest.raises(ValueError, match="canonical UTF-8 JSON"):
        load_finqa_split(path)


def test_finqa_loader_rejects_mismatched_gold_text(tmp_path: Path) -> None:
    payload = _case()
    payload["qa"]["gold_inds"]["table_1"] = "label-leaking row text"
    path = tmp_path / "dev.json"
    _write(path, [payload])

    with pytest.raises(ValueError, match="does not match source units"):
        load_finqa_split(path)


def test_finqa_loader_rejects_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "dev.json"
    _write(path, [_case()])

    with pytest.raises(ValueError, match="pinned FinQA split hash mismatch"):
        load_finqa_split(path, expected_sha256="0" * 64)


def test_finqa_stable_sample_is_order_independent(tmp_path: Path) -> None:
    path = tmp_path / "dev.json"
    _write(path, [_case("case-3"), _case("case-1"), _case("case-2")])
    cases, _ = load_finqa_split(path)

    selected = stable_sample_finqa_cases(cases, count=2, seed="finqa-dev-v1")
    reversed_selected = stable_sample_finqa_cases(
        list(reversed(cases)),
        count=2,
        seed="finqa-dev-v1",
    )

    assert [case.id for case in selected] == [
        case.id for case in reversed_selected
    ]


def test_table_row_to_text_matches_corrected_upstream_template() -> None:
    assert table_row_to_text(
        ["", "2023", "2022"],
        ["Revenue", "$120", "$100"],
    ) == (
        "the Revenue of 2023 is $120 ; "
        "the Revenue of 2022 is $100 ;"
    )


def test_finqa_downloader_is_hash_pinned_and_test_requires_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = json.dumps([_case()], ensure_ascii=True).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(finqa, "FINQA_DEV_SHA256", digest)

    class Response:
        is_redirect = False

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            assert chunk_size == 1024 * 1024
            yield content[:10]
            yield content[10:]

    class Session:
        trust_env = True

        def get(self, url: str, **kwargs):
            assert url.endswith("/dataset/dev.json")
            assert kwargs["allow_redirects"] is False
            return Response()

    target, actual_digest, byte_count = download_finqa_split(
        split="dev",
        source_root=tmp_path,
        session=Session(),
    )

    assert target.read_bytes() == content
    assert actual_digest == digest
    assert byte_count == len(content)
    with pytest.raises(ValueError, match="explicit confirmation"):
        download_finqa_split(split="test", source_root=tmp_path)
