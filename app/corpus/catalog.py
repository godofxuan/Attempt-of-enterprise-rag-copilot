from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.corpus.generator import load_facts, load_profile
from app.corpus.schemas import CompanyFacts, CorpusProfile


ROOT = Path(__file__).resolve().parents[2]
FACTS_DIR = ROOT / "data" / "v2" / "facts"
CONFIG_DIR = ROOT / "data" / "v2" / "config"


@dataclass(frozen=True)
class CorpusPreset:
    profile_id: str
    facts_file: str
    profile_file: str


CORPUS_PRESETS = {
    "demo": CorpusPreset(
        profile_id="demo",
        facts_file="company_facts_v1.json",
        profile_file="demo.json",
    ),
    "benchmark": CorpusPreset(
        profile_id="benchmark",
        facts_file="company_facts_v1.json",
        profile_file="benchmark.json",
    ),
    "expanded": CorpusPreset(
        profile_id="expanded",
        facts_file="company_facts_v2.json",
        profile_file="expanded.json",
    ),
    "expanded_benchmark": CorpusPreset(
        profile_id="expanded_benchmark",
        facts_file="company_facts_v2.json",
        profile_file="expanded_benchmark.json",
    ),
}
CORPUS_PROFILE_IDS = tuple(CORPUS_PRESETS)


def load_corpus_preset(
    profile_id: str,
) -> tuple[CompanyFacts, CorpusProfile]:
    try:
        preset = CORPUS_PRESETS[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown corpus profile {profile_id!r}") from exc
    facts = load_facts(FACTS_DIR / preset.facts_file)
    profile = load_profile(CONFIG_DIR / preset.profile_file)
    if profile.profile_id != preset.profile_id:
        raise ValueError(
            f"profile file declares {profile.profile_id!r}, "
            f"expected {preset.profile_id!r}"
        )
    return facts, profile
