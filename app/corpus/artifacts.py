from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.corpus.eval_cases import (
    build_eval_splits,
    build_test_manifest_line,
    serialize_eval_cases,
)
from app.corpus.generator import generate_document_specs
from app.corpus.renderers import extension_for, render_document
from app.corpus.schemas import (
    CompanyFacts,
    CorpusManifest,
    CorpusProfile,
    ManifestDocument,
    SmokeFixtureManifest,
)


GENERATOR_VERSION = "1.0.0"


def _json_bytes(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _model_hash(model: BaseModel) -> str:
    canonical = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_manifest(path: Path) -> CorpusManifest:
    return CorpusManifest.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def load_smoke_manifest(path: Path) -> SmokeFixtureManifest:
    return SmokeFixtureManifest.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def _build(
    facts: CompanyFacts,
    profile: CorpusProfile,
    seed: int,
):
    documents = generate_document_specs(facts, profile, seed=seed)
    dev_cases, test_cases = build_eval_splits(
        facts,
        documents,
        profile,
        seed=seed,
    )
    rendered: dict[str, bytes] = {}
    manifest_documents: list[ManifestDocument] = []
    for document in documents:
        relative_path = (
            Path("documents")
            / f"{document.doc_id}{extension_for(document.format)}"
        )
        content = render_document(document).encode("utf-8")
        relative_key = relative_path.as_posix()
        rendered[relative_key] = content
        manifest_documents.append(
            ManifestDocument(
                doc_id=document.doc_id,
                path=relative_key,
                sha256=hashlib.sha256(content).hexdigest(),
                byte_count=len(content),
                format=document.format,
                source_type=document.source_type,
                variant=document.metadata.variant,
                metadata=document.metadata,
                fact_ids=document.fact_ids,
            )
        )

    manifest = CorpusManifest(
        schema_version="enterprise_corpus_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        generator_version=GENERATOR_VERSION,
        profile_id=profile.profile_id,
        seed=seed,
        facts_sha256=_model_hash(facts),
        profile_sha256=_model_hash(profile),
        document_count=len(documents),
        counts_by_format=dict(sorted(Counter(doc.format for doc in documents).items())),
        counts_by_source_type=dict(
            sorted(Counter(doc.source_type for doc in documents).items())
        ),
        counts_by_variant=dict(
            sorted(Counter(doc.metadata.variant for doc in documents).items())
        ),
        documents=manifest_documents,
    )
    return manifest, rendered, dev_cases, test_cases


def preview_corpus(
    facts: CompanyFacts,
    profile: CorpusProfile,
    seed: int | None = None,
) -> dict:
    effective_seed = profile.seed if seed is None else seed
    manifest, _, dev_cases, test_cases = _build(facts, profile, effective_seed)
    return {
        "profile_id": profile.profile_id,
        "seed": effective_seed,
        "document_count": manifest.document_count,
        "eval_dev_count": len(dev_cases),
        "eval_test_count": len(test_cases),
        "counts_by_format": manifest.counts_by_format,
        "counts_by_source_type": manifest.counts_by_source_type,
        "counts_by_variant": manifest.counts_by_variant,
        "facts_sha256": manifest.facts_sha256,
        "profile_sha256": manifest.profile_sha256,
        "written": False,
    }


def _is_nonempty_directory(path: Path) -> bool:
    return path.is_dir() and next(path.iterdir(), None) is not None


def _validate_owned_output(path: Path) -> None:
    manifest_path = path / "manifest.json"
    try:
        manifest = load_manifest(manifest_path)
    except (FileNotFoundError, json.JSONDecodeError, ValidationError) as exc:
        raise PermissionError(
            f"{path} is not a generated corpus; refusing --force"
        ) from exc
    if manifest.producer != "enterprise_agentic_rag_v2":
        raise PermissionError(f"{path} is not a generated corpus; refusing --force")


def _validate_target(path: Path, force: bool) -> None:
    resolved = path.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise PermissionError(f"refusing to use unsafe output directory: {resolved}")
    if path.exists() and not path.is_dir():
        raise FileExistsError(f"output path already exists and is not a directory: {path}")
    if not _is_nonempty_directory(path):
        return
    if not force:
        raise FileExistsError(
            f"output directory already exists and is not empty: {path}; use --force"
        )
    _validate_owned_output(path)


def _write_stage(
    stage: Path,
    manifest: CorpusManifest,
    rendered: dict[str, bytes],
    dev_cases,
    test_cases,
) -> None:
    for relative_path, content in rendered.items():
        path = stage / Path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    eval_dir = stage / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    dev_bytes = serialize_eval_cases(dev_cases)
    test_bytes = serialize_eval_cases(test_cases)
    (eval_dir / "dev.json").write_bytes(dev_bytes)
    (eval_dir / "test.json").write_bytes(test_bytes)
    (eval_dir / "test_manifest.sha256").write_text(
        build_test_manifest_line(test_bytes),
        encoding="utf-8",
        newline="\n",
    )
    (stage / "manifest.json").write_bytes(
        _json_bytes(manifest.model_dump(mode="json"))
    )


def _rename_with_retry(
    source: Path,
    target: Path,
    delays: tuple[float, ...] = (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.25),
) -> None:
    for delay in (*delays, None):
        try:
            source.rename(target)
            return
        except PermissionError as exc:
            is_transient_windows_lock = getattr(exc, "winerror", None) in {5, 32}
            if not is_transient_windows_lock or target.exists() or delay is None:
                raise
            time.sleep(delay)


def _activate_stage(stage: Path, output_dir: Path) -> None:
    if not output_dir.exists():
        _rename_with_retry(stage, output_dir)
        return
    if not _is_nonempty_directory(output_dir):
        output_dir.rmdir()
        _rename_with_retry(stage, output_dir)
        return

    backup = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.backup-",
            dir=output_dir.parent,
        )
    )
    backup.rmdir()
    _rename_with_retry(output_dir, backup)
    try:
        _rename_with_retry(stage, output_dir)
    except Exception:
        if not output_dir.exists() and backup.exists():
            _rename_with_retry(backup, output_dir)
        raise
    else:
        shutil.rmtree(backup)


def write_corpus(
    output_dir: Path,
    facts: CompanyFacts,
    profile: CorpusProfile,
    seed: int | None = None,
    force: bool = False,
) -> CorpusManifest:
    output_dir = Path(output_dir)
    _validate_target(output_dir, force)
    effective_seed = profile.seed if seed is None else seed
    manifest, rendered, dev_cases, test_cases = _build(
        facts,
        profile,
        effective_seed,
    )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    try:
        _write_stage(stage, manifest, rendered, dev_cases, test_cases)
        _activate_stage(stage, output_dir)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return manifest


def _require_empty_output(path: Path, label: str) -> None:
    if path.exists() and not path.is_dir():
        raise FileExistsError(f"{label} path is not a directory: {path}")
    if _is_nonempty_directory(path):
        raise FileExistsError(f"{label} already exists and is frozen: {path}")


def write_canonical_eval(
    output_dir: Path,
    facts: CompanyFacts,
    profile: CorpusProfile,
    seed: int | None = None,
) -> dict[str, str | int]:
    output_dir = Path(output_dir)
    _require_empty_output(output_dir, "frozen eval directory")
    effective_seed = profile.seed if seed is None else seed
    documents = generate_document_specs(facts, profile, seed=effective_seed)
    dev_cases, test_cases = build_eval_splits(
        facts,
        documents,
        profile,
        seed=effective_seed,
    )
    dev_bytes = serialize_eval_cases(dev_cases)
    test_bytes = serialize_eval_cases(test_cases)
    test_sha256 = hashlib.sha256(test_bytes).hexdigest()

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    try:
        (stage / "dev.json").write_bytes(dev_bytes)
        (stage / "test.json").write_bytes(test_bytes)
        (stage / "test_manifest.sha256").write_text(
            build_test_manifest_line(test_bytes),
            encoding="utf-8",
            newline="\n",
        )
        _activate_stage(stage, output_dir)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {
        "dev_count": len(dev_cases),
        "test_count": len(test_cases),
        "test_sha256": test_sha256,
    }


def write_smoke_fixture(
    output_dir: Path,
    facts: CompanyFacts,
    profile: CorpusProfile,
    seed: int | None = None,
) -> SmokeFixtureManifest:
    output_dir = Path(output_dir)
    _require_empty_output(output_dir, "smoke fixture directory")
    effective_seed = profile.seed if seed is None else seed
    full_manifest, rendered, _, _ = _build(facts, profile, effective_seed)

    selected: list[ManifestDocument] = []
    for document_format in ("md", "txt", "html", "csv", "jsonl"):
        selected.append(
            next(
                document
                for document in full_manifest.documents
                if document.format == document_format
            )
        )
    manifest = SmokeFixtureManifest(
        schema_version="enterprise_smoke_fixture_v1",
        producer="enterprise_agentic_rag_v2",
        generator_version=GENERATOR_VERSION,
        source_profile_id=profile.profile_id,
        seed=effective_seed,
        facts_sha256=full_manifest.facts_sha256,
        profile_sha256=full_manifest.profile_sha256,
        documents=selected,
    )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    try:
        for document in selected:
            path = stage / Path(document.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(rendered[document.path])
        (stage / "manifest.json").write_bytes(
            _json_bytes(manifest.model_dump(mode="json"))
        )
        _activate_stage(stage, output_dir)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return manifest
