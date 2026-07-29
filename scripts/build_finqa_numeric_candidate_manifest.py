try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import os
from pathlib import Path

from app.external_datasets import finqa_typed_program
from app.external_datasets.finqa_typed_program import (
    NumericCandidateSource,
    build_numeric_candidate_manifest,
    extract_numeric_candidate_corpus,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    REPOSITORY_ROOT
    / "data"
    / "v2"
    / "public"
    / "finqa_numeric_candidates"
    / "source_fixture.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_numeric_candidate_manifest_v1.json"
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def build_manifest_bytes(source_path: Path) -> bytes:
    source_bytes = source_path.read_bytes()
    payload = json.loads(
        source_bytes.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, list) or not payload:
        raise ValueError("numeric candidate source must be a non-empty JSON list")
    sources = [
        NumericCandidateSource.model_validate(item)
        for item in payload
    ]
    corpus = extract_numeric_candidate_corpus(sources)
    manifest = build_numeric_candidate_manifest(
        corpus=corpus,
        source_artifact_sha256=hashlib.sha256(source_bytes).hexdigest(),
        extractor_source_sha256=hashlib.sha256(
            Path(finqa_typed_program.__file__).read_bytes()
        ).hexdigest(),
        source_record_count=len(sources),
        status="SYNTHETIC_CONTRACT_ONLY",
    )
    return _canonical_bytes(manifest.model_dump(mode="json"))


def _write_new_file(path: Path, content: bytes, *, replace: bool) -> None:
    path = path.resolve()
    if path.exists() and not replace:
        raise FileExistsError(f"candidate manifest already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build or verify the redacted FinQA numeric-candidate manifest "
            "from a deterministic source fixture."
        )
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    expected = build_manifest_bytes(args.source.resolve())
    output = args.output.resolve()
    if args.check:
        if not output.is_file():
            raise FileNotFoundError(f"candidate manifest is missing: {output}")
        if output.read_bytes() != expected:
            raise ValueError("candidate manifest does not match recomputed bytes")
        print(f"verified {output}")
        return 0
    _write_new_file(output, expected, replace=args.replace)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
