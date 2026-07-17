from __future__ import annotations

from pathlib import Path

import pytest

from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile


ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"


@pytest.fixture(scope="session")
def evaluation_corpus_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("e4-evaluation-corpus")
    write_corpus(path, load_facts(FACTS), load_profile(PROFILE))
    return path
