from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import requests

from app.external_datasets.wixqa import (
    DEFAULT_WIXQA_MANIFEST,
    DEFAULT_WIXQA_ROOT,
    WIXQA_REVISION,
    load_wixqa_manifest,
    verify_wixqa_source,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and verify the pinned official WixQA dataset."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument("--offline-verify", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = args.source_root.resolve()
    manifest = load_wixqa_manifest(args.manifest)
    if args.offline_verify:
        verified = verify_wixqa_source(source_root, args.manifest)
        print(_summary(verified, source_root, action="verified"))
        return 0
    if source_root.exists() and not args.force:
        verified = verify_wixqa_source(source_root, args.manifest)
        print(_summary(verified, source_root, action="already_present_verified"))
        return 0

    source_root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".wixqa-download-", dir=source_root.parent))
    try:
        for item in manifest.files:
            target = stage / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            url = (
                "https://huggingface.co/datasets/Wix/WixQA/resolve/"
                f"{WIXQA_REVISION}/{item.path}?download=true"
            )
            with requests.get(url, stream=True, timeout=(15, 180)) as response:
                response.raise_for_status()
                with target.open("wb") as handle:
                    for block in response.iter_content(chunk_size=1024 * 1024):
                        if block:
                            handle.write(block)
        verify_wixqa_source(stage, args.manifest)
        if source_root.exists():
            if not args.force:
                raise FileExistsError(f"WixQA source root exists: {source_root}")
            shutil.rmtree(source_root)
        stage.replace(source_root)
        verified = verify_wixqa_source(source_root, args.manifest)
        print(_summary(verified, source_root, action="downloaded_verified"))
        return 0
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _summary(manifest, source_root: Path, *, action: str) -> str:
    return json.dumps(
        {
            "action": action,
            "dataset": manifest.dataset_name,
            "source_commit": manifest.source_commit,
            "source_root": str(source_root),
            "documents": manifest.number_of_documents,
            "questions": manifest.number_of_questions,
            "verified_files": len(manifest.files),
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())

