from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


MIN_SENSITIVE_VALUE_LENGTH = 8


@dataclass(frozen=True)
class SecuritySensitiveValueCorpus:
    protected_values: tuple[str, ...]
    case_ids: tuple[str, ...]

    def values(self, *, include_case_ids: bool) -> tuple[str, ...]:
        if not include_case_ids:
            return self.protected_values
        return tuple(sorted({*self.protected_values, *self.case_ids}))


def collect_security_sensitive_values(
    *,
    datasets: Iterable[object] = (),
    fixture_manifests: Iterable[object] = (),
) -> SecuritySensitiveValueCorpus:
    values: set[str] = set()
    case_ids: set[str] = set()
    for dataset_value in datasets:
        dataset = _as_mapping(dataset_value)
        _add_fields(
            values,
            dataset,
            ("schema_version", "dataset_id", "taxonomy_version"),
        )
        for case_value in _mappings(dataset.get("cases")):
            _add_fields(case_ids, case_value, ("case_id",))
            _add_fields(
                values,
                case_value,
                (
                    "question",
                    "user_context_fixture",
                    "document_canary",
                    "trace_canary",
                ),
            )
            _add_sequences(
                values,
                case_value,
                (
                    "fixture_document_ids",
                    "attack_unit_ids",
                    "benign_unit_ids",
                    "required_clean_fact_ids",
                    "tags",
                ),
            )
            expected = case_value.get("expected_guard_outcome")
            if isinstance(expected, Mapping):
                _add_values(values, expected.keys())

    for fixture_value in fixture_manifests:
        fixture_manifest = _as_mapping(fixture_value)
        _add_fields(
            values,
            fixture_manifest,
            ("schema_version", "fixture_id"),
        )
        for case_value in _mappings(fixture_manifest.get("cases")):
            _add_fields(case_ids, case_value, ("case_id",))
            facts = case_value.get("fact_texts")
            if isinstance(facts, Mapping):
                _add_values(values, facts.keys())
                _add_values(values, facts.values())
            for candidate in _mappings(case_value.get("candidates")):
                _add_fields(
                    values,
                    candidate,
                    (
                        "chunk_id",
                        "document_id",
                        "source_path",
                        "source_path_unit_id",
                        "section_unit_id",
                        "matched_text",
                        "matched_unit_id",
                        "context_text",
                        "context_unit_id",
                        "parent_chunk_id",
                        "document_title",
                        "title_unit_id",
                        "version",
                        "version_unit_id",
                    ),
                )
                _add_sequences(values, candidate, ("section_path", "fact_ids"))
            for opened in _mappings(case_value.get("open_results")):
                _add_fields(
                    values,
                    opened,
                    (
                        "target_id",
                        "document_id",
                        "content",
                        "content_unit_id",
                        "source_path",
                    ),
                )
                _add_sequences(values, opened, ("section_path",))
            for parent in _mappings(case_value.get("parent_links")):
                _add_fields(
                    values,
                    parent,
                    ("parent_chunk_id", "document_id"),
                )
                _add_sequences(values, parent, ("child_chunk_ids",))
    return SecuritySensitiveValueCorpus(
        protected_values=tuple(sorted(values)),
        case_ids=tuple(sorted(case_ids)),
    )


def _as_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        if isinstance(dumped, Mapping):
            return dumped
    raise TypeError("sensitive-value source must be a mapping or Pydantic model")


def _mappings(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _add_fields(
    values: set[str],
    source: Mapping[str, Any],
    fields: Iterable[str],
) -> None:
    _add_values(values, (source.get(field) for field in fields))


def _add_sequences(
    values: set[str],
    source: Mapping[str, Any],
    fields: Iterable[str],
) -> None:
    for field in fields:
        value = source.get(field)
        if isinstance(value, (list, tuple)):
            _add_values(values, value)


def _add_values(values: set[str], candidates: Iterable[object]) -> None:
    for candidate in candidates:
        if (
            isinstance(candidate, str)
            and len(candidate.strip()) >= MIN_SENSITIVE_VALUE_LENGTH
        ):
            values.add(candidate)


__all__ = [
    "MIN_SENSITIVE_VALUE_LENGTH",
    "SecuritySensitiveValueCorpus",
    "collect_security_sensitive_values",
]
