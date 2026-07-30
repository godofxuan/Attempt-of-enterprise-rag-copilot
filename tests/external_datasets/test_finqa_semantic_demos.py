from __future__ import annotations

import hashlib
import json

import pytest

from app.external_datasets import finqa_semantic_demos
from app.external_datasets.finqa_semantic_demos import (
    FinQADemoSource,
    FinQAStructuralDemoIndex,
    download_finqa_train_for_demos,
)


def _case(index: int) -> FinQADemoSource:
    return FinQADemoSource(
        case_id=f"train-{index}",
        question=(
            f"What was the percentage change in revenue {index} "
            "from 2019 to 2020?"
        ),
        program="subtract(10, 5), divide(#0, 5)",
    )


def test_dynamic_demo_index_returns_value_free_train_templates() -> None:
    index = FinQAStructuralDemoIndex(
        [_case(item) for item in range(120)],
        forbidden_case_ids={"calibration-1"},
    )

    demos = index.retrieve(
        "What was the percentage change in revenue from 2018 to 2019?",
        top_k=3,
    )

    assert index.demo_count == 120
    assert len(demos) == 3
    assert all("<NUM>" in demo.question_template for demo in demos)
    assert all("train-" not in demo.question_template for demo in demos)
    assert [step.operation for step in demos[0].skeleton.steps] == [
        "SUB",
        "DIV",
    ]


def test_dynamic_demo_index_rejects_source_overlap() -> None:
    cases = [_case(item) for item in range(120)]

    with pytest.raises(ValueError, match="isolation"):
        FinQAStructuralDemoIndex(
            cases,
            forbidden_case_ids={cases[0].case_id},
        )


def test_train_demo_downloader_is_hash_pinned(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = json.dumps([{"id": "train-1"}]).encode("utf-8")
    expected = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        finqa_semantic_demos,
        "FINQA_TRAIN_SHA256",
        expected,
    )

    class Response:
        is_redirect = False

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            assert chunk_size == 1024 * 1024
            yield content

    class Session:
        trust_env = True

        def get(self, url: str, **kwargs):
            assert url.endswith("/dataset/train.json")
            assert kwargs["allow_redirects"] is False
            return Response()

    target, actual, byte_count = download_finqa_train_for_demos(
        source_root=tmp_path,
        session=Session(),
    )

    assert target.name == "train.json"
    assert actual == expected
    assert byte_count == len(content)
