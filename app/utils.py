import re
from pathlib import Path

import jieba


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


def tokenize_for_bm25(text: str) -> list[str]:
    text = normalize_text(text)
    return [tok.strip() for tok in jieba.lcut(text) if tok.strip()]