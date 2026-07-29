from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

from app.external_datasets.finqa_typed_program import (
    EXTRACTION_CONFIG_SHA256,
    NumericCandidateSource,
    build_finqa_numeric_sources,
    build_numeric_candidate_manifest,
    extract_finqa_numeric_candidates,
    extract_numeric_candidate_corpus,
    extract_numeric_candidates,
)
from app.external_datasets.finqa import FinQACase


def _finqa_case() -> FinQACase:
    return FinQACase.model_validate(
        {
            "pre_text": ["In 2020, revenue increased."],
            "post_text": ["Page 12 contains the notes."],
            "filename": "report.pdf",
            "table_ori": [
                ["", "2020", "2019"],
                ["Revenue", "$120 million", "$100 million"],
            ],
            "table": [
                ["", "2020", "2019"],
                ["Revenue", "$120 million", "$100 million"],
            ],
            "qa": {
                "question": "What was the revenue change?",
                "answer": "20",
                "explanation": "",
                "ann_table_rows": [1],
                "ann_text_rows": [],
                "steps": [],
                "program": "subtract(120, 100)",
                "gold_inds": {
                    "table_1": (
                        "the Revenue of 2020 is $120 million ; "
                        "the Revenue of 2019 is $100 million ;"
                    )
                },
                "exe_ans": 20,
                "tfidftopn": {},
                "program_re": "subtract(120, 100)",
                "model_input": [],
            },
            "id": "report.pdf-1",
            "table_retrieved": [],
            "text_retrieved": [],
            "table_retrieved_all": [],
            "text_retrieved_all": [],
        }
    )


@pytest.mark.parametrize(
    ("text", "unit_hint", "value", "unit", "scale", "sign"),
    [
        ("$2.5 million", "usd", "2500000", "usd", "million", 1),
        ("$300 thousand", "usd", "300000", "usd", "thousand", 1),
        ("12%", None, "0.12", "ratio", "percent", 1),
        ("35 bps", None, "0.0035", "ratio", "basis_point", 1),
        ("(120)", "usd", "-120", "usd", "one", -1),
        ("-$1,200.50", None, "-1200.50", "usd", "one", -1),
        ("EUR 2 billion", None, "2000000000", "eur", "billion", 1),
    ],
)
def test_financial_formats_normalize_to_decimal_base_units(
    text: str,
    unit_hint: str | None,
    value: str,
    unit: str,
    scale: str,
    sign: int,
) -> None:
    candidate = extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="cell-1",
        text=text,
        kind="table_cell",
        table_id="table-main",
        row_header="Revenue",
        column_header="FY2020",
        unit_hint=unit_hint,
    )[0]

    assert candidate.normalized_value == Decimal(value)
    assert candidate.unit == unit
    assert candidate.scale == scale
    assert candidate.sign == sign
    assert candidate.metric == "Revenue"
    assert candidate.period == "2020"
    assert candidate.fiscal_year == 2020
    assert candidate.provenance_span.start == 0
    assert candidate.provenance_span.end == len(text)
    assert candidate.provenance_span.text_sha256 == hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def test_table_header_scale_is_inherited_without_model_inference() -> None:
    candidate = extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="cell-7",
        text="120",
        kind="table_cell",
        table_id="income-statement",
        row_header="Net income (USD millions)",
        column_header="FY 2020",
        unit_hint="usd",
    )[0]

    assert candidate.normalized_value == Decimal("120000000")
    assert candidate.metric == "Net income (USD millions)"
    assert candidate.period == "2020"
    assert candidate.unit == "usd"
    assert candidate.scale == "million"
    assert candidate.table_id == "income-statement"
    assert candidate.row_header == "Net income (USD millions)"
    assert candidate.column_header == "FY 2020"


def test_text_period_is_bound_only_when_clause_has_one_explicit_year() -> None:
    unambiguous = extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="text-1",
        text="In 2020, revenue was $120 million.",
        kind="text",
    )
    amount = next(candidate for candidate in unambiguous if candidate.role == "operand")
    year = next(
        candidate for candidate in unambiguous if candidate.role == "period_label"
    )

    assert amount.period == "2020"
    assert amount.fiscal_year == 2020
    assert year.normalized_value == Decimal("2020")

    ambiguous = extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="text-2",
        text="Revenue was 100 in 2019 and 120 in 2020",
        kind="text",
    )
    amounts = [
        candidate
        for candidate in ambiguous
        if candidate.role == "operand"
    ]
    assert [candidate.normalized_value for candidate in amounts] == [
        Decimal("100"),
        Decimal("120"),
    ]
    assert all(candidate.period is None for candidate in amounts)


def test_page_ordinals_and_years_are_not_default_operands() -> None:
    candidates = extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="text-3",
        text="Page 12, the 3rd appendix reports FY2020 revenue of 100.",
        kind="text",
    )
    by_text = {candidate.raw_text: candidate for candidate in candidates}

    assert by_text["12"].role == "page_number"
    assert by_text["3rd"].role == "ordinal"
    assert by_text["2020"].role == "period_label"
    assert by_text["100"].role == "operand"


def test_unknown_metadata_is_preserved_as_unknown() -> None:
    candidate = extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="text-4",
        text="The reported amount was 42.",
        kind="text",
    )[0]

    assert candidate.metric is None
    assert candidate.entity is None
    assert candidate.period is None
    assert candidate.fiscal_year is None
    assert candidate.unit == "unknown"
    assert candidate.scale == "one"


def test_same_exact_input_has_stable_candidate_identity() -> None:
    kwargs = {
        "source_id": "report.pdf",
        "evidence_id": "cell-5",
        "text": "$1,200 thousand",
        "kind": "table_cell",
        "table_id": "table-main",
        "row_header": "Revenue",
        "column_header": "2020",
        "unit_hint": "usd",
    }

    first = extract_numeric_candidates(**kwargs)[0]
    second = extract_numeric_candidates(**kwargs)[0]

    assert first == second
    assert first.candidate_id == second.candidate_id


def test_equal_values_at_different_spans_have_distinct_ids() -> None:
    candidates = extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id="text-5",
        text="100 then 100",
        kind="text",
    )

    assert [candidate.normalized_value for candidate in candidates] == [
        Decimal("100"),
        Decimal("100"),
    ]
    assert candidates[0].candidate_id != candidates[1].candidate_id


def test_generated_format_matrix_preserves_values_and_repeatability() -> None:
    generated_cases = {
        "0": "0",
        "1": "1",
        "12": "12",
        "1,200": "1200",
        "12 thousand": "12000",
        "12 million": "12000000",
        "12 billion": "12000000000",
        "0.5%": "0.005",
        "50 bps": "0.0050",
        "(1,200)": "-1200",
    }

    for index, (text, expected) in enumerate(generated_cases.items()):
        kwargs = {
            "source_id": "generated-fixture",
            "evidence_id": f"value-{index}",
            "text": text,
            "kind": "text",
        }
        first = extract_numeric_candidates(**kwargs)[0]
        second = extract_numeric_candidates(**kwargs)[0]
        assert first.normalized_value == Decimal(expected)
        assert first.candidate_id == second.candidate_id
        assert first.provenance_span == second.provenance_span


def test_conflicting_unit_or_scale_hints_fail_closed() -> None:
    with pytest.raises(ValueError, match="unit hint"):
        extract_numeric_candidates(
            source_id="report.pdf",
            evidence_id="cell-6",
            text="$120",
            kind="table_cell",
            table_id="table-main",
            unit_hint="eur",
        )

    with pytest.raises(ValueError, match="contradicts table scale"):
        extract_numeric_candidates(
            source_id="report.pdf",
            evidence_id="cell-7",
            text="120 thousand",
            kind="table_cell",
            table_id="table-main",
            row_header="Revenue (millions)",
            unit_hint="usd",
        )


def test_public_manifest_contains_counts_and_hashes_but_no_source_text() -> None:
    sources = [
        NumericCandidateSource(
            source_id="synthetic-report",
            evidence_id="cell-1",
            text="$2.5 million",
            kind="table_cell",
            table_id="table-main",
            row_header="Revenue",
            column_header="2020",
            unit_hint="usd",
        ),
        NumericCandidateSource(
            source_id="synthetic-report",
            evidence_id="text-1",
            text="Page 12 reports a 35 bps change.",
            kind="text",
        ),
    ]
    corpus = extract_numeric_candidate_corpus(sources)
    manifest = build_numeric_candidate_manifest(
        corpus=corpus,
        source_artifact_sha256="a" * 64,
        extractor_source_sha256="b" * 64,
        source_record_count=len(sources),
    )
    public_json = json.dumps(manifest.model_dump(mode="json"), sort_keys=True)

    assert manifest.extraction_config_sha256 == EXTRACTION_CONFIG_SHA256
    assert manifest.source_record_count == 2
    assert manifest.candidate_count == 3
    assert manifest.counts_by_role == {"operand": 2, "page_number": 1}
    assert manifest.rejected_noise_counts == {"non_operand_page_number": 1}
    assert "$2.5 million" not in public_json
    assert "synthetic-report" not in public_json
    assert "cell-1" not in public_json
    assert "num-" not in public_json


def test_finqa_adapter_uses_cells_and_explicit_headers_without_row_flattening() -> None:
    sources = build_finqa_numeric_sources(
        _finqa_case(),
        admitted_evidence_ids={"table_1"},
    )

    assert len(sources) == 2
    assert {source.text for source in sources} == {
        "$120 million",
        "$100 million",
    }
    assert {source.row_header for source in sources} == {"Revenue"}
    assert {source.column_header for source in sources} == {"2019", "2020"}
    assert {source.evidence_id for source in sources} == {"table_1"}
    assert all("the Revenue of" not in source.text for source in sources)

    corpus = extract_finqa_numeric_candidates(
        _finqa_case(),
        admitted_evidence_ids={"table_1"},
    )
    by_period = {candidate.period: candidate for candidate in corpus.candidates}
    assert by_period["2020"].normalized_value == Decimal("120000000")
    assert by_period["2019"].normalized_value == Decimal("100000000")
    assert all(candidate.metric == "Revenue" for candidate in corpus.candidates)


def test_finqa_adapter_rejects_unknown_admitted_evidence_id() -> None:
    with pytest.raises(ValueError, match="not present"):
        build_finqa_numeric_sources(
            _finqa_case(),
            admitted_evidence_ids={"table_999"},
        )
