from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


CONTENT_FILES = (
    "README.md",
    "index_manifest.json",
    "quality.json",
    "retrieval_dev_summary.json",
    "retrieval_test_summary.json",
    "verify.py",
)
PACKAGE_FILES = frozenset((*CONTENT_FILES, "checksums.sha256"))
CHECKSUM_PATTERN = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)")


def _load_json(package: Path, name: str) -> dict[str, Any]:
    payload = json.loads((package / name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return payload


def _verify_checksums(package: Path) -> None:
    actual_files = {
        item.name
        for item in package.iterdir()
        if item.is_file()
    }
    if actual_files != PACKAGE_FILES:
        raise ValueError(
            "unexpected package files: "
            f"expected {sorted(PACKAGE_FILES)}, got {sorted(actual_files)}"
        )

    rows = (package / "checksums.sha256").read_text(
        encoding="utf-8"
    ).splitlines()
    declared: dict[str, str] = {}
    for row in rows:
        match = CHECKSUM_PATTERN.fullmatch(row)
        if match is None:
            raise ValueError(f"invalid checksum row: {row!r}")
        digest, name = match.groups()
        if name in declared:
            raise ValueError(f"duplicate checksum entry: {name}")
        declared[name] = digest
    if set(declared) != set(CONTENT_FILES):
        raise ValueError("checksum file set does not match package contract")

    for name in CONTENT_FILES:
        actual = hashlib.sha256((package / name).read_bytes()).hexdigest()
        if actual != declared[name]:
            raise ValueError(
                f"checksum mismatch for {name}: "
                f"expected {declared[name]}, got {actual}"
            )


def _retrieval_metric(summary: dict[str, Any], name: str) -> float:
    return float(
        summary["summary"]["layers"]["retrieval"]["metrics"][name]["mean"]
    )


def _verify_quality(quality: dict[str, Any]) -> None:
    expected_metrics = {
        "document_count": 240,
        "policy_count": 20,
        "policy_version_count": 40,
        "atomic_fact_count": 104,
        "active_fact_count": 52,
        "department_count": 12,
        "eval_dev_count": 48,
        "eval_test_count": 56,
        "unused_operational_acl_group_count": 0,
    }
    if quality.get("schema_version") != "enterprise_corpus_quality_v1":
        raise ValueError("unexpected quality schema")
    if quality.get("profile_id") != "expanded":
        raise ValueError("quality profile is not expanded")
    if quality.get("release_pass") is not True:
        raise ValueError("corpus quality gate did not pass")
    if quality.get("failures") != []:
        raise ValueError("corpus quality report contains failures")
    if not all(quality.get("checks", {}).values()):
        raise ValueError("one or more corpus quality checks failed")
    metrics = quality.get("metrics", {})
    for name, expected in expected_metrics.items():
        if metrics.get(name) != expected:
            raise ValueError(
                f"unexpected quality metric {name}: {metrics.get(name)!r}"
            )
    if metrics.get("active_fact_support_coverage") != 1.0:
        raise ValueError("active fact support coverage is not complete")
    if metrics.get("active_fact_eval_coverage") != 1.0:
        raise ValueError("active fact evaluation coverage is not complete")


def _verify_index(manifest: dict[str, Any]) -> None:
    expected = {
        "schema_version": "enterprise_index_manifest_v1",
        "profile_id": "expanded",
        "source_document_count": 240,
        "canonical_document_count": 216,
        "duplicate_count": 24,
        "chunk_count": 216,
        "indexed_chunk_count": 216,
    }
    for name, value in expected.items():
        if manifest.get(name) != value:
            raise ValueError(
                f"unexpected index manifest field {name}: "
                f"{manifest.get(name)!r}"
            )
    embedding = manifest.get("embedding", {})
    if embedding.get("model") != "bge-m3":
        raise ValueError("index evidence was not built with bge-m3")
    if embedding.get("dimension") != 1024:
        raise ValueError("unexpected embedding dimension")
    if manifest.get("chunker_config", {}).get("mode") != "fixed":
        raise ValueError("unexpected chunker mode")


def _verify_retrieval(
    summary: dict[str, Any],
    *,
    split: str,
    case_count: int,
) -> None:
    if summary.get("mode") != "live":
        raise ValueError(f"{split} evidence is not a live run")
    if summary.get("split") != split:
        raise ValueError(f"{split} evidence declares the wrong split")
    if summary.get("suite") != "retrieval":
        raise ValueError(f"{split} evidence is not a retrieval suite")
    if summary.get("case_count") != case_count:
        raise ValueError(f"{split} evidence has the wrong case count")
    aggregate = summary.get("summary", {})
    if aggregate.get("failed_case_count") != 0:
        raise ValueError(f"{split} retrieval contains failed cases")
    if aggregate.get("overall_case_pass", {}).get("rate") != 1.0:
        raise ValueError(f"{split} overall pass rate is not 1.0")
    if _retrieval_metric(summary, "acl_leakage_count") != 0.0:
        raise ValueError(f"{split} retrieval contains ACL leakage")
    if _retrieval_metric(summary, "hit@1") != 1.0:
        raise ValueError(f"{split} hit@1 is below the release threshold")
    if _retrieval_metric(summary, "document_recall@3") != 1.0:
        raise ValueError(
            f"{split} document_recall@3 is below the release threshold"
        )


def verify(package: Path) -> dict[str, object]:
    package = package.resolve()
    if not package.is_dir():
        raise ValueError(f"package directory not found: {package}")
    _verify_checksums(package)
    _verify_quality(_load_json(package, "quality.json"))
    _verify_index(_load_json(package, "index_manifest.json"))
    _verify_retrieval(
        _load_json(package, "retrieval_dev_summary.json"),
        split="dev",
        case_count=48,
    )
    _verify_retrieval(
        _load_json(package, "retrieval_test_summary.json"),
        split="test",
        case_count=56,
    )
    return {"profile_id": "expanded", "verified": True}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Verify the public expanded-corpus evidence package.",
    )
    parser.add_argument(
        "--package",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    args = parser.parse_args(argv)
    try:
        report = verify(args.package)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
