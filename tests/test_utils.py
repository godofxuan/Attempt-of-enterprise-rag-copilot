from pathlib import Path
from types import SimpleNamespace

from app import utils


def test_bm25_tokenizer_configures_jieba_cache_outside_os_temp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_cache = tmp_path / "private-runtime"
    monkeypatch.setattr(
        utils,
        "get_settings",
        lambda: SimpleNamespace(runtime_cache_dir=runtime_cache),
    )
    monkeypatch.setattr(utils, "_JIEBA_CACHE_CONFIGURED", False)
    monkeypatch.setattr(utils.jieba.dt, "tmp_dir", None)
    monkeypatch.setattr(utils.jieba, "lcut", lambda text: text.split())

    assert utils.tokenize_for_bm25("one two") == ["one", "two"]
    assert utils.jieba.dt.tmp_dir == str((runtime_cache / "jieba").resolve())
    assert (runtime_cache / "jieba").is_dir()
