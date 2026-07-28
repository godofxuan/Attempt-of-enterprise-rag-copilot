import re
import threading
from pathlib import Path

import jieba

from app.config import get_settings


_JIEBA_CACHE_LOCK = threading.Lock()
_JIEBA_CACHE_CONFIGURED = False


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _configure_jieba_cache() -> None:
    global _JIEBA_CACHE_CONFIGURED
    if _JIEBA_CACHE_CONFIGURED:
        return
    with _JIEBA_CACHE_LOCK:
        if _JIEBA_CACHE_CONFIGURED:
            return
        cache_dir = ensure_dir(
            Path(get_settings().runtime_cache_dir).resolve() / "jieba"
        )
        jieba.dt.tmp_dir = str(cache_dir)
        _JIEBA_CACHE_CONFIGURED = True


def tokenize_for_bm25(text: str) -> list[str]:
    _configure_jieba_cache()
    text = normalize_text(text)
    return [tok.strip() for tok in jieba.lcut(text) if tok.strip()]
