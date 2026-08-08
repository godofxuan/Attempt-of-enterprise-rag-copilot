from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.external_datasets.uda_finance import (
    DEFAULT_PROTOCOL_PATH,
    UdaFinanceQaRow,
    extract_selected_pdfs,
    load_uda_finance_protocol,
    select_uda_finance_cases,
    selection_sha256,
)


def _rows() -> list[UdaFinanceQaRow]:
    rows: list[UdaFinanceQaRow] = []
    for company_index in range(6):
        company = f"C{company_index}"
        year = 2010 + company_index
        doc_name = f"{company}_{year}"
        for question_index in range(4):
            rows.append(
                UdaFinanceQaRow(
                    doc_name=doc_name,
                    q_uid=(
                        f"{company}/{year}/page_{question_index + 1}.pdf-"
                        f"{question_index}"
                    ),
                    question=f"question {company_index} {question_index}",
                    answer_1="1",
                    answer_2="1.0",
                    company_id=company,
                    report_year=year,
                    page_number=question_index + 1,
                )
            )
    return rows


def test_selection_is_deterministic_company_disjoint_and_fixed_size() -> None:
    kwargs = {
        "seed": "uda-finance-test-seed",
        "minimum_questions_per_document": 4,
        "dev_company_count": 2,
        "test_company_count": 3,
        "cases_per_document": 3,
    }
    first = select_uda_finance_cases(_rows(), **kwargs)
    second = select_uda_finance_cases(list(reversed(_rows())), **kwargs)

    assert first == second
    assert selection_sha256(first) == selection_sha256(second)
    assert sum(item.split == "dev" for item in first) == 2
    assert sum(item.split == "test" for item in first) == 3
    assert len({item.company_id for item in first}) == 5
    assert all(len(item.q_uids) == 3 for item in first)


def test_selection_rejects_an_underpowered_population() -> None:
    with pytest.raises(ValueError, match="too few eligible companies"):
        select_uda_finance_cases(
            _rows(),
            seed="seed",
            minimum_questions_per_document=5,
            dev_company_count=2,
            test_company_count=3,
            cases_per_document=3,
        )


def test_row_requires_one_answer_but_not_both() -> None:
    row = _rows()[0].model_copy(update={"answer_2": ""})
    assert UdaFinanceQaRow.model_validate(row.model_dump()).answer_1 == "1"
    with pytest.raises(ValueError, match="at least one answer"):
        UdaFinanceQaRow.model_validate(
            row.model_copy(update={"answer_1": ""}).model_dump()
        )


def test_selected_pdf_extraction_is_exact_and_non_overwriting(tmp_path: Path) -> None:
    archive = tmp_path / "docs.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("fin_docs/A_2020.pdf", b"%PDF-a")
        output.writestr("fin_docs/B_2021.pdf", b"%PDF-b")
        output.writestr("fin_docs/unselected.pdf", b"%PDF-c")
    destination = tmp_path / "selected"

    extracted = extract_selected_pdfs(
        archive,
        destination,
        ["A_2020", "B_2021"],
    )

    assert set(extracted) == {"A_2020", "B_2021"}
    assert sorted(path.name for path in destination.iterdir()) == [
        "A_2020.pdf",
        "B_2021.pdf",
    ]
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        extract_selected_pdfs(archive, destination, ["A_2020"])


def test_selected_pdf_extraction_rejects_zip_slip(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../A_2020.pdf", b"%PDF-a")

    with pytest.raises(ValueError, match="unsafe path"):
        extract_selected_pdfs(archive, tmp_path / "out", ["A_2020"])


def test_committed_protocol_is_strict_and_frozen() -> None:
    protocol, protocol_sha256 = load_uda_finance_protocol(DEFAULT_PROTOCOL_PATH)

    assert protocol.dev_case_count == 64
    assert protocol.test_case_count == 96
    assert protocol.test_execution_limit == 1
    assert protocol.selection_sha256 == (
        "cf167cfa4603f6d0877650721b73aec952c5ec4e8ed6d461d4eed33c401b1e4e"
    )
    assert len(protocol_sha256) == 64
