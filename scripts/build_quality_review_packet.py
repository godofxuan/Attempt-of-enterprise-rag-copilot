from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import csv
import hashlib
import hmac
import json
import random
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.corpus.schemas import EvalCase
from app.evaluation.quality_review import (
    QualityEvidence,
    QualityReviewItem,
    QualityReviewPacketSpec,
    QualityReviewSource,
    publish_quality_review_packet,
    verify_quality_review_packet,
)
from app.filesystem import atomic_directory_move


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a blinded calibration packet from an immutable human-review "
            "evaluation run. Public synthetic inputs cannot produce held-out claims."
        )
    )
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--dataset-path", type=Path, required=True)
    parser.add_argument(
        "--dataset-split",
        choices=["dev", "test"],
        required=True,
    )
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--control-out-dir", type=Path, required=True)
    parser.add_argument("--blinding-key-file", type=Path, required=True)
    parser.add_argument(
        "--sampling-strategy",
        choices=["all_cases", "stratified_random", "error_enriched"],
        default="stratified_random",
    )
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--sampling-seed", type=int, default=1729)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.sample_size is not None and args.sample_size < 1:
        raise ValueError("quality review sample size must be positive")
    if args.sampling_seed < 0:
        raise ValueError("quality review sampling seed must be non-negative")

    source_run_dir = args.source_run_dir.resolve()
    dataset_path = args.dataset_path.resolve()
    corpus_dir = args.corpus_dir.resolve()
    source_manifest_path = source_run_dir / "manifest.json"
    review_csv_path = source_run_dir / "human_review.csv"
    corpus_manifest_path = corpus_dir / "manifest.json"
    for path in (
        source_manifest_path,
        review_csv_path,
        dataset_path,
        corpus_manifest_path,
        args.blinding_key_file.resolve(),
    ):
        _require_regular_file(path)

    source_manifest = _load_json_object(source_manifest_path)
    _verify_source_bindings(
        source_manifest,
        source_manifest_path=source_manifest_path,
        review_csv_path=review_csv_path,
        dataset_path=dataset_path,
        corpus_manifest_path=corpus_manifest_path,
    )
    cases = _load_cases(dataset_path)
    rows = _load_review_rows(review_csv_path)
    selected_rows = _select_rows(
        rows,
        cases=cases,
        source_run_dir=source_run_dir,
        source_manifest=source_manifest,
        strategy=args.sampling_strategy,
        sample_size=args.sample_size,
        seed=args.sampling_seed,
    )

    blinding_key = args.blinding_key_file.resolve().read_bytes()
    if len(blinding_key) < 32:
        raise ValueError("quality review blinding key must contain at least 32 bytes")
    if len(set(blinding_key)) < 8:
        raise ValueError(
            "quality review blinding key is obviously weak; use a CSPRNG"
        )
    corpus_documents = _load_corpus_documents(
        corpus_dir,
        corpus_manifest_path,
    )
    items, control_rows = _build_items(
        packet_id=args.packet_id,
        rows=selected_rows,
        cases=cases,
        corpus_documents=corpus_documents,
        blinding_key=blinding_key,
    )

    source = QualityReviewSource(
        run_id=_required_string(source_manifest, "run_id"),
        run_manifest_sha256=_sha256(source_manifest_path),
        dataset_sha256=_sha256(dataset_path),
        dataset_split=args.dataset_split,
        git_commit=_required_nested_string(source_manifest, "git", "head"),
        population_kind="public_synthetic",
        independence_status="not_independent",
    )
    spec = QualityReviewPacketSpec(
        packet_id=args.packet_id,
        purpose="calibration",
        created_at_utc=datetime.now(timezone.utc),
        source=source,
        sampling_strategy=args.sampling_strategy,
        sampling_seed=args.sampling_seed,
        items=items,
    )
    packet_dir = _publish_or_recover_packet(args.out_dir, spec)
    control_dir = _publish_control_map(
        args.control_out_dir.resolve(),
        packet_id=args.packet_id,
        packet_dir=packet_dir,
        source_manifest_sha256=_sha256(source_manifest_path),
        rows=control_rows,
    )
    print(
        json.dumps(
            {
                "packet_id": args.packet_id,
                "purpose": "calibration",
                "population_kind": "public_synthetic",
                "independence_status": "not_independent",
                "claim_status": "NOT_RUN",
                "item_count": len(items),
                "packet_dir": str(packet_dir),
                "control_dir": str(control_dir),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _publish_or_recover_packet(
    root: Path,
    spec: QualityReviewPacketSpec,
) -> Path:
    root = Path(root).resolve()
    target = (root / spec.packet_id).resolve()
    if target.parent != root:
        raise ValueError("quality review packet path escapes its root")
    if not target.exists():
        return publish_quality_review_packet(root, spec)

    manifest = verify_quality_review_packet(target)
    observed_items = [
        QualityReviewItem.model_validate_json(line)
        for line in (target / "review_items.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    expected_contract = (
        spec.packet_id,
        spec.purpose,
        spec.source,
        spec.sampling_strategy,
        spec.sampling_seed,
        spec.thresholds,
        len(spec.items),
    )
    observed_contract = (
        manifest.packet_id,
        manifest.purpose,
        manifest.source,
        manifest.sampling_strategy,
        manifest.sampling_seed,
        manifest.thresholds,
        manifest.item_count,
    )
    if observed_contract != expected_contract or observed_items != spec.items:
        raise FileExistsError(
            "existing quality review packet does not match recovery input"
        )
    return target


def _verify_source_bindings(
    manifest: dict[str, Any],
    *,
    source_manifest_path: Path,
    review_csv_path: Path,
    dataset_path: Path,
    corpus_manifest_path: Path,
) -> None:
    del source_manifest_path
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("source run manifest artifacts must be an object")
    if artifacts.get("human_review.csv") != _sha256(review_csv_path):
        raise ValueError("source human-review CSV hash mismatch")

    dataset_hash = _sha256(dataset_path)
    admitted_hashes: set[str] = set()
    dataset = manifest.get("dataset")
    if isinstance(dataset, dict) and isinstance(dataset.get("sha256"), str):
        admitted_hashes.add(dataset["sha256"])
    config = manifest.get("config")
    if isinstance(config, dict) and isinstance(config.get("datasets"), list):
        for item in config["datasets"]:
            if isinstance(item, dict) and isinstance(item.get("sha256"), str):
                admitted_hashes.add(item["sha256"])
    if dataset_hash not in admitted_hashes:
        raise ValueError("source run does not bind the requested dataset")

    corpus = manifest.get("corpus")
    if (
        not isinstance(corpus, dict)
        or corpus.get("manifest_sha256") != _sha256(corpus_manifest_path)
    ):
        raise ValueError("source run corpus manifest hash mismatch")
    git_head = _required_nested_string(manifest, "git", "head")
    if len(git_head) != 40 or any(char not in "0123456789abcdef" for char in git_head):
        raise ValueError("source run git commit is not a lowercase full SHA")


def _load_cases(path: Path) -> dict[str, EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("quality review dataset must be a JSON array")
    cases = [EvalCase.model_validate(item) for item in payload]
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("quality review dataset case IDs must be unique")
    return by_id


def _load_review_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "case_id",
            "task_type",
            "question",
            "expected_mode",
            "actual_mode",
            "system_answer",
            "visible_source_doc_ids",
        }
        if not required.issubset(set(reader.fieldnames or ())):
            raise ValueError("source human-review CSV fields are incomplete")
        rows = list(reader)
    case_ids = [row["case_id"] for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("source human-review CSV case IDs must be unique")
    return rows


def _select_rows(
    rows: list[dict[str, str]],
    *,
    cases: dict[str, EvalCase],
    source_run_dir: Path,
    source_manifest: dict[str, Any],
    strategy: str,
    sample_size: int | None,
    seed: int,
) -> list[dict[str, str]]:
    eligible = [row for row in rows if row["case_id"] in cases]
    if not eligible:
        raise ValueError("source human-review CSV has no rows for the dataset")
    target = len(eligible) if sample_size is None else sample_size
    if target > len(eligible):
        raise ValueError("quality review sample size exceeds eligible rows")
    if strategy == "all_cases":
        if target != len(eligible):
            raise ValueError("all_cases sampling must include every eligible row")
        return sorted(eligible, key=lambda row: row["case_id"])
    if strategy == "stratified_random":
        return _stratified_sample(eligible, target=target, seed=seed)

    failures_path = source_run_dir / "failures.csv"
    artifacts = source_manifest.get("artifacts")
    if (
        not failures_path.is_file()
        or not isinstance(artifacts, dict)
        or artifacts.get("failures.csv") != _sha256(failures_path)
    ):
        raise ValueError(
            "error-enriched sampling requires a hash-bound failures.csv"
        )
    with failures_path.open(encoding="utf-8-sig", newline="") as handle:
        failed_ids = {
            row["case_id"]
            for row in csv.DictReader(handle)
            if row.get("case_id")
        }
    ordered = sorted(
        eligible,
        key=lambda row: (row["case_id"] not in failed_ids, row["case_id"]),
    )
    return ordered[:target]


def _stratified_sample(
    rows: list[dict[str, str]],
    *,
    target: int,
    seed: int,
) -> list[dict[str, str]]:
    rng = random.Random(seed)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["task_type"]].append(row)
    for group in groups.values():
        group.sort(key=lambda row: row["case_id"])
        rng.shuffle(group)
    selected: list[dict[str, str]] = []
    task_types = sorted(groups)
    while len(selected) < target:
        progressed = False
        for task_type in task_types:
            if groups[task_type] and len(selected) < target:
                selected.append(groups[task_type].pop())
                progressed = True
        if not progressed:
            break
    return selected


def _load_corpus_documents(
    corpus_dir: Path,
    manifest_path: Path,
) -> dict[str, QualityEvidence]:
    manifest = _load_json_object(manifest_path)
    documents = manifest.get("documents")
    if not isinstance(documents, list):
        raise ValueError("corpus manifest documents must be an array")
    result: dict[str, QualityEvidence] = {}
    for entry in documents:
        if not isinstance(entry, dict):
            raise ValueError("corpus manifest document entry must be an object")
        doc_id = _required_string(entry, "doc_id")
        relative = Path(_required_string(entry, "path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe corpus document path for {doc_id}")
        path = (corpus_dir / relative).resolve()
        try:
            path.relative_to(corpus_dir)
        except ValueError as exc:
            raise ValueError(f"corpus document escapes root for {doc_id}") from exc
        _require_regular_file(path)
        expected_hash = _required_string(entry, "sha256")
        if _sha256(path) != expected_hash:
            raise ValueError(f"corpus document hash mismatch for {doc_id}")
        if doc_id in result:
            raise ValueError("corpus manifest document IDs must be unique")
        content = path.read_text(encoding="utf-8")
        result[doc_id] = QualityEvidence(
            source_id=doc_id,
            title=doc_id,
            content=content,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_artifact_sha256=expected_hash,
        )
    return result


def _build_items(
    *,
    packet_id: str,
    rows: list[dict[str, str]],
    cases: dict[str, EvalCase],
    corpus_documents: dict[str, QualityEvidence],
    blinding_key: bytes,
) -> tuple[list[QualityReviewItem], list[dict[str, Any]]]:
    items: list[QualityReviewItem] = []
    control_rows: list[dict[str, Any]] = []
    for row in rows:
        case = cases[row["case_id"]]
        if row["question"] != case.question:
            raise ValueError(f"review question mismatch for {case.case_id}")
        if row["expected_mode"] != case.answer_mode:
            raise ValueError(f"review expected mode mismatch for {case.case_id}")
        if not row["system_answer"].strip():
            raise ValueError(f"review system answer is blank for {case.case_id}")
        visible_ids = _split_source_ids(row["visible_source_doc_ids"])
        forbidden_visible = set(visible_ids) & set(case.forbidden_doc_ids)
        if forbidden_visible:
            raise ValueError(
                f"review source contains forbidden document for {case.case_id}"
            )
        reference_ids = list(
            dict.fromkeys([*case.gold_doc_ids, *case.expected_authority_doc_ids])
        )
        candidate_ids = list(dict.fromkeys([*visible_ids, *reference_ids]))
        review_item_id = "qri_" + hmac.new(
            blinding_key,
            f"{packet_id}\0{case.case_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:24]
        item = QualityReviewItem(
            review_item_id=review_item_id,
            question=case.question,
            system_answer=row["system_answer"],
            expected_response_mode=case.answer_mode,
            reference_answer=case.expected_answer,
            retrieved_evidence=[
                _required_document(corpus_documents, doc_id)
                for doc_id in visible_ids
            ],
            retrieval_candidate_evidence=[
                _required_document(corpus_documents, doc_id)
                for doc_id in candidate_ids
            ],
            candidate_pool_strategy="returned_plus_reference",
            reference_evidence=[
                _required_document(corpus_documents, doc_id)
                for doc_id in reference_ids
            ],
        )
        items.append(item)
        control_rows.append(
            {
                "review_item_id": review_item_id,
                "source_case_id": case.case_id,
                "task_type": case.task_type,
                "expected_mode": case.answer_mode,
                "actual_mode": row["actual_mode"],
            }
        )
    return items, control_rows


def _publish_control_map(
    root: Path,
    *,
    packet_id: str,
    packet_dir: Path,
    source_manifest_sha256: str,
    rows: list[dict[str, Any]],
) -> Path:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / packet_id).resolve()
    if target.parent != root:
        raise ValueError("quality review control path escapes its root")
    if target.exists():
        _verify_control_map(
            target,
            packet_id=packet_id,
            packet_dir=packet_dir,
            source_manifest_sha256=source_manifest_sha256,
            rows=rows,
        )
        return target
    stage = Path(
        tempfile.mkdtemp(prefix=f".{packet_id}.staging-", dir=root)
    ).resolve()
    try:
        item_map = stage / "item_map.jsonl"
        item_map.write_bytes(
            b"".join(_json_bytes(row, newline=True) for row in rows)
        )
        control_manifest = {
            "schema_version": "enterprise_quality_review_control_v1",
            "packet_id": packet_id,
            "packet_manifest_sha256": _sha256(packet_dir / "manifest.json"),
            "source_manifest_sha256": source_manifest_sha256,
            "item_count": len(rows),
            "item_map_sha256": _sha256(item_map),
            "public": False,
        }
        (stage / "control_manifest.json").write_bytes(
            _json_bytes(control_manifest)
        )
        atomic_directory_move(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def _verify_control_map(
    target: Path,
    *,
    packet_id: str,
    packet_dir: Path,
    source_manifest_sha256: str,
    rows: list[dict[str, Any]],
) -> None:
    target = Path(target).resolve()
    if target.is_symlink() or not target.is_dir():
        raise FileExistsError(
            "existing quality review control target is not a plain directory"
        )
    expected_names = {"control_manifest.json", "item_map.jsonl"}
    if {path.name for path in target.iterdir()} != expected_names:
        raise FileExistsError(
            "existing quality review control file set does not match"
        )
    item_map = target / "item_map.jsonl"
    expected_item_map = b"".join(
        _json_bytes(row, newline=True) for row in rows
    )
    if item_map.read_bytes() != expected_item_map:
        raise FileExistsError(
            "existing quality review control rows do not match"
        )
    expected_manifest = {
        "schema_version": "enterprise_quality_review_control_v1",
        "packet_id": packet_id,
        "packet_manifest_sha256": _sha256(
            Path(packet_dir).resolve() / "manifest.json"
        ),
        "source_manifest_sha256": source_manifest_sha256,
        "item_count": len(rows),
        "item_map_sha256": hashlib.sha256(expected_item_map).hexdigest(),
        "public": False,
    }
    if _load_json_object(target / "control_manifest.json") != expected_manifest:
        raise FileExistsError(
            "existing quality review control manifest does not match"
        )


def _split_source_ids(value: str) -> list[str]:
    source_ids = [item.strip() for item in value.split(";") if item.strip()]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("review visible source document IDs must be unique")
    return source_ids


def _required_document(
    documents: dict[str, QualityEvidence],
    doc_id: str,
) -> QualityEvidence:
    try:
        return documents[doc_id]
    except KeyError as exc:
        raise ValueError(f"review references unknown document: {doc_id}") from exc


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"required string field is missing: {key}")
    return item


def _required_nested_string(
    value: dict[str, Any],
    object_key: str,
    item_key: str,
) -> str:
    nested = value.get(object_key)
    if not isinstance(nested, dict):
        raise ValueError(f"required object field is missing: {object_key}")
    return _required_string(nested, item_key)


def _require_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"required regular file not found: {path}")


def _json_bytes(value: object, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if newline else 2,
        )
        + suffix
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
