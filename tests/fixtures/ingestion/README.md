# Ingestion Binary Fixtures

These files are synthetic parser fixtures. They contain no real company data.

| File | Purpose | SHA256 |
|---|---|---|
| `sample_policy.pdf` | One text page followed by one blank page | `4a15d04441319c619ec3a967696e3d5fc173a4ae2ee93bdf90a7fd0c5d30f60e` |
| `empty_page.pdf` | One blank page for fail-closed empty extraction | `2a00b59be4df7c668b9281f6a659536d12a95b9bd963bc44a0250defce3112e7` |
| `sample_policy.docx` | Ordered headings, paragraphs, and a two-column table | `9c9ffd203db25fb1084e1fa37b28e796c18f0ee41758103f6b35647479a265bf` |
| `eml/plain.eml` | Plain body, headers, and data-only prompt-injection sentence | `ee907ea0ec5e25fa2634c9cbc8b928e6343e833185aef2cc8e34f0f74a4a2dec` |
| `eml/html_only.eml` | HTML fallback with remote and active elements | `02187ff8644e1f2d729e74a07b55077262c1c1f1540787dd66050abb6a3cff3b` |
| `eml/alternative.eml` | Deterministic plain-over-HTML multipart choice | `ad59299ca7d6ea0ed8b430b163b4ee599ef7282a0ceecdacad5322b987ff32072` |
| `eml/mixed_attachment.eml` | Transfer-encoded child attachment and control-data boundary | `b441668d53b5c6a50f549903db33f97956108f857aa8d55116ade051016f425c` |
| `eml/nested.eml` | Nested `message/rfc822` lineage and depth | `b95acd1eb242a7d15ae55a1a9db75a4eed266728732cee20138beba1ff17c354` |
| `eml/malformed_boundary.eml` | Structural MIME boundary failure | `cd262f3abc201ce1a640156cc6e624789227b5812d3bde64e1f9668027bbfa30` |

The PDF fixtures were created locally as digitally born PDFs. They do not test OCR. The DOCX fixture was created with python-docx 1.2.0.

The EML fixtures use only fictional `example.invalid` identities. Generated
test cases add bounded transfer-encoding, attachment-budget, encrypted,
unsupported archive, `.msg`, malformed-header, and fault-injection variants.
No fixture sender, recipient, subject, body, or attachment name is emitted by
the public G4 trace.
