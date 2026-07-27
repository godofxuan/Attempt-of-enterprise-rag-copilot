from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import BASE_DIR
from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from app.indexing.store import build_index_version, load_index_version
from app.ingestion.chunking import ChunkerConfig
from app.security.demo_identity import initialize_demo_identity


FACTS = BASE_DIR / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = BASE_DIR / "data" / "v2" / "config" / "demo.json"
STARTED_AT = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)


def _embed(text: str, *, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [float(digest[index] + 1) for index in range(dimension)]


def create_smoke_fixture(root: Path) -> dict[str, object]:
    target = Path(os.path.abspath(root))
    if target.exists() and any(target.iterdir()):
        raise FileExistsError("deployment smoke fixture root must be empty")
    target.mkdir(parents=True, exist_ok=True)
    data_root = target / "data"
    identity_root = target / "identity"
    corpus_root = target / "corpus"
    index_root = data_root / "indexes_v2"

    write_corpus(corpus_root, load_facts(FACTS), load_profile(PROFILE))
    for offset, run_id, dimension, activate in (
        (0, "deployment-smoke-index-v1", 8, True),
        (2, "deployment-smoke-index-v2", 7, False),
    ):
        build_index_version(
            root=index_root,
            input_dir=corpus_root,
            run_id=run_id,
            chunker_config=ChunkerConfig(
                mode="fixed",
                chunk_size=500,
                overlap=80,
            ),
            embedding_model="deployment-smoke-embed",
            embed_text=lambda text, size=dimension: _embed(
                text,
                dimension=size,
            ),
            activate=activate,
            started_at=STARTED_AT + timedelta(seconds=offset),
            finished_at=STARTED_AT + timedelta(seconds=offset + 1),
        )

    initialize_demo_identity(
        identity_root,
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        token_lifetime_seconds=900,
    )
    versions = {}
    for run_id in ("deployment-smoke-index-v1", "deployment-smoke-index-v2"):
        loaded = load_index_version(index_root, run_id)
        versions[run_id] = {
            "embedding_dimension": loaded.manifest.embedding.dimension,
            "manifest_sha256": loaded.manifest_sha256,
        }
    return {
        "data_root": str(data_root),
        "identity_root": str(identity_root),
        "index_root": str(index_root),
        "versions": versions,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create private, deterministic container smoke fixtures."
    )
    parser.add_argument("--root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = create_smoke_fixture(args.root)
    except (FileExistsError, PermissionError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["build_parser", "create_smoke_fixture", "main"]
