import json
from pathlib import Path

import pytest

from scripts import prepare_finqa


def test_test_download_requires_existing_frozen_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def download(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("download must not start")

    monkeypatch.setattr(prepare_finqa, "download_finqa_split", download)

    with pytest.raises(ValueError, match="frozen protocol"):
        prepare_finqa.main(
            [
                "--split",
                "test",
                "--execute-frozen-test-download",
                "--freeze-protocol",
                str(tmp_path / "missing.json"),
            ]
        )

    assert called is False


def test_test_download_rejects_draft_protocol_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"status": "DRAFT"}), encoding="utf-8")
    monkeypatch.setattr(
        prepare_finqa,
        "download_finqa_split",
        lambda **kwargs: pytest.fail("download must not start"),
    )

    with pytest.raises(ValueError, match="frozen protocol"):
        prepare_finqa.main(
            [
                "--split",
                "test",
                "--execute-frozen-test-download",
                "--freeze-protocol",
                str(protocol),
            ]
        )
