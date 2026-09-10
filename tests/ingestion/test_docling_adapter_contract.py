import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from experiments.document_quality_v1.docling_worker import adapt_document, verify_models


def table_document(*, merged=False, header=True, pages=(3,)):
    cells = [
        [
            NS(
                text=t,
                column_header=i == 0 and header,
                row_span=2 if merged else 1,
                col_span=1,
                row_section=False,
            )
            for t in values
        ]
        for i, values in enumerate([["Grade", "CNY/night"], ["G24", "550.00"]])
    ]
    item = NS(
        prov=[NS(page_no=p) for p in pages],
        self_ref="#/tables/0",
        data=NS(grid=cells, table_cells=sum(cells, [])),
        caption_text=lambda doc: "Office policy",
    )
    return NS(name="policy", iterate_items=lambda: iter([(item, 0)]))


def test_finite_docling_adapter_retains_page_and_literal_cells():
    parsed = adapt_document(table_document())
    assert parsed.tables[0].locator.start == 3
    assert parsed.tables[0].rows == [["G24", "550.00"]]


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"merged": True}, "merged_cells"),
        ({"header": False}, "header_not_explicit"),
        ({"pages": (3, 4)}, "multi_page"),
    ],
)
def test_ambiguous_docling_tables_are_not_flattened(kwargs, reason):
    with pytest.raises(ValueError, match=reason):
        adapt_document(table_document(**kwargs))


def test_missing_or_changed_model_artifacts_never_load(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_models(tmp_path)
    model = tmp_path / "model.bin"
    model.write_bytes(b"original")
    (tmp_path / "MODEL_LOCK.json").write_text(
        json.dumps(
            {"files": [{"path": "model.bin", "sha256": hashlib.sha256(b"original").hexdigest()}]}
        )
    )
    verify_models(tmp_path)
    model.write_bytes(b"changed")
    with pytest.raises(ValueError, match="model_hash_mismatch"):
        verify_models(tmp_path)
