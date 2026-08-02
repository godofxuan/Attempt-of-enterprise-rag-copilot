try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    build_finqa_evidence_units,
    load_finqa_split,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v2 import (
    build_contextual_safe_descriptor_catalog_v2,
)
from scripts import audit_finqa_descriptor_catalog_upper_bound_v1 as engine


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _context_registry() -> dict[tuple[str, str], str]:
    cases, _ = load_finqa_split(
        (DEFAULT_SOURCE_ROOT / "dataset" / "dev.json").resolve(),
        expected_sha256=FINQA_DEV_SHA256,
    )
    registry: dict[tuple[str, str], str] = {}
    for case in cases:
        for unit in build_finqa_evidence_units(case):
            registry[(case.filename, unit.unit_id)] = unit.text
    return registry


def main(argv: list[str] | None = None) -> int:
    registry = _context_registry()

    def contextual_builder(*, candidates, admitted_evidence_ids, guard):
        context = {
            candidate.evidence_id: registry[
                (candidate.source_id, candidate.evidence_id)
            ]
            for candidate in candidates
        }
        return build_contextual_safe_descriptor_catalog_v2(
            candidates=candidates,
            admitted_evidence_ids=admitted_evidence_ids,
            evidence_context_by_id=context,
            guard=guard,
        )

    engine.DEFAULT_OUTPUT = (
        REPOSITORY_ROOT
        / "docs"
        / "external_datasets"
        / "evidence"
        / "finqa_descriptor_catalog_upper_bound_public_v2.json"
    )
    engine.DEFAULT_PRIVATE_OUTPUT = (
        DEFAULT_PRIVATE_ROOT
        / "descriptor_catalog_upper_bound_audits"
        / "finqa-descriptor-catalog-upper-bound-v2"
    )
    engine.IMPLEMENTATION_FILES = (
        "app/external_datasets/finqa_safe_descriptor_catalog_v1.py",
        "app/external_datasets/finqa_safe_descriptor_catalog_v2.py",
        "app/external_datasets/finqa_descriptor_catalog_protocol_v1.py",
        "scripts/audit_finqa_descriptor_catalog_upper_bound_v1.py",
        "scripts/audit_finqa_descriptor_catalog_upper_bound_v2.py",
    )
    engine.build_safe_descriptor_catalog_v1 = contextual_builder
    return engine.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
