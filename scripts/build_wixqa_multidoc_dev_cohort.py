from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.external_datasets.wixqa import (
    DEFAULT_WIXQA_MANIFEST,
    DEFAULT_WIXQA_ROOT,
    WIXQA_REVISION,
    canonical_json_bytes,
    load_wixqa_questions,
    verify_wixqa_source,
)


DEFAULT_OUTPUT = Path(
    "docs/rapid_upgrade/evidence/MULTIDOC_DEV_COHORT.json"
)


def build_cohort(
    *,
    source_root: Path = DEFAULT_WIXQA_ROOT,
    manifest_path: Path = DEFAULT_WIXQA_MANIFEST,
) -> dict:
    verify_wixqa_source(source_root, manifest_path)
    questions = [
        item
        for item in load_wixqa_questions("simulated", source_root)
        if len(item.article_ids) > 1
    ]
    records = [
        {
            "question_id": item.question_id,
            "raw_record_sha256": item.raw_record_sha256,
            "required_article_ids": item.article_ids,
            "required_source_count": len(item.article_ids),
            "source_row": item.source_row,
        }
        for item in questions
    ]
    question_ids = [item["question_id"] for item in records]
    manifest_sha256 = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    return {
        "schema_version": "wixqa_multidoc_dev_cohort_v1",
        "cohort_id": "wixqa-simulated-multidoc-retrospective-v1",
        "dataset": "WixQA",
        "dataset_revision": WIXQA_REVISION,
        "dataset_split": "simulated",
        "consumption": "RETROSPECTIVE_DEVELOPMENT_ONLY_ALREADY_OBSERVED",
        "claim_boundary": (
            "Development mechanism evidence only; not fresh validation, fixed test, "
            "or a resume quality claim."
        ),
        "dataset_manifest_sha256": manifest_sha256,
        "question_count": len(records),
        "question_ids_sha256": hashlib.sha256(
            canonical_json_bytes(question_ids)
        ).hexdigest(),
        "records_sha256": hashlib.sha256(
            canonical_json_bytes(records)
        ).hexdigest(),
        "records": records,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the hash-bound retrospective WixQA multi-document cohort."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_cohort(
        source_root=args.source_root,
        manifest_path=args.manifest,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
