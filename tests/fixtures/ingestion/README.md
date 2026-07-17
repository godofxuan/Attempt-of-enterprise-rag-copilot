# Ingestion Binary Fixtures

These files are synthetic parser fixtures. They contain no real company data.

| File | Purpose | SHA256 |
|---|---|---|
| `sample_policy.pdf` | One text page followed by one blank page | `4a15d04441319c619ec3a967696e3d5fc173a4ae2ee93bdf90a7fd0c5d30f60e` |
| `empty_page.pdf` | One blank page for fail-closed empty extraction | `2a00b59be4df7c668b9281f6a659536d12a95b9bd963bc44a0250defce3112e7` |
| `sample_policy.docx` | Ordered headings, paragraphs, and a two-column table | `9c9ffd203db25fb1084e1fa37b28e796c18f0ee41758103f6b35647479a265bf` |

The PDF fixtures were created locally as digitally born PDFs. They do not test OCR. The DOCX fixture was created with python-docx 1.2.0.
