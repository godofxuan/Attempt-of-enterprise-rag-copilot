"""Offline preflight for an existing trusted corpus; never publishes an index."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.ingestion.chunking import ChunkerConfig, chunk_document
from app.ingestion.document_quality import DocumentQualityError, assess_document_quality
from app.ingestion.normalize import _confined_source_path, load_source_manifest, normalize_document
from app.ingestion.parsers import build_default_registry


def check_corpus(input_dir: Path, output_dir: Path, config: ChunkerConfig) -> dict:
    if config.mode != "structure":
        raise ValueError("quality preflight requires the explicit structure profile")
    source_manifest = load_source_manifest(input_dir / "manifest.json")
    output_dir.mkdir(parents=True, exist_ok=False)
    registry = build_default_registry()
    now = datetime.now(UTC)
    reports = []
    for entry in source_manifest.documents:
        result = {"doc_id": entry.doc_id, "source_sha256": entry.sha256}
        try:
            source = _confined_source_path(input_dir, entry.path)
            if not source.is_file() or source.stat().st_size > 20 * 1024**2:
                raise ValueError("missing_source_or_size_budget_exceeded")
            content = source.read_bytes()
            if (
                len(content) != entry.byte_count
                or hashlib.sha256(content).hexdigest() != entry.sha256
            ):
                raise ValueError("source_manifest_mismatch")
            parsed = registry.parse_bytes(content, suffix=source.suffix)
            document = normalize_document(entry, source, parsed, ingested_at=now)
            chunks = chunk_document(document, config)
            result.update(
                assessment=assess_document_quality(document, chunks, config).model_dump(
                    mode="json"
                ),
                status="ACCEPT",
            )
        except DocumentQualityError as exc:
            result.update(status=exc.report.decision, assessment=exc.report.model_dump(mode="json"))
        except Exception as exc:
            result.update(status="REJECT", error_type=type(exc).__name__, reason=str(exc))
        reports.append(result)
    accepted = sum(row["status"] == "ACCEPT" for row in reports)
    report = {
        "schema": "document_quality_preflight_v1",
        "scope": "structural_preflight_not_source_authorization_or_semantic_truth",
        "created_at": now.isoformat(),
        "manifest_sha256": hashlib.sha256((input_dir / "manifest.json").read_bytes()).hexdigest(),
        "config": config.model_dump(mode="json"),
        "document_count": len(reports),
        "accepted": accepted,
        "status": "PREFLIGHT_PASS" if reports and accepted == len(reports) else "REVIEW_REQUIRED",
        "published": False,
        "reports": reports,
    }
    (output_dir / "QUALITY_PREFLIGHT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = check_corpus(
        args.input_dir.resolve(), args.output_dir.resolve(), ChunkerConfig(mode="structure")
    )
    print(json.dumps({key: value for key, value in report.items() if key != "reports"}, indent=2))
    raise SystemExit(0 if report["status"] == "PREFLIGHT_PASS" else 2)


if __name__ == "__main__":
    main()
